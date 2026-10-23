import psycopg
from fastapi import APIRouter, HTTPException, Request, Response

from ..common import account_out, parse_uuid
from ..db import transaction
from ..deps import current_user
from ..schemas import AccountIn, AccountUpdateIn
from ..security import (
    bad_request,
    check_letters_only,
    check_password,
    check_university_email,
    hash_password,
    normalize_email,
    start_session,
)

router = APIRouter(prefix="/admin/accounts")

ROLES = ("student", "staff", "admin")


def duplicate_email():
    return HTTPException(status_code=409, detail="An account with this email already exists.")


@router.get("")
def list_accounts(request: Request):
    with transaction() as conn:
        current_user(conn, request, "admin")
        rows = conn.execute(
            "select * from users where deleted_at is null order by created_at desc"
        ).fetchall()
        return [account_out(row) for row in rows]


@router.post("")
def create_account(body: AccountIn, request: Request):
    if body.role not in ("staff", "admin"):
        raise bad_request("Please choose Authorized Staff or Admin.")
    full_name = check_letters_only(body.fullName, "Full name")
    email = normalize_email(body.email)
    check_university_email(email)
    check_password(body.password)
    password_hash = hash_password(body.password)
    with transaction() as conn:
        current_user(conn, request, "admin")
        if conn.execute(
            "select 1 from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone():
            raise duplicate_email()
        try:
            row = conn.execute(
                """
                insert into users (full_name, email, password_hash, role)
                values (%s, %s, %s, %s)
                returning *
                """,
                (full_name, email, password_hash, body.role),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise duplicate_email()
        return account_out(row)


@router.put("/{user_id}")
def update_account(user_id: str, body: AccountUpdateIn, request: Request, response: Response):
    target_id = parse_uuid(user_id)
    if body.role not in ROLES:
        raise bad_request("Please choose a valid role.")
    full_name = check_letters_only(body.fullName, "Full name")
    email = normalize_email(body.email)
    check_university_email(email)
    password = body.password or ""
    if password:
        check_password(password)
    with transaction() as conn:
        admin = current_user(conn, request, "admin")
        target = conn.execute(
            "select * from users where id = %s and deleted_at is null for update", (target_id,)
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Account not found.")
        is_self = str(target["id"]) == str(admin["id"])
        if is_self and body.role != target["role"]:
            raise bad_request("You cannot change your own role.")
        if conn.execute(
            "select 1 from users where lower(email) = %s and id <> %s and deleted_at is null",
            (email, target_id),
        ).fetchone():
            raise duplicate_email()
        try:
            if password:
                row = conn.execute(
                    """
                    update users
                    set full_name = %s, email = %s, role = %s, password_hash = %s,
                        token_version = token_version + 1, failed_attempts = 0,
                        locked_until = null, updated_at = now()
                    where id = %s
                    returning *
                    """,
                    (full_name, email, body.role, hash_password(password), target_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    update users
                    set full_name = %s, email = %s, role = %s, updated_at = now()
                    where id = %s
                    returning *
                    """,
                    (full_name, email, body.role, target_id),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise duplicate_email()
        if is_self and password:
            start_session(response, row)
        return account_out(row)


@router.delete("/{user_id}")
def delete_account(user_id: str, request: Request):
    target_id = parse_uuid(user_id)
    with transaction() as conn:
        admin = current_user(conn, request, "admin")
        if target_id == str(admin["id"]):
            raise bad_request("You cannot delete your own account.")
        row = conn.execute(
            """
            update users
            set deleted_at = now(), token_version = token_version + 1, updated_at = now()
            where id = %s and deleted_at is null
            returning *
            """,
            (target_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found.")
        return {"ok": True}
