import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.catalog import ROLE_LABELS
from backend.app.common import ensure_user_role_check
from backend.app.db import transaction
from backend.app.security import (
    check_letters_only,
    check_password,
    check_university_email,
    hash_password,
    normalize_email,
)

CREATABLE_ROLES = ("staff", "admin", "president", "executive_president", "super_admin")


def main():
    if len(sys.argv) not in (3, 4):
        print(
            'Usage: python scripts/create_admin.py "Full Name" email@panpacificu.edu.ph [role]\n'
            "Roles: " + ", ".join(CREATABLE_ROLES) + " (default: admin)"
        )
        sys.exit(1)
    role = (sys.argv[3] if len(sys.argv) == 4 else "admin").strip().lower()
    if role not in CREATABLE_ROLES:
        print(f"Role must be one of: {', '.join(CREATABLE_ROLES)}")
        sys.exit(1)
    full_name = check_letters_only(sys.argv[1], "Full name")
    email = normalize_email(sys.argv[2])
    check_university_email(email)
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    check_password(password)
    password_hash = hash_password(password)
    ensure_user_role_check()
    with transaction() as conn:
        existing = conn.execute(
            "select id from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                update users
                set full_name = %s, password_hash = %s, role = %s, token_version = token_version + 1,
                    failed_attempts = 0, locked_until = null, updated_at = now()
                where id = %s
                """,
                (full_name, password_hash, role, existing["id"]),
            )
            print(f"Existing account updated and set as {ROLE_LABELS.get(role, role)}.")
        else:
            conn.execute(
                "insert into users (full_name, email, password_hash, role) values (%s, %s, %s, %s)",
                (full_name, email, password_hash, role),
            )
            print(f"{ROLE_LABELS.get(role, role)} account created.")


if __name__ == "__main__":
    main()
