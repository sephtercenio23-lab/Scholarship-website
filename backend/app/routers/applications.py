import csv
import io
import logging
import re
from datetime import datetime

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response

from .. import storage
from ..catalog import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    APPROVED_STATUSES,
    APPROVAL_STAGE_EVENTS,
    APPROVAL_STAGE_LABELS,
    APPROVAL_STAGES,
    BASE_DOCUMENT_ATTEMPTS,
    CHANGED_AFTER_FINANCE,
    DISCOUNT_EDITABLE_STATUSES,
    DOCUMENT_LABELS,
    FINANCE_SENT_STATUSES,
    FINANCE_STATUS,
    INITIAL_DOCUMENT_KEYS,
    MAX_FILE_BYTES,
    NON_STUDENT_ROLES,
    PAST_DISCOUNT_CHOICES,
    PAST_DISCOUNT_NOT_SCHOLAR,
    POST_APPROVAL_DOCUMENT_KEYS,
    SCHOLARSHIP_TYPES,
    STAGE_STATUS,
    STATUSES,
    YEAR_LEVELS,
    program_not_offered,
    status_label,
    term_label,
)
from ..common import (
    MANILA_TZ,
    add_history,
    application_out,
    audit,
    can_act_on_stage,
    deadline_is_past,
    document_allowance,
    ensure_current_term,
    ensure_document_upload_allowed,
    export_approvals,
    latest_document_submission,
    load_application,
    load_applications,
    next_approval_stage,
    normalize_academic_year,
    notify,
    parse_uuid,
    role_ids,
    staff_ids,
    student_status,
    term_state,
)
from ..config import get_settings
from ..db import transaction
from ..deps import current_user
from ..mailer import mail_configured, queue_email
from ..schemas import (
    AllowResubmissionIn,
    AppealIn,
    AppealResponseIn,
    ApplicationIn,
    DiscountIn,
    DocumentIn,
    DocumentReviewIn,
    ReopenIn,
    StatusIn,
)
from ..security import bad_request, check_letters_only
from ..signatures import signature_for
from ..spreadsheet import build_xlsx

router = APIRouter()
logger = logging.getLogger("sams.finance")

PAST_TERM_MESSAGE = "This application belongs to a past term and is read-only."
APPROVALS_COMPLETE_MESSAGE = (
    f"The {APPROVAL_STAGE_LABELS['president']} and the {APPROVAL_STAGE_LABELS['executive_president']} "
    "have completed their approvals."
)
# The API keeps sending "Approved" for "approve this level"; the stored status advances
# one level at a time: Under Evaluation -> Endorsed by Staff -> Approved by President
# -> Approved by Executive President (the third approval also emails the scholar to
# Finance and moves the application to "Sent to Finance").
TRANSITIONS = {
    ("Submitted", "Under Evaluation"),
    ("Under Evaluation", "Approved"),
    ("Under Evaluation", "Rejected"),
    ("Endorsed by Staff", "Approved"),
    ("Endorsed by Staff", "Rejected"),
    ("Approved by President", "Approved"),
    ("Approved by President", "Rejected"),
}
# SQL fragment matching every fully approved status (legacy "Approved" rows included).
APPROVED_STATUS_SQL = "a.status in (" + ", ".join(f"'{status}'" for status in APPROVED_STATUSES) + ")"

EXPORT_HEADERS = (
    "Application code",
    "Student name",
    "Student ID",
    "Email",
    "Program",
    "Year level",
    "Scholarship type",
    "Term",
    "Status",
    "Date submitted",
    "Evaluated by",
    "Remarks",
    "Discount %",
    "Letter of Intent review status",
    "Notarized Agreement review status",
)

CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# Browsers and storage providers use several harmless labels for real images.
BENIGN_MIME_TYPES = ALLOWED_MIME_TYPES | {
    "application/octet-stream",
    "image/jpg",
    "image/jpeg",
    "image/pjpeg",
    "image/jfif",
    "image/webp",
    "image/avif",
    "image/heic",
    "image/heif",
    "image/gif",
    "image/bmp",
    "image/tiff",
}


def csv_cell(value):
    text = "" if value is None else str(value)
    if text[:1] in CSV_INJECTION_PREFIXES:
        return "'" + text
    return text


def file_slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def document_review_status(app, doc_key):
    document = (app.get("postApprovalDocuments") or {}).get(doc_key)
    return document["reviewStatus"] if document else ""


def export_row_values(app):
    submitted = ""
    if app["dateSubmitted"]:
        submitted = (
            datetime.fromisoformat(app["dateSubmitted"])
            .astimezone(MANILA_TZ)
            .strftime("%Y-%m-%d")
        )
    return [
        app["code"],
        app["studentName"],
        app["studentId"],
        app["universityEmail"],
        app["program"],
        app["yearLevel"],
        app["scholarshipType"],
        app["term"],
        status_label(app["status"]),
        submitted,
        app["evaluatedBy"],
        app["remarks"],
        app["discountPercent"],
        document_review_status(app, "letterOfIntent"),
        document_review_status(app, "notarizedAgreement"),
    ]


