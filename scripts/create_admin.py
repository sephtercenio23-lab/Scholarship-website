import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.db import transaction
from backend.app.security import (
    check_letters_only,
    check_password,
    check_university_email,
    hash_password,
    normalize_email,
)


def main():
    if len(sys.argv) != 3:
        print('Usage: python scripts/create_admin.py "Full Name" email@panpacificu.edu.ph')
        sys.exit(1)
    full_name = check_letters_only(sys.argv[1], "Full name")
    email = normalize_email(sys.argv[2])
    check_university_email(email)
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    check_password(password)
    password_hash = hash_password(password)
    with transaction() as conn:
        existing = conn.execute(
            "select id from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                update users
                set full_name = %s, password_hash = %s, role = 'admin', token_version = token_version + 1,
                    failed_attempts = 0, locked_until = null, updated_at = now()
                where id = %s
                """,
                (full_name, password_hash, existing["id"]),
            )
            print("Existing account updated and set as Admin.")
        else:
            conn.execute(
                "insert into users (full_name, email, password_hash, role) values (%s, %s, %s, 'admin')",
                (full_name, email, password_hash),
            )
            print("Admin account created.")


if __name__ == "__main__":
    main()
