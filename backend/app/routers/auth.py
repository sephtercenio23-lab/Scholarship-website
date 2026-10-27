from datetime import datetime, timedelta, timezone
from html import escape

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from ..catalog import YEAR_LEVELS
from ..common import audit, user_out
from ..config import get_settings
from ..db import transaction
from ..deps import current_user
from ..mailer import mail_configured, send_mail
from ..ratelimit import (
    LOGIN_MAX_FAILURES,
    LOGIN_WINDOW_SECONDS,
    REGISTER_MAX_REQUESTS,
    REGISTER_WINDOW_SECONDS,
    RESET_MAX_REQUESTS,
    RESET_WINDOW_SECONDS,
    enforce_rate_limit,
)
from ..schemas import LoginIn, RegisterIn, ResetConfirmIn, ResetRequestIn
from ..security import (
    DUMMY_HASH,
    RESET_COOKIE,
    SESSION_COOKIE,
    bad_request,
    check_letters_only,
    check_password,
    check_student_id,
    check_university_email,
    clear_cookie,
    create_token,
    decode_token,
    hash_password,
    normalize_email,
    set_cookie,
    start_session,
    verify_password,
)

router = APIRouter(prefix="/auth")

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
RESET_LINK_MINUTES = 30
RESET_SESSION_MINUTES = 15
TOO_MANY_LOGINS = "Too many failed login attempts from this network. Please try again in a few minutes."
TOO_MANY_REGISTRATIONS = "Too many registration attempts from this network. Please try again in a few minutes."
TOO_MANY_RESETS = "Too many password reset requests from this network. Please try again in a few minutes."


