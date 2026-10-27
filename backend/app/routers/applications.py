from decimal import Decimal

import psycopg
from fastapi import APIRouter, HTTPException, Request

from .. import storage
from ..catalog import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    BASE_DOCUMENT_ATTEMPTS,
    DOCUMENT_LABELS,
    INITIAL_DOCUMENT_KEYS,
    MAX_FILE_BYTES,
    POST_APPROVAL_DOCUMENT_KEYS,
    SCHOLARSHIP_BY_KEY,
    SCHOLARSHIP_TYPES,
    YEAR_LEVELS,
    program_not_offered,
)
from ..common import (
    add_history,
    application_out,
    audit,
    deadline_is_past,
    document_allowance,
    ensure_current_term,
    ensure_document_upload_allowed,
    latest_document_submission,
    load_application,
    load_applications,
    notify,
    parse_uuid,
    staff_ids,
    term_state,
)
from ..db import transaction
from ..deps import current_user
from ..schemas import (
    AllowResubmissionIn,
    ApplicationIn,
    DiscountIn,
    DocumentIn,
    DocumentReviewIn,
    DutyIn,
    ReopenIn,
    StatusIn,
)
from ..security import bad_request, check_letters_only

router = APIRouter()

PAST_TERM_MESSAGE = "This application belongs to a past term and is read-only."
TRANSITIONS = {
    ("Submitted", "Under Evaluation"),
    ("Under Evaluation", "Approved"),
    ("Under Evaluation", "Rejected"),
}


def not_found():
    return HTTPException(status_code=404, detail="Application not found.")


def is_past(conn, row):
    return term_state(row, ensure_current_term(conn)) == "Past"


def locked_application(conn, app_id):
    row = load_application(conn, parse_uuid(app_id, message="Application not found."), lock=True)
    if not row or row["deleted_at"] is not None:
        raise not_found()
    return row


def ensure_editable(conn, row):
    if is_past(conn, row):
        raise HTTPException(status_code=403, detail=PAST_TERM_MESSAGE)


def parse_discount(value):
    if value is None:
        return None
    if value != int(value) or value < 0 or value > 100:
        raise bad_request("Tuition fee discount must be a whole number from 0 to 100.")
    return int(value)


def check_stored_document(user_id, app_id, key, doc):
    parts = storage.parse_path(doc.path)
    if (
        parts["user"].lower() != str(user_id).lower()
        or parts["app"].lower() != str(app_id).lower()
        or parts["key"] != key
    ):
        raise bad_request(f"The {DOCUMENT_LABELS[key]} file path is not valid.")
    name = " ".join(str(doc.name or "").split())[:255]
    if not name or not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise bad_request(f"The {DOCUMENT_LABELS[key]} must be a PDF, JPG or PNG file.")
    info = storage.object_info(doc.path)
    if info is None:
        raise bad_request(
            f"The {DOCUMENT_LABELS[key]} file was not found in secure storage. Please upload it again."
        )
    size = info.get("size") or doc.sizeBytes
    mime = info.get("mimetype") or doc.mimeType
    if size is not None and (size <= 0 or size > MAX_FILE_BYTES):
        raise bad_request(f"The {DOCUMENT_LABELS[key]} must be 5 MB or smaller.")
    if mime and mime not in ALLOWED_MIME_TYPES:
        raise bad_request(f"The {DOCUMENT_LABELS[key]} must be a PDF, JPG or PNG file.")
    return name, doc.path, size, mime


def has_at_most_two_decimals(value):
    return Decimal(str(value)).as_tuple().exponent >= -2


