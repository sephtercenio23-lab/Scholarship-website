from fastapi import APIRouter, Request, Response

from ..catalog import YEAR_LEVELS
from ..common import audit, user_out
from ..db import transaction
from ..deps import current_user
from ..schemas import ChangePasswordIn, ProfileIn
from ..security import (
    bad_request,
    check_letters_only,
    check_password,
    hash_password,
    start_session,
    verify_password,
)

router = APIRouter(prefix="/users")


@router.patch("/me")
def update_profile(body: ProfileIn, request: Request):
    program = check_letters_only(body.program, "Degree program")
    if body.yearLevel not in YEAR_LEVELS:
        raise bad_request("Please select your year level.")
    with transaction() as conn:
        user = current_user(conn, request, "student")
        row = conn.execute(
            "update users set program = %s, year_level = %s, updated_at = now() where id = %s returning *",
            (program, body.yearLevel, user["id"]),
        ).fetchone()
        return {"user": user_out(row)}


@router.post("/me/password")
def change_password(body: ChangePasswordIn, request: Request, response: Response):
    with transaction() as conn:
        user = current_user(conn, request)
        if not verify_password(body.currentPassword, user["password_hash"]):
            raise bad_request("Current password is incorrect.")
        check_password(body.newPassword)
        if body.newPassword == body.currentPassword:
            raise bad_request("New password must be different from your current password.")
        row = conn.execute(
            """
            update users
            set password_hash = %s, token_version = token_version + 1, updated_at = now()
            where id = %s
            returning *
            """,
            (hash_password(body.newPassword), user["id"]),
        ).fetchone()
        audit(conn, user, "password_changed", "user", user["id"], {})
        start_session(response, row)
        return {"ok": True}