@router.get("/me")
def me(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    payload = decode_token(token, "session") if token else None
    if not payload:
        if token:
            clear_cookie(response, SESSION_COOKIE)
        return {"user": None}
    with transaction() as conn:
        try:
            user = conn.execute(
                "select * from users where id = %s and deleted_at is null", (payload.get("sub"),)
            ).fetchone()
        except Exception:
            conn.rollback()
            user = None
        if not user or user["token_version"] != payload.get("tv"):
            clear_cookie(response, SESSION_COOKIE)
            return {"user": None}
        return {"user": user_out(user)}


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response):
    enforce_rate_limit(
        "register", request, REGISTER_MAX_REQUESTS, REGISTER_WINDOW_SECONDS, TOO_MANY_REGISTRATIONS
    )
    full_name = check_letters_only(body.fullName, "Full name")
    student_id = check_student_id(body.studentId)
    email = normalize_email(body.email)
    check_university_email(email)
    program = check_letters_only(body.program, "Program/Course")
    if body.yearLevel not in YEAR_LEVELS:
        raise bad_request("Please select your year level.")
    check_password(body.password)
    password_hash = hash_password(body.password)
    with transaction() as conn:
        if conn.execute(
            "select 1 from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        if conn.execute(
            "select 1 from users where student_id = %s and deleted_at is null", (student_id,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="An account with this student ID already exists.")
        try:
            user = conn.execute(
                """
                insert into users (full_name, email, password_hash, role, student_id, program, year_level)
                values (%s, %s, %s, 'student', %s, %s, %s)
                returning *
                """,
                (full_name, email, password_hash, student_id, program, body.yearLevel),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="An account with these details already exists.")
        start_session(response, user)
        return {"user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    email = normalize_email(body.email)
    invalid = HTTPException(status_code=401, detail="Incorrect email or password.")
    with transaction() as conn:
        user = conn.execute(
            "select * from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone()
    if not user:
        verify_password(body.password, DUMMY_HASH)
        enforce_rate_limit("login", request, LOGIN_MAX_FAILURES, LOGIN_WINDOW_SECONDS, TOO_MANY_LOGINS)
        raise invalid
    with transaction() as conn:
        now = datetime.now(timezone.utc)
        if user["locked_until"] and user["locked_until"] > now:
            raise HTTPException(
                status_code=429, detail="Too many failed attempts. Please try again in a few minutes."
            )
        if not verify_password(body.password, user["password_hash"]):
            attempts = user["failed_attempts"] + 1
            locked_until = now + timedelta(minutes=LOCK_MINUTES) if attempts >= MAX_FAILED_ATTEMPTS else None
            conn.execute(
                "update users set failed_attempts = %s, locked_until = %s where id = %s",
                (0 if locked_until else attempts, locked_until, user["id"]),
            )
            if locked_until:
                audit(
                    conn,
                    user,
                    "account_locked",
                    "user",
                    user["id"],
                    {"failedAttempts": attempts, "lockedMinutes": LOCK_MINUTES},
                )
            conn.commit()
            raise invalid
        if user["failed_attempts"] or user["locked_until"]:
            conn.execute(
                "update users set failed_attempts = 0, locked_until = null where id = %s", (user["id"],)
            )
        start_session(response, user)
        return {"user": user_out(user)}


@router.post("/logout")
def logout(response: Response):
    clear_cookie(response, SESSION_COOKIE)
    return {"ok": True}


@router.post("/password-reset/request")
def password_reset_request(body: ResetRequestIn, request: Request):
    email = normalize_email(body.email)
    check_university_email(email)
    enforce_rate_limit("password-reset", request, RESET_MAX_REQUESTS, RESET_WINDOW_SECONDS, TOO_MANY_RESETS)
    if not mail_configured():
        raise HTTPException(
            status_code=503,
            detail="Password reset email is not available right now. Please contact the CSS Office.",
        )
    with transaction() as conn:
        user = conn.execute(
            "select * from users where lower(email) = %s and deleted_at is null", (email,)
        ).fetchone()
    if user:
        settings = get_settings()
        base = settings.public_base_url or str(request.base_url).rstrip("/")
        token = create_token(
            {"purpose": "reset_link", "sub": str(user["id"]), "tv": user["token_version"]},
            RESET_LINK_MINUTES,
        )
        send_mail(
            user["email"],
            "Verify your password reset - Panpacific University Scholarship Portal",
            "Hello "
            + user["full_name"]
            + ",\n\nOpen this link in the same browser where you requested the reset to verify it is you:\n\n"
            + f"{base}/api/auth/password-reset/verify?token={token}\n\n"
            + f"The link expires in {RESET_LINK_MINUTES} minutes. After opening it, go back to the "
            + "reset password page and submit your new password.\n\n"
            + "If you did not request this, you can ignore this email.",
        )
    return {"ok": True}


@router.get("/password-reset/verify", response_class=HTMLResponse)
def password_reset_verify(token: str = ""):
    payload = decode_token(token, "reset_link") if token else None
    page = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Password reset</title></head><body style='font-family:sans-serif;max-width:480px;margin:15vh auto;padding:0 20px;text-align:center'><h2>{title}</h2><p>{text}</p></body></html>"
    if not payload:
        return HTMLResponse(
            page.format(
                title="Link expired",
                text="This verification link is invalid or has expired. Please request a new password reset.",
            ),
            status_code=400,
        )
    with transaction() as conn:
        user = conn.execute(
            "select * from users where id = %s and deleted_at is null", (payload["sub"],)
        ).fetchone()
    if not user or user["token_version"] != payload["tv"]:
        return HTMLResponse(
            page.format(
                title="Link expired",
                text="This verification link is no longer valid. Please request a new password reset.",
            ),
            status_code=400,
        )
    response = HTMLResponse(
        page.format(
            title="Email verified",
            text=escape("Go back to the reset password page and submit your new password."),
        )
    )
    verified = create_token(
        {"purpose": "reset_verified", "sub": str(user["id"]), "tv": user["token_version"]},
        RESET_SESSION_MINUTES,
    )
    set_cookie(response, RESET_COOKIE, verified, RESET_SESSION_MINUTES * 60)
    return response


@router.post("/password-reset/confirm")
def password_reset_confirm(body: ResetConfirmIn, request: Request, response: Response):
    email = normalize_email(body.email)
    token = request.cookies.get(RESET_COOKIE)
    payload = decode_token(token, "reset_verified") if token else None
    if not payload:
        raise bad_request(
            "Open the verification link we emailed you first, then submit your new password again."
        )
    check_password(body.newPassword)
    with transaction() as conn:
        user = conn.execute(
            "select * from users where id = %s and deleted_at is null", (payload["sub"],)
        ).fetchone()
        if (
            not user
            or user["token_version"] != payload["tv"]
            or user["email"].lower() != email
        ):
            raise bad_request("This reset request is no longer valid. Please request a new one.")
        conn.execute(
            """
            update users
            set password_hash = %s, token_version = token_version + 1,
                failed_attempts = 0, locked_until = null, updated_at = now()
            where id = %s
            """,
            (hash_password(body.newPassword), user["id"]),
        )
    clear_cookie(response, RESET_COOKIE)
    clear_cookie(response, SESSION_COOKIE)
    return {"ok": True}