def check_eligibility(body):
    rule = SCHOLARSHIP_BY_KEY[body.scholarshipType]
    if body.hasFailingGrade or body.hasIncompleteGrade or body.hasDroppedGrade:
        raise bad_request("Applicants with a failing grade, INC, or dropped remark are not eligible.")
    if body.gwa is not None and (body.gwa < 0 or body.gwa > 100):
        raise bad_request("GWA must be between 0 and 100.")
    if body.lowestGrade is not None and (body.lowestGrade < 0 or body.lowestGrade > 100):
        raise bad_request("Lowest grade must be between 0 and 100.")
    if body.gwa is not None and not has_at_most_two_decimals(body.gwa):
        raise bad_request("GWA can have at most 2 decimal places.")
    if body.lowestGrade is not None and not has_at_most_two_decimals(body.lowestGrade):
        raise bad_request("Lowest grade can have at most 2 decimal places.")
    if body.gwa is not None and body.lowestGrade is not None and body.lowestGrade > body.gwa:
        raise bad_request("Lowest grade cannot be higher than your GWA.")
    if body.gwa is not None and body.gwa < rule["min_gwa"]:
        raise bad_request(f"{body.scholarshipType} requires a GWA of at least {rule['min_gwa']}.")
    if body.lowestGrade is not None and body.lowestGrade < rule["min_lowest"]:
        raise bad_request(f"{body.scholarshipType} requires no grade below {rule['min_lowest']}.")


@router.get("/applications")
def my_applications(request: Request, active: bool = False):
    with transaction() as conn:
        user = current_user(conn, request, "student")
        where = "a.student_id = %s and a.deleted_at is null"
        params = [user["id"]]
        if active:
            where += " and t.is_current"
        return load_applications(conn, where, params)


