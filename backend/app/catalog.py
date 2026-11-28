import re

TRIMESTERS = ["1st Trimester", "2nd Trimester", "3rd Trimester"]
YEAR_LEVELS = ["1st Year", "2nd Year", "3rd Year", "4th Year", "Irregular"]
ROLES = ["student", "staff", "admin", "president", "executive_president", "super_admin"]
NON_STUDENT_ROLES = ["staff", "admin", "president", "executive_president", "super_admin"]
ADMIN_ROLES = ["admin", "super_admin"]
# Who may start a new term on the dashboard: Authorized Staff plus the admins.
TERM_MANAGE_ROLES = ["staff", "admin", "super_admin"]
# Keep role, status and event keys stable for existing accounts and approval histories.
APPROVAL_STAGES = ["staff", "president", "executive_president"]
APPROVAL_STAGE_LABELS = {
    "staff": "Authorized Staff",
    "president": "Director of Academic Services",
    "executive_president": "University President",
}
APPROVAL_STAGE_EVENTS = {
    "staff": "staff_endorsed",
    "president": "president_approved",
    "executive_president": "executive_approved",
}
# Application status flow: Submitted -> Under Evaluation -> Endorsed by Staff ->
# Approved by President -> Approved by Executive President -> Sent to Finance.
# "Exported" and "Approved" remain valid for applications saved before this flow.
STATUSES = [
    "Submitted",
    "Under Evaluation",
    "Endorsed by Staff",
    "Approved by President",
    "Approved by Executive President",
    "Sent to Finance",
    "Exported",
    "Approved",
    "Rejected",
]
# The status reached after the third approval: the scholars were emailed to Finance.
FINANCE_STATUS = "Sent to Finance"
# Flag shown on an application that was edited after it had already been sent to Finance.
CHANGED_AFTER_FINANCE = "Changed after sent to Finance"
# Finance receives the approved scholars (and later the correction lists) by email.
FINANCE_EMAIL = "zyren.ynalvez.ihs@panpacificu.edu.ph"
# Status stored when each approval level completes.
STAGE_STATUS = {
    "staff": "Endorsed by Staff",
    "president": "Approved by President",
    "executive_president": "Approved by Executive President",
}
# Use current titles for display; database statuses and API filter values are stable.
STATUS_LABELS = {
    STAGE_STATUS[role]: f"Approved by {APPROVAL_STAGE_LABELS[role]}"
    for role in ("president", "executive_president")
}
# Fully approved statuses: all three approvals are done ("Approved"/"Exported" cover legacy rows).
APPROVED_STATUSES = (
    "Approved",
    "Approved by Executive President",
    "Sent to Finance",
    "Exported",
)
# Statuses that mean the record already reached Finance, so later edits must be re-approved.
FINANCE_SENT_STATUSES = ("Sent to Finance", "Exported", "Approved")
# Statuses still waiting for the current approval level.
PENDING_APPROVAL_STATUSES = ("Under Evaluation", "Endorsed by Staff", "Approved by President")
ROLE_LABELS = {
    **APPROVAL_STAGE_LABELS,
    "student": "Student",
    "admin": "Admin",
    "super_admin": "Super Admin",
}

DEFAULT_TERM = {"trimester": "1st Trimester", "academic_year": "2026\u20132027"}

BENEFIT_TEXT = "Benefits to be confirmed by the CSS Office"
DEADLINE_TEXT = "To be announced"

# Stage 1 (initial application): only Copy of Grades is required.
INITIAL_DOCUMENT_KEYS = ["copyOfGrades"]
# Stage 2 (after staff approval): uploaded and reviewed with the 3-attempt system.
POST_APPROVAL_DOCUMENT_KEYS = ["letterOfIntent", "notarizedAgreement"]
DOCUMENT_KEYS = INITIAL_DOCUMENT_KEYS + POST_APPROVAL_DOCUMENT_KEYS
DOCUMENT_LABELS = {
    "copyOfGrades": "Copy of Grades",
    "letterOfIntent": "Letter of Intent",
    "notarizedAgreement": "Notarized Scholarship Agreement",
}
ALL_DOCUMENT_KEYS = DOCUMENT_KEYS

BASE_DOCUMENT_ATTEMPTS = 3
REVIEW_STATUSES = ["Pending", "Valid", "Rejected"]

ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
MAX_FILE_BYTES = 5 * 1024 * 1024

SCHOLARSHIPS = [
    {
        "key": "Academic Scholarship",
        "min_gwa": 87,
        "min_lowest": 85,
        "eligibility": [
            "Currently enrolled Panpacific University student",
            "GWA of at least 87, with no grade below 85",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "Entrance Exam Scholarship",
        "min_gwa": 87,
        "min_lowest": 85,
        "eligibility": [
            "Qualifying score in the Panpacific University entrance examination",
            "Incoming freshman or transferee student",
            "Complete admission requirements on file",
            "GWA of at least 87, with no grade below 85",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "4Ps Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Household listed under the 4Ps program",
            "Valid 4Ps household ID or certificate",
            "Currently enrolled or incoming Panpacific University student",
            "GWA of at least 85, with no grade below 82",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "Urdanetarian Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Proof of residency in Urdaneta City",
            "GWA of at least 85, with no grade below 82",
            "No failing grade, INC, or dropped remarks",
            "Certificate of residency or barangay clearance",
        ],
    },
    {
        "key": "RPSEA Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Meets RPSEA program qualification criteria",
            "Complete supporting documentation",
            "GWA of at least 85, with no grade below 82",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "SOC Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Meets SOC program qualification criteria",
            "Currently enrolled Panpacific University student",
            "Complete supporting documentation",
            "GWA of at least 85, with no grade below 82",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "BSA Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Meets BSA program qualification criteria",
            "GWA of at least 85, with no grade below 82",
            "Complete supporting documentation",
            "No failing grade, INC, or dropped remarks",
        ],
    },
    {
        "key": "New Program Scholarship",
        "min_gwa": 85,
        "min_lowest": 82,
        "eligibility": [
            "Enrolled in a qualified new academic program",
            "Complete admission requirements",
            "GWA of at least 85, with no grade below 82",
            "No failing grade, INC, or dropped remarks",
        ],
    },
]

SCHOLARSHIP_TYPES = [item["key"] for item in SCHOLARSHIPS]
SCHOLARSHIP_BY_KEY = {item["key"]: item for item in SCHOLARSHIPS}

# Tuition fee discount the student declared for the past term or academic year.
# Stored as 25/50/75/100, or None when the student was not a scholar before.
PAST_DISCOUNT_CHOICES = (25, 50, 75, 100)
PAST_DISCOUNT_NOT_SCHOLAR = "none"


def status_label(status):
    return STATUS_LABELS.get(status, status)


def program_not_offered(program, trimester):
    return trimester == "3rd Trimester" and bool(re.search("nursing", program or "", re.I))


def term_sort_key(academic_year, trimester):
    return (int(str(academic_year)[:4]), TRIMESTERS.index(trimester))


def term_label(trimester, academic_year):
    return f"{trimester}, AY {academic_year}"