CERTIFICATION_TITLE = "APPROVED BY:"
# Signature images sit above the approver's name. They are scaled to this width and
# keep the handwriting's aspect ratio (the images are pre-cropped to their ink).
SIGNATURE_WIDTH_PX = 96
CSV_SIGNATURE_MARKER = "[SIGNATURE]"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def append_certification(rows, applications, signature_text=None):
    """Append the approver certification block to the export rows.

    The block lists only approvers who actually approved: signature first (an image in
    Excel, a marker in CSV), then the full name in capital letters, then the role, and
    the CSS Office for the Authorized Staff. Returns the signature images anchored on
    the appended rows (0-based row/column) and the row heights they need.
    """
    approvers = export_approvals(applications)
    images = []
    row_heights = {}
    if not approvers:
        return images, row_heights
    rows.append([""])
    rows.append([CERTIFICATION_TITLE])
    for approver in approvers:
        rows.append([signature_text or ""])
        # rows[i] is worksheet row i + 1 (row 0 holds the header), so the row just
        # appended is the worksheet row index equal to len(rows).
        anchor_row = len(rows)
        signature = signature_for(approver["stage"])
        if signature and signature_text is None:
            native_width = signature.get("width") or SIGNATURE_WIDTH_PX
            native_height = signature.get("height") or native_width
            height_px = max(1, round(SIGNATURE_WIDTH_PX * native_height / native_width))
            images.append(
                {
                    "data": signature["data"],
                    "extension": "png" if signature["mime"] == "image/png" else "jpeg",
                    "row": anchor_row,
                    "col": 0,
                    "width": SIGNATURE_WIDTH_PX,
                    "height": height_px,
                }
            )
            # Excel row heights are points (72 pt per inch, 96 px per inch) plus a
            # little headroom so the signature is never clipped.
            row_heights[anchor_row] = round(height_px * 0.75) + 6
        rows.append([approver["name"]])
        rows.append([approver["position"]])
        if approver.get("office"):
            rows.append([approver["office"]])
        rows.append([""])
    if signature_text:
        rows.append(["Signatures are printed as images in the Excel export."])
    return images, row_heights


def export_certification_rows(applications):
    """Certification rows for the CSV export (images cannot be embedded in CSV)."""
    rows = []
    append_certification(rows, applications, signature_text=CSV_SIGNATURE_MARKER)
    return rows


def build_application_workbook(applications):
    """Excel workbook for approved scholars, including the signature certification."""
    rows = [export_row_values(app) for app in applications]
    images, row_heights = append_certification(rows, applications)
    return build_xlsx(list(EXPORT_HEADERS), rows, images=images, row_heights=row_heights)


def export_file_name(term_row, academic_year, extension):
    if term_row:
        term_part = file_slug(term_label(term_row["trimester"], term_row["academic_year"]))
    elif academic_year:
        term_part = file_slug(f"ay-{academic_year}")
    else:
        term_part = "all-terms"
    date_part = datetime.now(MANILA_TZ).strftime("%Y-%m-%d")
    return f"applications-{term_part}-{date_part}.{extension}"


