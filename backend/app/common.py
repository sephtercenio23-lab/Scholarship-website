import logging
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Json

from .config import get_settings

logger = logging.getLogger("sams.db")

from .catalog import (
    APPROVED_STATUSES,
    APPROVAL_STAGE_EVENTS,
    APPROVAL_STAGE_LABELS,
    APPROVAL_STAGES,
    BASE_DOCUMENT_ATTEMPTS,
    BENEFIT_TEXT,
    DEADLINE_TEXT,
    DEFAULT_TERM,
    DOCUMENT_LABELS,
    DOCUMENT_KEYS,
    FINANCE_STATUS,
    NON_STUDENT_ROLES,
    PENDING_APPROVAL_STATUSES,
    ROLE_LABELS,
    SCHOLARSHIP_BY_KEY,
    SCHOLARSHIPS,
    STAGE_STATUS,
    term_label,
    term_sort_key,
)
from .security import bad_request

MANILA_TZ = timezone(timedelta(hours=8))

# Roles the users_role_check constraint must allow. Mirrors supabase/migrations/20261028_approval_roles.sql.
USERS_ROLE_CHECK = "role in ('student', 'staff', 'admin', 'president', 'executive_president', 'super_admin')"
_role_check_lock = threading.Lock()
_role_check_ready = False


def constraint_supports_approval_roles(conn):
    """True when nothing blocks the approval-flow roles on public.users.

    Used as a fallback when this app cannot run DDL (lacks ALTER privilege): if the
    constraint is already current — or missing entirely — inserts of the new roles
    will succeed, so the check can be cached and the request proceeds.
    """
    try:
        row = conn.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = 'public.users'::regclass and conname = 'users_role_check'"
        ).fetchone()
    except Exception:
        return False
    if row is None:
        return True
    definition = row[0] or ""
    return all(
        role in definition
        for role in ("student", "staff", "admin", "president", "executive_president", "super_admin")
    )


def ensure_user_role_check():
    """Bring users_role_check up to date so the approval-flow roles can be stored.

    Databases created from an older schema carry a users_role_check constraint that
    only allows student/staff/admin, so every insert of president, executive_president
    or super_admin fails and surfaces as a 500. This rewrites the constraint on a
    dedicated connection (atomically, before the request transaction opens), so it
    never deadlocks with an in-flight request. If it cannot run — for example the
    database user lacks ALTER privilege — it logs a warning and returns False; the
    route then reports an actionable error instead of a bare 500.
    """
    global _role_check_ready
    if _role_check_ready:
        return True
    with _role_check_lock:
        if _role_check_ready:
            return True
        try:
            conn = psycopg.connect(
                get_settings().database_url,
                autocommit=True,
                prepare_threshold=None,
                connect_timeout=10,
            )
        except Exception:
            logger.warning("Could not connect to verify users_role_check", exc_info=True)
            return False
        try:
            if not constraint_supports_approval_roles(conn):
                try:
                    with conn.transaction():
                        conn.execute("alter table public.users drop constraint if exists users_role_check")
                        conn.execute(f"alter table public.users add constraint users_role_check check ({USERS_ROLE_CHECK})")
                except Exception:
                    logger.warning(
                        "Could not update users_role_check; apply supabase/migrations/20261028_approval_roles.sql",
                        exc_info=True,
                    )
                    return False
            _role_check_ready = True
            logger.info("users_role_check now allows all approval-flow roles.")
            return True
        finally:
            conn.close()


def migration_fix_hint(constraint_name=None):
    if constraint_name and constraint_name != "users_role_check":
        return (
            f"The database rejected the change (constraint: {constraint_name}). "
            "Ask the database administrator to apply the latest migration in supabase/migrations."
        )
    return (
        "The database does not allow this role yet. Apply supabase/apply_all.sql in the Supabase SQL editor "
        "(or `python scripts/apply_migrations.py`), then try again."
    )