@router.get("/applications/{app_id}")
def get_application(app_id: str, request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        row = load_application(conn, parse_uuid(app_id, message="Application not found."))
        if not row or row["deleted_at"] is not None:
            raise not_found()
        if user["role"] == "student" and str(row["owner_id"]) != str(user["id"]):
            raise not_found()
        return application_out(conn, row)


@router.post("/applications")
def create_application(body: ApplicationIn, request: Request):
    app_id = parse_uuid(body.id, status_code=400, message="Invalid application ID.")
    if body.scholarshipType not in SCHOLARSHIP_TYPES:
        raise bad_request("Please choose a valid scholarship.")
    program = check_letters_only(body.program, "Degree program")
    if body.yearLevel not in YEAR_LEVELS:
        raise bad_request("Please select your year level.")
    if body.gwa is None:
        raise bad_request("GWA is required.")
    if body.lowestGrade is None:
        raise bad_request("Lowest grade is required.")
    check_eligibility(body)
    missing = [DOCUMENT_LABELS[key] for key in INITIAL_DOCUMENT_KEYS if key not in body.documents]
    if missing:
        raise bad_request("Missing required document(s): " + ", ".join(missing) + ".")
    with transaction() as conn:
        user = current_user(conn, request, "student")
        term = ensure_current_term(conn)
        if body.termId and body.termId != str(term["id"]):
            raise bad_request("The current term has changed. Please reload the page and try again.")
        scholarship = conn.execute(
            "select status, deadline_at from term_scholarships where term_id = %s and scholarship_key = %s",
            (term["id"], body.scholarshipType),
        ).fetchone()
        if not scholarship or scholarship["status"] != "Open":
            raise bad_request("This scholarship is closed for the current term.")
        if deadline_is_past(scholarship["deadline_at"]):
            raise bad_request(
                f"The deadline for {body.scholarshipType} has passed. Applications are no longer accepted."
            )
        if program_not_offered(program, term["trimester"]) or program_not_offered(
            user["program"], term["trimester"]
        ):
            raise bad_request("Your program has no 3rd trimester. Applications reopen next academic year.")
        stored = {
            key: check_stored_document(user["id"], app_id, key, body.documents[key])
            for key in INITIAL_DOCUMENT_KEYS
        }
        try:
            conn.execute(
                """
                insert into applications
                  (id, code, student_id, term_id, scholarship_type, program, year_level,
                   gwa, lowest_grade, has_failing_grade, has_incomplete_grade, has_dropped_grade)
                values
                  (%s, 'APP-' || lpad(nextval('application_code_seq')::text, 5, '0'), %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s)
                """,
                (
                    app_id,
                    user["id"],
                    term["id"],
                    body.scholarshipType,
                    program,
                    body.yearLevel,
                    body.gwa,
                    body.lowestGrade,
                    body.hasFailingGrade,
                    body.hasIncompleteGrade,
                    body.hasDroppedGrade,
                ),
            )
        except psycopg.errors.UniqueViolation as error:
            if error.diag.constraint_name == "applications_one_per_type_idx":
                raise HTTPException(
                    status_code=409,
                    detail="You already have an application for this scholarship in the current term.",
                )
            raise bad_request("This application was already submitted.")
        for key, (name, path, size, mime) in stored.items():
            conn.execute(
                """
                insert into application_documents (application_id, doc_key, name, path, size_bytes, mime_type)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (app_id, key, name, path, size, mime),
            )
        add_history(conn, app_id, "Submitted", "submitted", user["full_name"])
        row = load_application(conn, app_id)
        notify(
            conn,
            [user["id"]],
            app_id,
            f"Your application {row['code']} for {body.scholarshipType} was submitted successfully.",
        )
        notify(
            conn,
            staff_ids(conn),
            app_id,
            f"New application {row['code']} from {user['full_name']} for {body.scholarshipType}.",
            "admin",
        )
        return application_out(conn, row)


@router.get("/staff/applications")
def active_applications(request: Request):
    with transaction() as conn:
        current_user(conn, request, "staff", "admin")
        return load_applications(conn, "t.is_current and a.deleted_at is null")


@router.get("/staff/applications/history")
def all_applications(request: Request):
    with transaction() as conn:
        current_user(conn, request, "staff", "admin")
        return load_applications(conn, "true")


@router.patch("/staff/applications/{app_id}/status")
def update_status(app_id: str, body: StatusIn, request: Request):
    remarks = " ".join(str(body.remarks or "").split())[:1000]
    discount = parse_discount(body.discountPercent)
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if (row["status"], body.status) not in TRANSITIONS:
            raise bad_request(f"An application that is {row['status']} cannot be changed to {body.status}.")
        if body.status == "Rejected" and not remarks:
            raise bad_request("Please provide a reason or remarks before rejecting this application.")
        decided = body.status in ("Approved", "Rejected")
        conn.execute(
            """
            update applications
            set status = %s, remarks = %s, evaluated_by = %s, discount_percent = %s, updated_at = now()
            where id = %s
            """,
            (
                body.status,
                remarks if decided else None,
                user["full_name"] if decided else None,
                discount if body.status == "Approved" else None,
                row["id"],
            ),
        )
        add_history(conn, row["id"], body.status, "status_changed", user["full_name"], remarks)
        messages = {
            "Under Evaluation": f"Your application {row['code']} is now under evaluation.",
            "Approved": (
                f"Your application {row['code']} was approved. You can now upload your "
                "Letter of Intent and Notarized Scholarship Agreement."
            ),
            "Rejected": f"Your application {row['code']} for {row['scholarship_type']} was not approved.",
        }
        notify(conn, [row["owner_id"]], row["id"], messages[body.status])
        return application_out(conn, load_application(conn, row["id"]))


@router.patch("/staff/applications/{app_id}/discount")
def update_discount(app_id: str, body: DiscountIn, request: Request):
    discount = parse_discount(body.discountPercent)
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if row["status"] != "Approved":
            raise bad_request("The tuition fee discount can only be set on approved applications.")
        conn.execute(
            "update applications set discount_percent = %s, updated_at = now() where id = %s",
            (discount, row["id"]),
        )
        add_history(
            conn,
            row["id"],
            "Approved",
            "discount_changed",
            user["full_name"],
            f"Tuition fee discount set to {discount}%." if discount is not None else "Tuition fee discount cleared.",
        )
        if discount is not None:
            notify(
                conn,
                [row["owner_id"]],
                row["id"],
                f"The tuition fee discount for {row['code']} was set to {discount}%.",
            )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/admin/applications/{app_id}/reopen")
def reopen_application(app_id: str, body: ReopenIn, request: Request):
    reason = " ".join(str(body.reason or "").split())[:1000]
    if not reason:
        raise bad_request("Please provide a reason for reopening this application.")
    with transaction() as conn:
        user = current_user(conn, request, "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if row["status"] not in ("Approved", "Rejected"):
            raise bad_request("Only approved or rejected applications can be reopened.")
        conn.execute(
            """
            update applications
            set status = 'Under Evaluation', remarks = null, evaluated_by = null,
                discount_percent = null, updated_at = now()
            where id = %s
            """,
            (row["id"],),
        )
        add_history(conn, row["id"], "Under Evaluation", "reopened", user["full_name"], reason)
        audit(
            conn,
            user,
            "application_reopened",
            "application",
            row["id"],
            {"code": row["code"], "reason": reason},
        )
        notify(
            conn,
            [row["owner_id"]],
            row["id"],
            f"Your application {row['code']} was reopened and is under evaluation again.",
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.delete("/staff/applications/{app_id}")
def delete_application(app_id: str, request: Request):
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        result = application_out(conn, row)
        conn.execute(
            "update applications set deleted_at = now(), updated_at = now() where id = %s", (row["id"],)
        )
        audit(
            conn,
            user,
            "application_deleted",
            "application",
            row["id"],
            {
                "code": row["code"],
                "scholarshipType": row["scholarship_type"],
                "studentName": row["student_name"],
            },
        )
        result["deleted"] = True
        return result


@router.patch("/admin/applications/{app_id}/duty")
def update_duty(app_id: str, body: DutyIn, request: Request):
    if body.hours < 0 or body.hours > 80:
        raise bad_request("Hours rendered must be from 0 to 80.")
    if body.completed and body.hours != 80:
        raise bad_request("Completed duty must be 80 hours.")
    completed = body.hours == 80
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if row["status"] != "Approved":
            raise bad_request("Duty hours can only be recorded for approved applications.")
        if row["report_received_at"] and not completed:
            raise bad_request("The terminal report was already received, so the duty hours cannot be reduced.")
        conn.execute(
            "update applications set duty_hours = %s, duty_completed = %s, updated_at = now() where id = %s",
            (body.hours, completed, row["id"]),
        )
        add_history(
            conn,
            row["id"],
            "Approved",
            "duty_changed",
            user["full_name"],
            f"Duty rendered updated to {body.hours} of 80 hours.",
        )
        if completed:
            message = f"You completed the 80 duty hours for {row['code']}. You can now submit your terminal report."
        else:
            message = f"Your duty progress for {row['code']} was updated to {body.hours} of 80 hours."
        notify(conn, [row["owner_id"]], row["id"], message)
        if completed:
            notify(
                conn,
                staff_ids(conn, exclude=user["id"]),
                row["id"],
                f"{row['student_name']} completed the 80 duty hours for {row['code']}.",
                "admin",
            )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/applications/{app_id}/terminal-report")
def submit_terminal_report(app_id: str, doc: DocumentIn, request: Request):
    with transaction() as conn:
        user = current_user(conn, request, "student")
        row = locked_application(conn, app_id)
        if str(row["owner_id"]) != str(user["id"]):
            raise not_found()
        ensure_editable(conn, row)
        if row["status"] != "Approved" or row["duty_hours"] != 80:
            raise bad_request("The terminal report is available once your 80 duty hours are complete.")
        if row["report_received_at"]:
            raise bad_request("Your terminal report was already received.")
        name, path, size, mime = check_stored_document(user["id"], row["id"], "terminalReport", doc)
        previous = conn.execute(
            "select path from application_documents where application_id = %s and doc_key = 'terminalReport'",
            (row["id"],),
        ).fetchone()
        conn.execute(
            """
            insert into application_documents (application_id, doc_key, name, path, size_bytes, mime_type)
            values (%s, 'terminalReport', %s, %s, %s, %s)
            on conflict (application_id, doc_key) do update
              set name = excluded.name, path = excluded.path, size_bytes = excluded.size_bytes,
                  mime_type = excluded.mime_type, uploaded_at = now()
            """,
            (row["id"], name, path, size, mime),
        )
        add_history(
            conn,
            row["id"],
            "Approved",
            "report_submitted",
            user["full_name"],
            "Terminal report submitted.",
        )
        notify(conn, [user["id"]], row["id"], f"Your terminal report for {row['code']} was submitted.")
        notify(
            conn,
            staff_ids(conn),
            row["id"],
            f"{user['full_name']} submitted a terminal report for {row['code']}.",
            "admin",
        )
        result = application_out(conn, load_application(conn, row["id"]))
    if previous and previous["path"] != path:
        try:
            storage.remove_objects([previous["path"]])
        except HTTPException:
            pass
    return result


@router.post("/applications/{app_id}/documents/{doc_key}")
def submit_post_approval_document(app_id: str, doc_key: str, doc: DocumentIn, request: Request):
    if doc_key not in POST_APPROVAL_DOCUMENT_KEYS:
        raise bad_request("Unknown document type.")
    with transaction() as conn:
        user = current_user(conn, request, "student")
        row = locked_application(conn, app_id)
        if str(row["owner_id"]) != str(user["id"]):
            raise not_found()
        ensure_editable(conn, row)
        _, attempt_no, _ = ensure_document_upload_allowed(conn, row, doc_key)
        name, path, size, mime = check_stored_document(user["id"], row["id"], doc_key, doc)
        conn.execute(
            """
            insert into application_document_submissions
              (application_id, doc_key, attempt_no, name, path, size_bytes, mime_type, review_status)
            values (%s, %s, %s, %s, %s, %s, %s, 'Pending')
            """,
            (row["id"], doc_key, attempt_no, name, path, size, mime),
        )
        # Sync the latest submission so the existing viewer/download links keep working.
        conn.execute(
            """
            insert into application_documents (application_id, doc_key, name, path, size_bytes, mime_type)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (application_id, doc_key) do update
              set name = excluded.name, path = excluded.path, size_bytes = excluded.size_bytes,
                  mime_type = excluded.mime_type, uploaded_at = now()
            """,
            (row["id"], doc_key, name, path, size, mime),
        )
        label = DOCUMENT_LABELS[doc_key]
        add_history(
            conn,
            row["id"],
            "Approved",
            "document_submitted",
            user["full_name"],
            f"{label} submitted (attempt {attempt_no}).",
        )
        notify(
            conn,
            staff_ids(conn),
            row["id"],
            f"{user['full_name']} submitted {label} (attempt {attempt_no}) for {row['code']}.",
            "admin",
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/staff/applications/{app_id}/documents/{doc_key}/review")
def review_post_approval_document(app_id: str, doc_key: str, body: DocumentReviewIn, request: Request):
    if doc_key not in POST_APPROVAL_DOCUMENT_KEYS:
        raise bad_request("Unknown document type.")
    if body.review not in ("Valid", "Rejected"):
        raise bad_request("Please choose Valid or Rejected.")
    reason = " ".join(str(body.reason or "").split())[:1000]
    if body.review == "Rejected" and not reason:
        raise bad_request("Please provide a reason before rejecting this document.")
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        latest = latest_document_submission(conn, row["id"], doc_key)
        if not latest:
            raise bad_request("No submission has been uploaded for this document yet.")
        if latest["review_status"] != "Pending":
            raise bad_request("The latest submission has already been reviewed.")
        conn.execute(
            """
            update application_document_submissions
            set review_status = %s, review_reason = %s, reviewed_by = %s, reviewed_at = now()
            where id = %s
            """,
            (body.review, reason or None, user["full_name"], latest["id"]),
        )
        label = DOCUMENT_LABELS[doc_key]
        if body.review == "Valid":
            event = "document_accepted"
            remarks = f"{label} accepted (attempt {latest['attempt_no']})."
            message = f"Your {label} for {row['code']} was accepted."
        else:
            event = "document_rejected"
            remarks = f"{label} rejected (attempt {latest['attempt_no']}): {reason}"
            message = (
                f"Your {label} for {row['code']} was rejected (attempt {latest['attempt_no']}): {reason}. "
                "Please correct it and upload a new copy."
            )
            max_attempts = BASE_DOCUMENT_ATTEMPTS + document_allowance(conn, row["id"], doc_key)
            if latest["attempt_no"] >= max_attempts:
                message += (
                    " You have used all attempts; wait for the CSS Office to allow another resubmission."
                )
        add_history(conn, row["id"], "Approved", event, user["full_name"], remarks)
        notify(conn, [row["owner_id"]], row["id"], message)
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/staff/applications/{app_id}/documents/{doc_key}/allow-resubmission")
def allow_document_resubmission(app_id: str, doc_key: str, body: AllowResubmissionIn, request: Request):
    if doc_key not in POST_APPROVAL_DOCUMENT_KEYS:
        raise bad_request("Unknown document type.")
    reason = " ".join(str(body.reason or "").split())[:1000]
    if not reason:
        raise bad_request("Please provide a reason for allowing another resubmission.")
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        latest = latest_document_submission(conn, row["id"], doc_key)
        if not latest:
            raise bad_request("No submission has been uploaded for this document yet.")
        if latest["review_status"] != "Rejected":
            raise bad_request("Resubmission can only be allowed after the latest submission is rejected.")
        conn.execute(
            """
            insert into application_document_allowances (application_id, doc_key, extra_attempts, updated_at)
            values (%s, %s, 1, now())
            on conflict (application_id, doc_key) do update
              set extra_attempts = application_document_allowances.extra_attempts + 1,
                  updated_at = now()
            """,
            (row["id"], doc_key),
        )
        max_attempts = BASE_DOCUMENT_ATTEMPTS + document_allowance(conn, row["id"], doc_key)
        label = DOCUMENT_LABELS[doc_key]
        add_history(
            conn,
            row["id"],
            "Approved",
            "document_resubmission_allowed",
            user["full_name"],
            f"{label} resubmission allowed (now {max_attempts} attempts): {reason}",
        )
        notify(
            conn,
            [row["owner_id"]],
            row["id"],
            f"The CSS Office allowed another resubmission of your {label} for {row['code']} "
            f"(attempt {latest['attempt_no'] + 1} of {max_attempts}). Reason: {reason}",
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/staff/applications/{app_id}/terminal-report/receive")
def receive_terminal_report(app_id: str, request: Request):
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        has_report = conn.execute(
            "select 1 from application_documents where application_id = %s and doc_key = 'terminalReport'",
            (row["id"],),
        ).fetchone()
        if not has_report:
            raise bad_request("No terminal report has been submitted for this application.")
        if row["report_received_at"]:
            raise bad_request("This terminal report was already marked as received.")
        conn.execute(
            "update applications set report_received_at = now(), updated_at = now() where id = %s",
            (row["id"],),
        )
        add_history(
            conn,
            row["id"],
            "Approved",
            "report_received",
            user["full_name"],
            "Terminal report marked as received.",
        )
        notify(
            conn,
            [row["owner_id"]],
            row["id"],
            f"Your terminal report for {row['code']} was marked as received.",
        )
        return application_out(conn, load_application(conn, row["id"]))