def prepare_application_export(
    request,
    term_id,
    academic_year,
    scholarship_type,
    status_filter,
    search_text,
    date_filter,
    program_filter,
    evaluator_filter,
    file_format,
):
    term_id = " ".join(term_id.split())
    academic_year = " ".join(academic_year.split())
    scholarship_type = " ".join(scholarship_type.split())
    status_filter = " ".join(status_filter.split())
    search_text = " ".join(search_text.split())
    date_filter = " ".join(date_filter.split())
    program_filter = " ".join(program_filter.split())
    evaluator_filter = " ".join(evaluator_filter.split())
    if term_id:
        parse_uuid(term_id, status_code=400, message="Invalid term filter.")
    if academic_year:
        academic_year = normalize_academic_year(academic_year)
    if scholarship_type and scholarship_type not in SCHOLARSHIP_TYPES:
        raise bad_request("Unknown scholarship type filter.")
    if status_filter and status_filter not in STATUSES:
        raise bad_request("Unknown status filter.")
    if date_filter:
        try:
            datetime.strptime(date_filter, "%Y-%m-%d")
        except ValueError:
            raise bad_request("Date filter must be in YYYY-MM-DD format.")
    where = ["a.deleted_at is null"]
    params = []
    if term_id:
        where.append("a.term_id = %s")
        params.append(term_id)
    elif academic_year:
        where.append("t.academic_year = %s")
        params.append(academic_year)
    if scholarship_type:
        where.append("a.scholarship_type = %s")
        params.append(scholarship_type)
    # "Approved" in the export means every fully approved status, including legacy rows.
    if status_filter == "Approved":
        where.append(APPROVED_STATUS_SQL)
    elif status_filter:
        where.append("a.status = %s")
        params.append(status_filter)
    if program_filter:
        where.append("a.program = %s")
        params.append(program_filter)
    if date_filter:
        where.append("(a.created_at at time zone 'Asia/Manila')::date = %s::date")
        params.append(date_filter)
    if search_text:
        where.append(
            "(a.code ilike %s or u.full_name ilike %s or u.student_id ilike %s "
            "or u.email ilike %s or a.program ilike %s)"
        )
        like = f"%{search_text}%"
        params.extend([like, like, like, like, like])
    with transaction() as conn:
        user = current_user(conn, request, *NON_STUDENT_ROLES)
        applications = load_applications(conn, " and ".join(where), params)
        # Legacy approvals remain visible, but only complete three-stage decisions are exportable.
        applications = [
            app
            for app in applications
            if app.get("status") in APPROVED_STATUSES and next_approval_stage(app.get("approvals")) is None
        ]
        term_row = None
        if term_id:
            term_row = conn.execute(
                "select * from academic_terms where id = %s", (term_id,)
            ).fetchone()
        if term_row and term_row["trimester"] == "3rd Trimester":
            applications = [
                app for app in applications if not program_not_offered(app["program"], "3rd Trimester")
            ]
        if evaluator_filter:
            if evaluator_filter in NON_STUDENT_ROLES:
                applications = [
                    app for app in applications if evaluator_filter in app.get("evaluatorRoles", [])
                ]
            else:
                applications = [app for app in applications if evaluator_filter in app["evaluators"]]
        # Exporting is a read-only record of the approved scholars; the finance send
        # (done automatically after the third approval) is what moves the status.
        audit(
            conn,
            user,
            "applications_exported",
            "application",
            None,
            {
                "count": len(applications),
                "format": file_format,
                "codes": [app["code"] for app in applications],
                "termId": term_id,
                "academicYear": academic_year,
                "scholarshipType": scholarship_type,
                "status": status_filter,
                "search": search_text,
            },
        )
    return applications, term_row, academic_year


def finance_file_name(applications, correction=False):
    term_part = file_slug(applications[0]["term"]) if applications else "all-terms"
    date_part = datetime.now(MANILA_TZ).strftime("%Y-%m-%d")
    kind = "finance-corrections" if correction else "approved-scholars"
    return f"{kind}-{term_part}-{date_part}.xlsx"


def send_scholars_to_finance(conn, user, applications, correction=False):
    """Email the approved scholars (or a correction list) to Finance as an Excel file.

    The workbook carries the same signature certification as a downloaded export, and
    only the approvers whose approval is on record are printed. Every send is audited.
    """
    if not applications:
        return None
    to_address = get_settings().finance_email
    filename = finance_file_name(applications, correction)
    workbook = build_application_workbook(applications)
    approvers = export_approvals(applications)
    codes = ", ".join(app["code"] for app in applications)
    term = applications[0].get("term") or "the current term"
    approved_by = ", ".join(
        f"{approver['name']} ({approver['position']})" for approver in approvers
    ) or "No completed approval on record"
    kind = "correction list" if correction else "approved scholar list"
    subject = (
        f"Correction list sent to Finance - {term}"
        if correction
        else f"Approved scholars sent to Finance - {term}"
    )
    body = "\n".join(
        [
            "Hello Finance,",
            "",
            (
                f"Please find attached the {kind} for {term} in Excel format."
                if correction
                else f"{APPROVALS_COMPLETE_MESSAGE} "
                f"The {kind} for {term} is attached in Excel format."
            ),
            "",
            f"Applications: {codes}",
            f"Approved by: {approved_by}",
            "",
            f"Attachment: {filename}",
        ]
    )
    attachments = [{"filename": filename, "content": workbook, "mime": XLSX_MIME}]
    queued = mail_configured()
    if not queued:
        # The status still moves to Sent to Finance so the record is not stuck; the
        # audit entry records that no email left the server.
        logger.warning(
            "Finance email to %s was not queued: SMTP is not configured.", to_address
        )
    queue_email(None, None, to_address, subject, body, attachments=attachments)
    audit(
        conn,
        user,
        "finance_correction_sent" if correction else "scholars_sent_to_finance",
        "application",
        applications[0]["id"] if len(applications) == 1 else None,
        {
            "codes": [app["code"] for app in applications],
            "recipient": to_address,
            "attachment": filename,
            "format": "xlsx",
            "approvers": [approver["name"] for approver in approvers],
            "emailQueued": queued,
        },
    )
    return {"to": to_address, "filename": filename, "queued": queued, "codes": codes}


