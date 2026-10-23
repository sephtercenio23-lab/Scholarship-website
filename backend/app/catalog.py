import re

TRIMESTERS = ["1st Trimester", "2nd Trimester", "3rd Trimester"]
YEAR_LEVELS = ["1st Year", "2nd Year", "3rd Year", "4th Year", "Irregular"]
STATUSES = ["Submitted", "Under Evaluation", "Approved", "Rejected"]

DEFAULT_TERM = {"trimester": "1st Trimester", "academic_year": "2026\u20132027"}

BENEFIT_TEXT = "Benefits to be confirmed by the CSS Office"
DEADLINE_TEXT = "To be announced"

DOCUMENT_KEYS = ["copyOfGrades", "letterOfIntent", "notarizedAgreement"]
DOCUMENT_LABELS = {
    "copyOfGrades": "Copy of Grades",
    "letterOfIntent": "Letter of Intent",
    "notarizedAgreement": "Notarized Scholarship Agreement",
    "terminalReport": "Terminal report",
}
ALL_DOCUMENT_KEYS = DOCUMENT_KEYS + ["terminalReport"]

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


def program_not_offered(program, trimester):
    return trimester == "3rd Trimester" and bool(re.search("nursing", program or "", re.I))


def term_sort_key(academic_year, trimester):
    return (int(str(academic_year)[:4]), TRIMESTERS.index(trimester))


def term_label(trimester, academic_year):
    return f"{trimester}, AY {academic_year}"