def parse_deadline_at(value):
    text = " ".join(str(value or "").split())
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("Deadline date and time must be a valid date and time.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MANILA_TZ)
    return parsed.astimezone(timezone.utc)


def deadline_is_past(deadline_at):
    return deadline_at is not None and deadline_at < datetime.now(timezone.utc)


def deadline_text(value):
    """Readable Asia/Manila label for a deadline, e.g. December 15, 2026, 5:00 PM."""
    if not value:
        return DEADLINE_TEXT
    local = value.astimezone(MANILA_TZ)
    label = f"{local:%B} {local.day}, {local.year}"
    if local.hour or local.minute:
        label += f", {local.strftime('%I:%M %p').lstrip('0')}"
    return label


def set_term_scholarship_deadline(conn, term_id, deadline_at):
    conn.execute(
        "update term_scholarships set deadline_at = %s, deadline = %s where term_id = %s",
        (deadline_at, deadline_text(deadline_at), term_id),
    )


# Approval stages use the stored role keys, not their display titles.
def role_label(role):
    return ROLE_LABELS.get(role, role or "")


def approval_stage_for_role(role):
    if role == "staff":
        return "staff"
    if role == "president":
        return "president"
    if role == "executive_president":
        return "executive_president"
    return None


def can_act_on_stage(role, stage):
    return approval_stage_for_role(role) == stage


def next_approval_stage(approvals):
    approvals = approvals or {}
    for stage in APPROVAL_STAGES:
        entry = approvals.get(stage) or approvals.get(
            "executivePresident" if stage == "executive_president" else stage
        )
        if not entry:
            return stage
    return None


def student_status(status):
    # Students only ever see Under Evaluation until all three approvals finish, then Approved.
    # "Sent to Finance" is the stored status once Finance received the scholar; students see Approved.
    if status in (STAGE_STATUS["staff"], STAGE_STATUS["president"]):
        return "Under Evaluation"
    if status in (STAGE_STATUS["executive_president"], FINANCE_STATUS, "Exported"):
        return "Approved"
    return status


def approval_out(entry):
    if not entry:
        return None
    return {"by": entry.get("by") or "", "at": entry.get("at"), "role": entry.get("role") or ""}


def export_approvals(applications):
    """Certification block for exports: only the approvers who actually approved.

    One signature per level, in approval order, names in uppercase. When several people
    approved the same level across the applications, the earliest recorded approval signs for it.
    """
    found = {}
    for app in applications or []:
        approvals = app.get("approvals") or {}
        for stage in APPROVAL_STAGES:
            key = "executivePresident" if stage == "executive_president" else stage
            entry = approvals.get(stage) or approvals.get(key)
            name = str((entry or {}).get("by") or "").strip()
            if not name:
                continue
            candidate = (str(entry.get("at") or ""), name)
            if stage not in found or candidate < found[stage]:
                found[stage] = candidate
    result = []
    for stage in APPROVAL_STAGES:
        if stage not in found:
            continue
        item = {
            "stage": stage,
            "name": found[stage][1].upper(),
            "position": APPROVAL_STAGE_LABELS[stage],
        }
        if stage == "staff":
            item["office"] = "CSS Office"
        result.append(item)
    return result

AUDIT_ACTIONS = (
    "account_created",
    "account_updated",
    "account_deleted",
    "term_changed",
    "scholarships_updated",
    "application_deleted",
    "application_reopened",
    "application_approved",
    "application_rejected",
    "application_changed_after_finance",
    "applications_exported",
    "scholars_sent_to_finance",
    "finance_correction_sent",
    "appeal_accepted",
    "appeal_declined",
    "password_changed",
    "account_locked",
)


def audit(conn, user, action, target_type, target_id, details=None):
    conn.execute(
        """
        insert into audit_log (actor_id, actor_name, actor_role, action, target_type, target_id, details)
        values (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user["id"] if user else None,
            user["full_name"] if user else None,
            user["role"] if user else None,
            action,
            target_type,
            str(target_id) if target_id is not None else None,
            Json(details or {}),
        ),
    )


def audit_out(row):
    return {
        "id": row["id"],
        "actorId": str(row["actor_id"]) if row["actor_id"] else "",
        "actorName": row["actor_name"] or "",
        "actorRole": row["actor_role"] or "",
        "action": row["action"],
        "targetType": row["target_type"],
        "targetId": str(row["target_id"]) if row["target_id"] else "",
        "details": row["details"] or {},
        "createdAt": iso(row["created_at"]),
    }

ACADEMIC_YEAR_FORMAT = re.compile(r"^(\d{4})\s*[-/\u2013]\s*(\d{4})$")

APPLICATION_SELECT = """
select a.id, a.code, a.student_id as owner_id, a.term_id, a.scholarship_type, a.program,
       a.year_level, a.has_failing_grade, a.has_incomplete_grade,
       a.has_dropped_grade, a.status, a.remarks, a.evaluated_by, a.discount_percent,
       a.past_discount, a.deleted_at, a.created_at,
       a.changed_after_finance, a.finance_sent_at,
       u.full_name as student_name, u.student_id as student_number, u.email as student_email,
       t.trimester, t.academic_year
from applications a
join users u on u.id = a.student_id
join academic_terms t on t.id = a.term_id
"""


def parse_uuid(value, status_code=404, message="Not found."):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status_code, detail=message)


def iso(value):
    return value.isoformat() if value else None


def user_out(row):
    return {
        "id": str(row["id"]),
        "fullName": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "studentId": row["student_id"] or "",
        "program": row["program"] or "",
        "yearLevel": row["year_level"] or "",
    }


def account_out(row):
    return {**user_out(row), "createdAt": iso(row["created_at"])}


def normalize_academic_year(value):
    match = ACADEMIC_YEAR_FORMAT.match(str(value or "").strip())
    if not match:
        raise HTTPException(status_code=400, detail="Academic year must be two years like 2026-2027.")
    start, end = int(match.group(1)), int(match.group(2))
    if end != start + 1:
        raise HTTPException(
            status_code=400,
            detail=f"The second year must follow the first (you typed {start}-{end}; did you mean {start}-{start + 1}?).",
        )
    if start < 2000 or start > 2100:
        raise HTTPException(
            status_code=400, detail="Please type a realistic academic year (between 2000 and 2100)."
        )
    return f"{start}\u2013{end}"


def default_scholarships():
    return [
        {
            "key": item["key"],
            "status": "Open",
            "benefit": BENEFIT_TEXT,
            "deadline": DEADLINE_TEXT,
            "eligibility": list(item["eligibility"]),
        }
        for item in SCHOLARSHIPS
    ]


def seed_scholarships(conn, term_id, scholarships):
    for index, item in enumerate(scholarships):
        deadline_at = (
            parse_deadline_at(item["deadlineAt"]) if "deadlineAt" in item else None
        )
        conn.execute(
            """
            insert into term_scholarships
              (term_id, scholarship_key, status, benefit, deadline, deadline_at, eligibility, sort_order)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (term_id, scholarship_key) do nothing
            """,
            (
                term_id,
                item["key"],
                item["status"],
                item["benefit"],
                item["deadline"],
                deadline_at,
                item["eligibility"],
                index,
            ),
        )


def ensure_current_term(conn):
    row = conn.execute("select * from academic_terms where is_current").fetchone()
    if row:
        return row
    conn.execute("select pg_advisory_xact_lock(7001)")
    row = conn.execute("select * from academic_terms where is_current").fetchone()
    if row:
        return row
    row = conn.execute(
        """
        insert into academic_terms (trimester, academic_year, is_current)
        values (%s, %s, true)
        on conflict (trimester, academic_year) do update set is_current = true
        returning *
        """,
        (DEFAULT_TERM["trimester"], DEFAULT_TERM["academic_year"]),
    ).fetchone()
    seed_scholarships(conn, row["id"], default_scholarships())
    return row


def row_term_key(row):
    return term_sort_key(row["academic_year"], row["trimester"])


def term_state(row, current):
    key, current_key = row_term_key(row), row_term_key(current)
    if row.get("term_id", row["id"]) == current["id"]:
        return "Current"
    return "Past" if key < current_key else "Upcoming"


def scholarship_out(row):
    rule = SCHOLARSHIP_BY_KEY.get(row["scholarship_key"])
    effective_status = (
        "Closed"
        if row["status"] == "Closed" or deadline_is_past(row["deadline_at"])
        else "Open"
    )
    return {
        "key": row["scholarship_key"],
        "status": row["status"],
        "effectiveStatus": effective_status,
        "benefit": row["benefit"],
        "deadline": row["deadline"],
        "deadlineAt": iso(row["deadline_at"]),
        "eligibility": list(row["eligibility"] or []),
        "minGwa": rule["min_gwa"] if rule else None,
        "minLowest": rule["min_lowest"] if rule else None,
    }


def term_out(row, current, scholarships=None):
    return {
        "id": str(row["id"]),
        "trimester": row["trimester"],
        "academicYear": row["academic_year"],
        "label": term_label(row["trimester"], row["academic_year"]),
        "state": term_state(row, current),
        "scholarships": scholarships if scholarships is not None else [],
    }


def load_terms(conn):
    current = ensure_current_term(conn)
    terms = conn.execute("select * from academic_terms").fetchall()
    grouped = defaultdict(list)
    for item in conn.execute("select * from term_scholarships order by sort_order, scholarship_key"):
        grouped[item["term_id"]].append(scholarship_out(item))
    terms.sort(key=lambda row: row_term_key(row), reverse=True)
    return [term_out(row, current, grouped[row["id"]]) for row in terms], current


def document_allowance(conn, app_id, doc_key):
    row = conn.execute(
        """
        select extra_attempts from application_document_allowances
        where application_id = %s and doc_key = %s
        """,
        (app_id, doc_key),
    ).fetchone()
    return (row["extra_attempts"] if row else 0) or 0


def latest_document_submission(conn, app_id, doc_key):
    return conn.execute(
        """
        select * from application_document_submissions
        where application_id = %s and doc_key = %s
        order by attempt_no desc
        limit 1
        """,
        (app_id, doc_key),
    ).fetchone()


def ensure_document_upload_allowed(conn, app_row, doc_key):
    """Shared server-side rules for Letter of Intent / Agreement uploads."""
    label = DOCUMENT_LABELS[doc_key]
    if app_row["status"] not in APPROVED_STATUSES:
        raise bad_request(f"The {label} becomes available once your application is approved.")
    latest = latest_document_submission(conn, app_row["id"], doc_key)
    max_attempts = BASE_DOCUMENT_ATTEMPTS + document_allowance(conn, app_row["id"], doc_key)
    if latest:
        if latest["review_status"] == "Valid":
            raise bad_request(f"Your {label} has already been accepted.")
        if latest["review_status"] == "Pending":
            raise bad_request(f"Your {label} is still under review. Please wait for the result.")
        if latest["attempt_no"] >= max_attempts:
            raise bad_request(
                f"No attempts left for the {label}. Ask the CSS Office to allow another resubmission."
            )
    attempt_no = (latest["attempt_no"] if latest else 0) + 1
    return latest, attempt_no, max_attempts


def appeal_out(row):
    return {
        "id": str(row["id"]),
        "applicationId": str(row["application_id"]),
        "reason": row["reason"],
        "status": row["status"],
        "response": row["response"] or "",
        "respondedBy": row["responded_by"] or "",
        "createdAt": iso(row["created_at"]),
        "respondedAt": iso(row["responded_at"]),
    }


def build_applications(conn, rows):
    if not rows:
        return []
    current = ensure_current_term(conn)
    ids = [row["id"] for row in rows]
    documents = defaultdict(dict)
    for doc in conn.execute(
        "select * from application_documents where application_id = any(%s::uuid[])", (ids,)
    ):
        if doc["doc_key"] not in DOCUMENT_KEYS:
            continue
        documents[doc["application_id"]][doc["doc_key"]] = {
            "name": doc["name"],
            "path": doc["path"],
            "uploadedAt": iso(doc["uploaded_at"]),
            "sizeBytes": doc["size_bytes"],
            "mimeType": doc["mime_type"],
        }
    post_documents = defaultdict(dict)
    submission_paths = defaultdict(list)
    for sub in conn.execute(
        """
        select s.*, coalesce(al.extra_attempts, 0) as extra_attempts
        from application_document_submissions s
        left join application_document_allowances al
          on al.application_id = s.application_id and al.doc_key = s.doc_key
        where s.application_id = any(%s::uuid[])
        order by s.application_id, s.doc_key, s.attempt_no desc
        """,
        (ids,),
    ):
        submission_paths[sub["application_id"]].append(sub["path"])
        if sub["doc_key"] not in post_documents[sub["application_id"]]:
            post_documents[sub["application_id"]][sub["doc_key"]] = {
                "attemptNo": sub["attempt_no"],
                "reviewStatus": sub["review_status"],
                "reviewReason": sub["review_reason"] or "",
                "reviewedBy": sub["reviewed_by"] or "",
                "reviewedAt": iso(sub["reviewed_at"]),
                "maxAttempts": BASE_DOCUMENT_ATTEMPTS + (sub["extra_attempts"] or 0),
                "name": sub["name"],
                "path": sub["path"],
                "uploadedAt": iso(sub["uploaded_at"]),
            }
    # Three-level approvals are read from history so existing saved data keeps loading without a schema change.
    approvals = {}
    stage_approvals = defaultdict(dict)
    evaluators = defaultdict(set)
    evaluator_roles = defaultdict(set)
    stage_by_event = {event: stage for stage, event in APPROVAL_STAGE_EVENTS.items()}
    for entry in conn.execute(
        """
        select ah.application_id, ah.status, ah.event_type, ah.created_at, ah.actor_name,
               (
                 select u.role
                 from users u
                 where u.full_name = ah.actor_name
                   and u.role in ('staff', 'admin', 'president', 'executive_president', 'super_admin')
                 order by (u.deleted_at is null) desc, u.created_at desc
                 limit 1
               ) as actor_role
        from application_history ah
        where ah.application_id = any(%s::uuid[])
          and ah.status in (
            'Under Evaluation', 'Endorsed by Staff', 'Approved by President',
            'Approved by Executive President', 'Sent to Finance', 'Approved', 'Exported', 'Rejected'
          )
          and ah.event_type in (
            'status_changed',
            'staff_endorsed',
            'president_approved',
            'executive_approved',
            'reopened',
            'appeal_accepted',
            'finance_change_flagged',
            'finance_sent',
            'discount_changed',
            'document_accepted',
            'document_rejected',
            'document_resubmission_allowed'
          )
          and not exists (
            select 1
            from users stu
            where stu.full_name = ah.actor_name
              and stu.role = 'student'
              and not exists (
                select 1
                from users staff
                where staff.full_name = ah.actor_name
                  and staff.role in ('staff', 'admin', 'president', 'executive_president', 'super_admin')
              )
          )
        order by ah.created_at, ah.id
        """,
        (ids,),
    ):
        app_id = entry["application_id"]
        if entry["actor_name"]:
            evaluators[app_id].add(entry["actor_name"])
        event_type = entry.get("event_type", "status_changed")
        actor_role = entry.get("actor_role") or ("admin" if event_type == "reopened" else None)
        if actor_role in NON_STUDENT_ROLES:
            evaluator_roles[app_id].add(actor_role)
        if event_type in stage_by_event:
            stage = stage_by_event[event_type]
            stage_approvals[app_id][stage] = {
                "by": entry["actor_name"] or "",
                "at": iso(entry["created_at"]),
                "role": actor_role or "",
            }
            if entry["status"] in APPROVED_STATUSES:
                approvals[app_id] = entry
        elif event_type == "status_changed" and entry["status"] in APPROVED_STATUSES:
            approvals[app_id] = entry
            stage = approval_stage_for_role(actor_role)
            if stage and stage not in stage_approvals[app_id]:
                stage_approvals[app_id][stage] = {
                    "by": entry["actor_name"] or "",
                    "at": iso(entry["created_at"]),
                    "role": actor_role or "",
                }
        elif event_type in ("reopened", "appeal_accepted", "finance_change_flagged") or (
            event_type == "status_changed" and entry["status"] not in APPROVED_STATUSES
        ):
            approvals.pop(app_id, None)
            stage_approvals.pop(app_id, None)
    appeals = {}
    for appeal in conn.execute(
        "select * from application_appeals where application_id = any(%s::uuid[])", (ids,)
    ):
        appeals[appeal["application_id"]] = appeal_out(appeal)
    result = []
    for row in rows:
        label = term_label(row["trimester"], row["academic_year"])
        approval = approvals.get(row["id"]) if row["status"] in APPROVED_STATUSES else None
        stages = stage_approvals.get(row["id"], {})
        approvals_out = {
            "staff": approval_out(stages.get("staff")),
            "president": approval_out(stages.get("president")),
            "executivePresident": approval_out(stages.get("executive_president")),
        }
        if row["status"] in APPROVED_STATUSES:
            final = stages.get("executive_president")
            if final:
                approval = {"actor_name": final["by"], "created_at": final["at"]}
            approval_stage = "complete"
        elif row["status"] in PENDING_APPROVAL_STATUSES:
            nxt = next_approval_stage(stages)
            approval_stage = "executivePresident" if nxt == "executive_president" else nxt
        else:
            approval_stage = None
        result.append(
            {
                "id": str(row["id"]),
                "code": row["code"],
                "studentUserId": str(row["owner_id"]),
                "studentName": row["student_name"],
                "studentId": row["student_number"] or "",
                "universityEmail": row["student_email"],
                "program": row["program"],
                "yearLevel": row["year_level"],
                "scholarshipType": row["scholarship_type"],
                "status": row["status"],
                "remarks": row["remarks"] or "",
                "evaluatedBy": row["evaluated_by"] or "",
                "discountPercent": row["discount_percent"],
                # Discount the student declared for the past term; null means not a scholar before.
                "pastDiscount": row.get("past_discount"),
                "hasFailingGrade": row["has_failing_grade"],
                "hasIncompleteGrade": row["has_incomplete_grade"],
                "hasDroppedGrade": row["has_dropped_grade"],
                "termId": str(row["term_id"]),
                "term": label,
                "trimester": row["trimester"],
                "academicYear": row["academic_year"],
                "archived": term_state(row, current) == "Past",
                "deleted": row["deleted_at"] is not None,
                "dateSubmitted": iso(row["created_at"]),
                "documents": documents[row["id"]],
                "postApprovalDocuments": post_documents[row["id"]],
                "submissionPaths": submission_paths[row["id"]],
                "approvedAt": (approval["created_at"] if isinstance(approval.get("created_at"), str) else iso(approval["created_at"])) if approval else None,
                "approvedBy": (approval["actor_name"] or "") if approval else "",
                "approvals": approvals_out,
                "approvalStage": approval_stage,
                # True when the application was edited after Finance already received it.
                "changedAfterFinance": bool(row.get("changed_after_finance")),
                "financeSentAt": iso(row.get("finance_sent_at")),
                "evaluators": sorted(evaluators[row["id"]]),
                "evaluatorRoles": sorted(evaluator_roles[row["id"]]),
                "appeal": appeals.get(row["id"]),
            }
        )
    return result


def load_applications(conn, where, params=()):
    rows = conn.execute(
        APPLICATION_SELECT + " where " + where + " order by a.created_at desc", params
    ).fetchall()
    return build_applications(conn, rows)


def load_application(conn, app_id, lock=False):
    sql = APPLICATION_SELECT + " where a.id = %s"
    if lock:
        sql += " for update of a"
    rows = conn.execute(sql, (app_id,)).fetchall()
    return rows[0] if rows else None


def application_out(conn, row):
    return build_applications(conn, [row])[0]


def add_history(conn, app_id, status, event_type, actor_name, remarks=""):
    conn.execute(
        """
        insert into application_history (application_id, status, event_type, actor_name, remarks)
        values (%s, %s, %s, %s, %s)
        """,
        (app_id, status, event_type, actor_name, remarks or None),
    )


def notify(conn, user_ids, app_id, message, kind="student"):
    for user_id in dict.fromkeys(user_ids):
        conn.execute(
            "insert into notifications (user_id, application_id, message, type) values (%s, %s, %s, %s)",
            (user_id, app_id, message, kind),
        )


def role_ids(conn, roles, exclude=None):
    rows = conn.execute(
        "select id, role from users where role in ('staff', 'admin', 'president', 'executive_president', 'super_admin') and deleted_at is null"
    ).fetchall()
    wanted = set(roles or NON_STUDENT_ROLES)
    result = []
    for row in rows:
        if str(row["id"]) == str(exclude):
            continue
        try:
            role = row["role"]
        except Exception:
            role = None
        if role is None or role in wanted:
            result.append(row["id"])
    return result


def staff_ids(conn, exclude=None):
    return role_ids(conn, NON_STUDENT_ROLES, exclude=exclude)


def student_ids(conn):
    rows = conn.execute(
        "select id from users where role = 'student' and deleted_at is null"
    ).fetchall()
    return [row["id"] for row in rows]
