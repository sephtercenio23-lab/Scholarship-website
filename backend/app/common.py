import re
import uuid
from collections import defaultdict

from fastapi import HTTPException

from .catalog import (
    BENEFIT_TEXT,
    DEADLINE_TEXT,
    DEFAULT_TERM,
    SCHOLARSHIPS,
    term_label,
    term_sort_key,
)

ACADEMIC_YEAR_FORMAT = re.compile(r"^(\d{4})\s*[-/\u2013]\s*(\d{4})$")

APPLICATION_SELECT = """
select a.id, a.code, a.student_id as owner_id, a.term_id, a.scholarship_type, a.program,
       a.year_level, a.gwa, a.lowest_grade, a.has_failing_grade, a.has_incomplete_grade,
       a.has_dropped_grade, a.status, a.remarks, a.evaluated_by, a.discount_percent,
       a.duty_hours, a.duty_completed, a.report_received_at, a.deleted_at, a.created_at,
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


def number(value):
    return float(value) if value is not None else None


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
        conn.execute(
            """
            insert into term_scholarships
              (term_id, scholarship_key, status, benefit, deadline, eligibility, sort_order)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (term_id, scholarship_key) do nothing
            """,
            (term_id, item["key"], item["status"], item["benefit"], item["deadline"], item["eligibility"], index),
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
    if row["id"] == current["id"]:
        return "Current"
    return "Past" if key < current_key else "Upcoming"


def scholarship_out(row):
    return {
        "key": row["scholarship_key"],
        "status": row["status"],
        "benefit": row["benefit"],
        "deadline": row["deadline"],
        "eligibility": list(row["eligibility"] or []),
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


def build_applications(conn, rows):
    if not rows:
        return []
    current = ensure_current_term(conn)
    ids = [row["id"] for row in rows]
    documents = defaultdict(dict)
    for doc in conn.execute(
        "select * from application_documents where application_id = any(%s::uuid[])", (ids,)
    ):
        documents[doc["application_id"]][doc["doc_key"]] = {
            "name": doc["name"],
            "path": doc["path"],
            "uploadedAt": iso(doc["uploaded_at"]),
            "sizeBytes": doc["size_bytes"],
            "mimeType": doc["mime_type"],
        }
    history = defaultdict(list)
    for entry in conn.execute(
        "select * from application_history where application_id = any(%s::uuid[]) order by created_at, id",
        (ids,),
    ):
        history[entry["application_id"]].append(
            {
                "status": entry["status"],
                "date": iso(entry["created_at"]),
                "by": entry["actor_name"] or "",
                "remarks": entry["remarks"] or "",
                "eventType": entry["event_type"],
            }
        )
    result = []
    for row in rows:
        label = term_label(row["trimester"], row["academic_year"])
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
                "gwa": number(row["gwa"]),
                "lowestGrade": number(row["lowest_grade"]),
                "hasFailingGrade": row["has_failing_grade"],
                "hasIncompleteGrade": row["has_incomplete_grade"],
                "hasDroppedGrade": row["has_dropped_grade"],
                "dutyHours": row["duty_hours"],
                "dutyCompleted": row["duty_completed"],
                "reportReceivedAt": iso(row["report_received_at"]),
                "termId": str(row["term_id"]),
                "term": label,
                "trimester": row["trimester"],
                "academicYear": row["academic_year"],
                "archived": term_state(row, current) == "Past",
                "deleted": row["deleted_at"] is not None,
                "dateSubmitted": iso(row["created_at"]),
                "documents": documents[row["id"]],
                "history": history[row["id"]],
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


def staff_ids(conn, exclude=None):
    rows = conn.execute(
        "select id from users where role in ('staff', 'admin') and deleted_at is null"
    ).fetchall()
    return [row["id"] for row in rows if str(row["id"]) != str(exclude)]
