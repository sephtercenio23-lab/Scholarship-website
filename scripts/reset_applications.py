# ============================================================================
# WARNING - IRREVERSIBLE ONE-TIME DATA RESET
#
# This script permanently deletes ALL application data in the production
# database and every file in the "documents" storage bucket:
#   applications, application_documents, application_document_submissions,
#   application_document_allowances, application_history, notifications,
#   and all uploaded files.
#
# It does NOT touch: users, academic_terms, term_scholarships.
#
# Run it deliberately, exactly once, before deploying the staged-document
# release. Take a Supabase backup first (Dashboard -> Database -> Backups,
# or export the affected tables) and make sure no student is mid-application.
#
# This is NOT part of the schema migration. Nothing runs it automatically.
# Usage:
#   python scripts/reset_applications.py --confirm
# ============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import storage
from backend.app.db import transaction

CONFIRM_FLAG = "--confirm"
CONFIRM_WORD = "RESET"
DELETE_BATCH = 100

RESET_TABLES = [
    "application_document_submissions",
    "application_document_allowances",
    "application_history",
    "application_documents",
    "notifications",
    "applications",
]
KEPT_TABLES = ["users", "academic_terms", "term_scholarships"]


def count_rows(conn, table):
    return conn.execute(f"select count(*) as total from {table}").fetchone()["total"]


def main():
    if CONFIRM_FLAG not in sys.argv[1:]:
        print("This script wipes all application data. Re-run with the --confirm flag to proceed.")
        sys.exit(1)

    with transaction() as conn:
        print("The following data will be PERMANENTLY DELETED:\n")
        for table in RESET_TABLES:
            print(f"  - {table}: {count_rows(conn, table)} rows")
        print("\nThe following tables are kept untouched:")
        for table in KEPT_TABLES:
            print(f"  - {table}: {count_rows(conn, table)} rows (kept)")
        print(f"\n  - every file in the '{storage.get_settings().bucket}' storage bucket")
        print("\n  - application_code_seq will be reset to 1")

    typed = input("\nType RESET (uppercase) to permanently erase this data: ").strip()
    if typed != CONFIRM_WORD:
        print("You did not type RESET. Nothing was changed.")
        sys.exit(1)

    with transaction() as conn:
        for table in RESET_TABLES:
            deleted = conn.execute(f"delete from {table}").rowcount
            print(f"Deleted {deleted} row(s) from {table}.")
        conn.execute("alter sequence application_code_seq restart with 1")
        print("application_code_seq reset to 1.")

    paths = storage.list_object_paths()
    print(f"Found {len(paths)} file(s) in the '{storage.get_settings().bucket}' bucket.")
    for start in range(0, len(paths), DELETE_BATCH):
        batch = paths[start : start + DELETE_BATCH]
        storage.remove_objects(batch)
        print(f"Deleted {len(batch)} file(s) ({start + len(batch)} of {len(paths)}).")

    print("\nReset complete. Users, academic terms and term scholarships were kept.")


if __name__ == "__main__":
    main()