def flag_changed_after_finance(conn, row, user, reason):
    """Flag an application that Finance already received when staff edit it.

    The application returns to Under Evaluation and must pass the three approvals
    again; after the third approval the correction list is emailed to Finance and the
    flag clears. Returns True when the application was flagged.
    """
    already_sent = row.get("finance_sent_at") is not None or row["status"] in FINANCE_SENT_STATUSES
    if not already_sent:
        return False
    conn.execute(
        """
        update applications
        set status = 'Under Evaluation', changed_after_finance = true,
            remarks = null, evaluated_by = null, updated_at = now()
        where id = %s
        """,
        (row["id"],),
    )
    add_history(
        conn,
        row["id"],
        "Under Evaluation",
        "finance_change_flagged",
        user["full_name"],
        reason,
    )
    audit(
        conn,
        user,
        "application_changed_after_finance",
        "application",
        row["id"],
        {"code": row["code"], "reason": reason, "flag": CHANGED_AFTER_FINANCE},
    )
    message = (
        f"Your application {row['code']} was updated after it was sent to Finance, so it is "
        f"flagged \"{CHANGED_AFTER_FINANCE}\" and must pass the three approvals again. "
        f"Reason: {reason}"
    )
    notify(conn, [row["owner_id"]], row["id"], message)
    queue_email(
        row["owner_id"],
        row["id"],
        row["student_email"],
        f"Application {row['code']} is being reviewed again",
        f"Hello {row['student_name']},\n\n"
        f"Your application {row['code']} was updated after it was sent to Finance. It is now "
        f"flagged \"{CHANGED_AFTER_FINANCE}\" and must pass the three approvals again.\n\n"
        f"Reason: {reason}",
    )
    return True


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


def parse_past_discount(value):
    # Accepts 25/50/75/100 or "none" (not a scholar). No value means the student skipped a required choice.
    text = " ".join(str(value or "").split())
    if not text:
        raise bad_request(
            "Please select the tuition fee discount you had in the past term or academic year."
        )
    if text == PAST_DISCOUNT_NOT_SCHOLAR:
        return None
    if text.isdigit() and int(text) in PAST_DISCOUNT_CHOICES:
        return int(text)
    raise bad_request("Please choose 25%, 50%, 75%, 100%, or not a scholar in the past term or academic year.")


def check_stored_document(user_id, app_id, key, doc):
    label = DOCUMENT_LABELS[key]
    parts = storage.parse_path(doc.path)
    if (
        parts["user"].lower() != str(user_id).lower()
        or parts["app"].lower() != str(app_id).lower()
        or parts["key"] != key
    ):
        raise bad_request(f"The {label} file path is not valid.")
    name = " ".join(str(doc.name or "").split())[:255]
    if not name or not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise bad_request(f"The {label} must be a PDF, JPG or PNG file.")
    info = storage.object_info(doc.path)
    if info is None:
        raise bad_request(
            f"The {label} file was not found in secure storage. Please upload it again."
        )
    size = info.get("size") if info.get("size") is not None else doc.sizeBytes
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    if size is not None and (size <= 0 or size > MAX_FILE_BYTES):
        raise bad_request(f"The {label} must be 5 MB or smaller.")

    # Derive the document type from the validated extension. Storage MIME
    # metadata can be wrong when a browser saved an image under a .jpg name.
    expected = storage.EXTENSION_KINDS.get(storage.file_extension(name), "")
    canonical_mime = storage.file_mime_type(expected)
    if not canonical_mime:
        raise bad_request(f"The {label} must be a PDF, JPG or PNG file.")
    declared_mime = str(info.get("mimetype") or doc.mimeType or "").split(";", 1)[0].strip().lower()
    if declared_mime and declared_mime not in BENIGN_MIME_TYPES:
        raise bad_request(f"The {label} must be a PDF, JPG or PNG file.")

    head = storage.object_head_bytes(doc.path)
    if head is None:
        raise bad_request(
            f"The {label} file was not found in secure storage. Please upload it again."
        )
    content_error = bad_request(
        f"The {label} content does not match its file type. "
        "Please upload the original PDF, JPG or PNG file."
    )
    if storage.looks_dangerous(head):
        raise content_error
    kind = storage.detect_file_kind(head)
    if expected == "pdf" and kind != "pdf":
        raise content_error
    if expected in storage.IMAGE_KINDS and kind == "pdf":
        raise content_error
    # An unrecognised image header can be WebP, AVIF or HEIC saved with a
    # .jpg/.png extension. Accept it with the extension's canonical MIME type;
    # the browser decodes the actual bytes when staff preview the image.
    if kind in storage.FILE_SIGNATURES:
        canonical_mime = storage.file_mime_type(kind)
    return name, doc.path, size, canonical_mime


@router.get("/applications")
def my_applications(request: Request, active: bool = False):
    with transaction() as conn:
        user = current_user(conn, request, "student")
        where = "a.student_id = %s and a.deleted_at is null"
        params = [user["id"]]
        if active:
            where += " and t.is_current"
        apps = load_applications(conn, where, params)
        # Students only ever see Under Evaluation until all three approvals, then Approved.
        for app in apps:
            app["status"] = student_status(app["status"])
        return apps


@router.get("/applications/{app_id}")
def get_application(app_id: str, request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        row = load_application(conn, parse_uuid(app_id, message="Application not found."))
        if not row or row["deleted_at"] is not None:
            raise not_found()
        if user["role"] == "student" and str(row["owner_id"]) != str(user["id"]):
            raise not_found()
        app = application_out(conn, row)
        if user["role"] == "student":
            app["status"] = student_status(app["status"])
        return app


@router.post("/applications")
def create_application(body: ApplicationIn, request: Request):
    app_id = parse_uuid(body.id, status_code=400, message="Invalid application ID.")
    if body.scholarshipType not in SCHOLARSHIP_TYPES:
        raise bad_request("Please choose a valid scholarship.")
    program = check_letters_only(body.program, "Degree program")
    if body.yearLevel not in YEAR_LEVELS:
        raise bad_request("Please select your year level.")
    # The tuition discount for the past term is required before grades can be submitted.
    past_discount = parse_past_discount(body.pastDiscount)
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
                  (id, code, student_id, term_id, scholarship_type, program, year_level, past_discount)
                values
                  (%s, 'APP-' || lpad(nextval('application_code_seq')::text, 5, '0'), %s, %s, %s, %s, %s, %s)
                """,
                (
                    app_id,
                    user["id"],
                    term["id"],
                    body.scholarshipType,
                    program,
                    body.yearLevel,
                    past_discount,
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
        queue_email(
            user["id"],
            app_id,
            user["email"],
            f"Application {row['code']} submitted",
            f"Hello {user['full_name']},\n\n"
            f"Your application {row['code']} for {body.scholarshipType} was submitted successfully. "
            "The CSS Office will review it and you will be notified when the status changes.",
        )
        return application_out(conn, row)


@router.get("/staff/applications")
def staff_applications(request: Request, active: bool = True):
    with transaction() as conn:
        current_user(conn, request, *NON_STUDENT_ROLES)
        where = "a.deleted_at is null"
        if active:
            where += " and t.is_current"
        return load_applications(conn, where)


@router.get("/staff/evaluators")
def staff_evaluators(request: Request):
    with transaction() as conn:
        current_user(conn, request, *NON_STUDENT_ROLES)
        rows = conn.execute(
            """
            select full_name
            from users
            where role in ('staff', 'admin', 'president', 'executive_president', 'super_admin') and deleted_at is null
            order by full_name
            """
        ).fetchall()
        return [row["full_name"] for row in rows if row["full_name"]]


@router.get("/staff/applications/export")
def export_applications(
    request: Request,
    termId: str = "",
    academicYear: str = "",
    scholarshipType: str = "",
    status: str = "",
    search: str = "",
    date: str = "",
    program: str = "",
    evaluator: str = "",
):
    applications, term_row, resolved_year = prepare_application_export(
        request,
        termId,
        academicYear,
        scholarshipType,
        status,
        search,
        date,
        program,
        evaluator,
        "csv",
    )
    if not applications:
        return Response(status_code=204)
    filename = export_file_name(term_row, resolved_year, "csv")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    for app in applications:
        writer.writerow([csv_cell(value) for value in export_row_values(app)])
    for row in export_certification_rows(applications):
        writer.writerow([csv_cell(value) for value in row])
    data = b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/staff/applications/excel")
def export_applications_excel(
    request: Request,
    termId: str = "",
    academicYear: str = "",
    scholarshipType: str = "",
    status: str = "",
    search: str = "",
    date: str = "",
    program: str = "",
    evaluator: str = "",
):
    applications, term_row, resolved_year = prepare_application_export(
        request,
        termId,
        academicYear,
        scholarshipType,
        status,
        search,
        date,
        program,
        evaluator,
        "xlsx",
    )
    if not applications:
        return Response(status_code=204)
    filename = export_file_name(term_row, resolved_year, "xlsx")
    data = build_application_workbook(applications)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/staff/applications/{app_id}/status")
def update_status(app_id: str, body: StatusIn, request: Request):
    remarks = " ".join(str(body.remarks or "").split())[:1000]
    discount = parse_discount(body.discountPercent)
    with transaction() as conn:
        # Any of the three reviewers may start evaluation. The deadline governs submissions only.
        user = current_user(conn, request, *APPROVAL_STAGES)
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if (row["status"], body.status) not in TRANSITIONS:
            raise bad_request(
                f"An application that is {status_label(row['status'])} cannot be changed to {status_label(body.status)}."
            )
        if body.status == "Rejected" and not remarks:
            raise bad_request("Please provide a reason or remarks before rejecting this application.")
        # Starting a review is not an endorsement. Decisions still belong to the
        # next approver in order, regardless of who started the evaluation.
        stage = None
        decided = body.status in ("Approved", "Rejected")
        if decided:
            approvals = application_out(conn, row).get("approvals") or {}
            stage = next_approval_stage(approvals)
            if stage is None:
                raise bad_request("This application has already completed all approval levels.")
            if not can_act_on_stage(user["role"], stage):
                label = APPROVAL_STAGE_LABELS[stage]
                action = "approve" if body.status == "Approved" else "reject"
                raise bad_request(f"Only the {label} can {action} at this stage. Waiting for {label} approval.")
        is_final = body.status == "Approved" and stage == "executive_president"
        # Preserve an already-encoded discount through intermediate approvals and
        # correction re-approvals; only the final approval can encode a new one.
        if body.status == "Approved":
            final_discount = (
                discount if is_final and discount is not None else row.get("discount_percent")
            )
        else:
            final_discount = None
        new_status = STAGE_STATUS[stage] if body.status == "Approved" else body.status
        event_type = APPROVAL_STAGE_EVENTS[stage] if body.status == "Approved" and stage else "status_changed"
        conn.execute(
            """
            update applications
            set status = %s, remarks = %s, evaluated_by = %s, discount_percent = %s, updated_at = now()
            where id = %s
            """,
            (
                new_status,
                remarks if decided else None,
                user["full_name"] if decided else None,
                final_discount,
                row["id"],
            ),
        )
        add_history(conn, row["id"], new_status, event_type, user["full_name"], remarks)
        if decided:
            # Every approval and rejection is recorded in the append-only audit log.
            audit(
                conn,
                user,
                "application_rejected" if body.status == "Rejected" else "application_approved",
                "application",
                row["id"],
                {
                    "code": row["code"],
                    "stage": stage,
                    "position": APPROVAL_STAGE_LABELS.get(stage, "") if stage else "",
                    "status": new_status,
                    "remarks": remarks,
                },
            )
        if body.status == "Under Evaluation":
            notify(conn, [row["owner_id"]], row["id"], f"Your application {row['code']} is now under evaluation.")
            queue_email(
                row["owner_id"],
                row["id"],
                row["student_email"],
                f"Application {row['code']} is now under evaluation",
                f"Hello {row['student_name']},\n\n"
                f"Your application {row['code']} for {row['scholarship_type']} is now under evaluation. "
                "The CSS Office will notify you once a decision has been made.",
            )
        elif body.status == "Rejected":
            label = APPROVAL_STAGE_LABELS[stage]
            notify(
                conn,
                [row["owner_id"]],
                row["id"],
                f"Your application {row['code']} for {row['scholarship_type']} was not approved by the {label}. Remarks: {remarks}",
            )
            notify(
                conn,
                staff_ids(conn, exclude=user["id"]),
                row["id"],
                f"Application {row['code']} was rejected by the {label}. Remarks: {remarks}",
                "admin",
            )
            queue_email(
                row["owner_id"],
                row["id"],
                row["student_email"],
                f"Application {row['code']} was not approved",
                f"Hello {row['student_name']},\n\n"
                f"Your application {row['code']} for {row['scholarship_type']} was not approved by the {label}.\n\n"
                f"Remarks: {remarks}",
            )
        elif is_final:
            # Third approval complete: email the scholar (or the correction list) to
            # Finance, then move the application to Sent to Finance and clear the flag.
            correction = bool(row.get("changed_after_finance"))
            approved_application = application_out(conn, load_application(conn, row["id"]))
            finance = send_scholars_to_finance(
                conn, user, [approved_application], correction=correction
            )
            conn.execute(
                """
                update applications
                set status = %s, finance_sent_at = now(), changed_after_finance = false,
                    updated_at = now()
                where id = %s
                """,
                (FINANCE_STATUS, row["id"]),
            )
            add_history(
                conn,
                row["id"],
                FINANCE_STATUS,
                "finance_sent",
                user["full_name"],
                "Correction list sent to Finance." if correction else "Approved scholar sent to Finance.",
            )
            notify(
                conn,
                [row["owner_id"]],
                row["id"],
                f"Your application {row['code']} was approved by {APPROVAL_STAGE_LABELS['staff']}, "
                f"the {APPROVAL_STAGE_LABELS['president']}, and the {APPROVAL_STAGE_LABELS['executive_president']}. "
                "You are now an approved scholar and can upload your Letter of Intent and Notarized Scholarship Agreement.",
            )
            notified_discount = (
                discount if discount is not None else (None if correction else final_discount)
            )
            if notified_discount is not None:
                notify(
                    conn,
                    [row["owner_id"]],
                    row["id"],
                    f"A {notified_discount}% tuition fee discount was encoded for application {row['code']}.",
                )
            if finance:
                # The same message tells the Authorized Staff that all approvals are done
                # and where the Excel file was sent.
                notify(
                    conn,
                    role_ids(conn, ["staff"]),
                    row["id"],
                    f"{APPROVALS_COMPLETE_MESSAGE} "
                    + (
                        "The correction list was"
                        if correction
                        else "The approved scholars were"
                    )
                    + f" automatically sent to Finance at {finance['to']} in an Excel format.",
                    "admin",
                )
            queue_email(
                row["owner_id"],
                row["id"],
                row["student_email"],
                f"Application {row['code']} approved",
                f"Hello {row['student_name']},\n\n"
                f"Your application {row['code']} for {row['scholarship_type']} was approved. "
                "You are now an approved scholar. "
                "You can now upload your Letter of Intent and Notarized Scholarship Agreement "
                "through the portal.",
            )
        else:
            label = APPROVAL_STAGE_LABELS[stage]
            nxt = next_approval_stage({**approvals, stage: {"by": user["full_name"]}})
            next_label = APPROVAL_STAGE_LABELS[nxt] if nxt else ""
            notify(
                conn,
                role_ids(conn, ["president", "executive_president", "admin", "super_admin"], exclude=user["id"]),
                row["id"],
                f"Application {row['code']} was approved by the {label} and is now waiting for {next_label} approval.",
                "admin",
            )
        return application_out(conn, load_application(conn, row["id"]))


@router.patch("/staff/applications/{app_id}/discount")
def update_discount(app_id: str, body: DiscountIn, request: Request):
    discount = parse_discount(body.discountPercent)
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin", "super_admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if row["status"] not in DISCOUNT_EDITABLE_STATUSES:
            raise bad_request(
                "The tuition fee discount can only be set after the application is endorsed by staff."
            )
        conn.execute(
            "update applications set discount_percent = %s, updated_at = now() where id = %s",
            (discount, row["id"]),
        )
        change_note = (
            f"Tuition fee discount set to {discount}%."
            if discount is not None
            else "Tuition fee discount cleared."
        )
        add_history(
            conn,
            row["id"],
            row["status"],
            "discount_changed",
            user["full_name"],
            change_note,
        )
        # Editing a record Finance already received forces the three approvals again.
        if row["status"] in APPROVED_STATUSES:
            flag_changed_after_finance(conn, row, user, change_note)
            if discount is not None:
                notify(
                    conn,
                    [row["owner_id"]],
                    row["id"],
                    f"The tuition fee discount for {row['code']} was set to {discount}%.",
                )
                queue_email(
                    row["owner_id"],
                    row["id"],
                    row["student_email"],
                    f"Tuition discount set for application {row['code']}",
                    f"Hello {row['student_name']},\n\n"
                    f"The tuition fee discount for your application {row['code']} was set to {discount}%.",
                )
            else:
                notify(
                    conn,
                    [row["owner_id"]],
                    row["id"],
                    f"The tuition fee discount for {row['code']} was cleared.",
                )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/admin/applications/{app_id}/reopen")
def reopen_application(app_id: str, body: ReopenIn, request: Request):
    reason = " ".join(str(body.reason or "").split())[:1000]
    if not reason:
        raise bad_request("Please provide a reason for reopening this application.")
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin", "super_admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        if row["status"] not in APPROVED_STATUSES and row["status"] != "Rejected":
            raise bad_request("Only approved or rejected applications can be reopened.")
        if row.get("finance_sent_at") is not None or row["status"] in FINANCE_SENT_STATUSES:
            # Already with Finance: flag it and start the three approvals again.
            flag_changed_after_finance(conn, row, user, reason)
            audit(
                conn,
                user,
                "application_reopened",
                "application",
                row["id"],
                {"code": row["code"], "reason": reason, "flag": CHANGED_AFTER_FINANCE},
            )
            return application_out(conn, load_application(conn, row["id"]))
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
            f"Your application {row['code']} was reopened and is under evaluation again. Reason: {reason}",
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/applications/{app_id}/appeals")
def submit_appeal(app_id: str, body: AppealIn, request: Request):
    reason = " ".join(str(body.reason or "").split())[:1000]
    if not reason:
        raise bad_request("Please provide a reason for your appeal.")
    with transaction() as conn:
        user = current_user(conn, request, "student")
        row = locked_application(conn, app_id)
        if str(row["owner_id"]) != str(user["id"]):
            raise not_found()
        ensure_editable(conn, row)
        if row["status"] != "Rejected":
            raise bad_request("You can only appeal a rejected application.")
        existing = conn.execute(
            "select 1 from application_appeals where application_id = %s", (row["id"],)
        ).fetchone()
        if existing:
            raise bad_request("You have already submitted an appeal for this application.")
        conn.execute(
            "insert into application_appeals (application_id, reason) values (%s, %s)",
            (row["id"], reason),
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/staff/applications/{app_id}/appeals/respond")
def respond_appeal(app_id: str, body: AppealResponseIn, request: Request):
    if body.decision not in ("Accepted", "Declined"):
        raise bad_request("Please choose Accept or Decline.")
    response_text = " ".join(str(body.response or "").split())[:1000]
    if body.decision == "Declined" and not response_text:
        raise bad_request("Please provide a response before declining this appeal.")
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin", "super_admin")
        row = locked_application(conn, app_id)
        ensure_editable(conn, row)
        appeal = conn.execute(
            "select * from application_appeals where application_id = %s for update",
            (row["id"],),
        ).fetchone()
        if not appeal:
            raise bad_request("This application has no appeal.")
        if appeal["status"] != "Pending":
            raise bad_request("This appeal has already been decided.")
        conn.execute(
            """
            update application_appeals
            set status = %s, response = %s, responded_by = %s, responded_at = now()
            where id = %s
            """,
            (body.decision, response_text or None, user["full_name"], appeal["id"]),
        )
        if body.decision == "Accepted":
            conn.execute(
                """
                update applications
                set status = 'Under Evaluation', remarks = null, evaluated_by = null,
                    discount_percent = null, updated_at = now()
                where id = %s
                """,
                (row["id"],),
            )
            add_history(
                conn,
                row["id"],
                "Under Evaluation",
                "appeal_accepted",
                user["full_name"],
                appeal["reason"],
            )
            notify(
                conn,
                [row["owner_id"]],
                row["id"],
                f"Your appeal for {row['code']} was accepted and your application is under evaluation again.",
            )
            queue_email(
                row["owner_id"],
                row["id"],
                row["student_email"],
                f"Appeal accepted for application {row['code']}",
                f"Hello {row['student_name']},\n\n"
                f"Your appeal for application {row['code']} ({row['scholarship_type']}) was accepted. "
                "Your application has been moved back to Under Evaluation and the CSS Office will review it again.",
            )
            audit(
                conn,
                user,
                "appeal_accepted",
                "application",
                row["id"],
                {"code": row["code"], "reason": appeal["reason"]},
            )
        else:
            notify(
                conn,
                [row["owner_id"]],
                row["id"],
                f"Your appeal for {row['code']} was declined. {response_text}",
            )
            queue_email(
                row["owner_id"],
                row["id"],
                row["student_email"],
                f"Appeal declined for application {row['code']}",
                f"Hello {row['student_name']},\n\n"
                f"Your appeal for application {row['code']} ({row['scholarship_type']}) was declined.\n\n"
                f"Response: {response_text}",
            )
            audit(
                conn,
                user,
                "appeal_declined",
                "application",
                row["id"],
                {"code": row["code"], "response": response_text},
            )
        return application_out(conn, load_application(conn, row["id"]))


@router.delete("/staff/applications/{app_id}")
def delete_application(app_id: str, request: Request):
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin", "super_admin")
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
        result = application_out(conn, load_application(conn, row["id"]))
        result["status"] = student_status(result["status"])
        return result


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
        user = current_user(conn, request, "staff", "admin", "super_admin")
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
        max_attempts = BASE_DOCUMENT_ATTEMPTS + document_allowance(conn, row["id"], doc_key)
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
            if latest["attempt_no"] >= max_attempts:
                message += (
                    " You have used all attempts; wait for the CSS Office to allow another resubmission."
                )
        add_history(conn, row["id"], "Approved", event, user["full_name"], remarks)
        flag_changed_after_finance(conn, row, user, remarks)
        notify(conn, [row["owner_id"]], row["id"], message)
        remaining = max_attempts - latest["attempt_no"]
        email_lines = [
            f"Hello {row['student_name']},",
            "",
            f"Your {label} for {row['code']} was {body.review.lower()} "
            f"(attempt {latest['attempt_no']} of {max_attempts}).",
        ]
        if reason:
            email_lines.append(f"Reason: {reason}")
        email_lines.append(f"Attempts remaining: {remaining}.")
        if body.review == "Rejected":
            email_lines.append("Please correct it and upload a new copy through the portal.")
            if remaining <= 0:
                email_lines.append(
                    "You have used all attempts; wait for the CSS Office to allow another resubmission."
                )
        queue_email(
            row["owner_id"],
            row["id"],
            row["student_email"],
            f"Your {label} was {body.review.lower()}",
            "\n".join(email_lines),
        )
        return application_out(conn, load_application(conn, row["id"]))


@router.post("/staff/applications/{app_id}/documents/{doc_key}/allow-resubmission")
def allow_document_resubmission(app_id: str, doc_key: str, body: AllowResubmissionIn, request: Request):
    if doc_key not in POST_APPROVAL_DOCUMENT_KEYS:
        raise bad_request("Unknown document type.")
    reason = " ".join(str(body.reason or "").split())[:1000]
    if not reason:
        raise bad_request("Please provide a reason for allowing another resubmission.")
    with transaction() as conn:
        user = current_user(conn, request, "staff", "admin", "super_admin")
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
        queue_email(
            row["owner_id"],
            row["id"],
            row["student_email"],
            f"Resubmission allowed for your {label}",
            f"Hello {row['student_name']},\n\n"
            f"The CSS Office allowed another resubmission of your {label} for {row['code']} "
            f"(attempt {latest['attempt_no'] + 1} of {max_attempts}).\n\n"
            f"Reason: {reason}",
        )
        return application_out(conn, load_application(conn, row["id"]))
