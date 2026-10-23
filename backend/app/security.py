import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Response

from .config import get_settings

SESSION_COOKIE = "sams_session"
RESET_COOKIE = "sams_reset"
UNIVERSITY_DOMAIN = "@panpacificu.edu.ph"
PASSWORD_MIN_LENGTH = 8

SPECIAL_CHARACTER = re.compile(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?~`]")
LETTERS_ONLY = re.compile(
    r"^[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF][A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF .,'&-]*$"
)
STUDENT_ID_FORMAT = re.compile(r"^[0-9]{7}$")

DUMMY_HASH = "$2b$12$./xa6csxeCdaUP473JEbvuKD0I96nOiJzlUOj3KIGirmEdjtD5UB2"


def bad_request(message):
    return HTTPException(status_code=400, detail=message)


def normalize_email(email):
    return str(email or "").strip().lower()


def check_university_email(email):
    if not email:
        raise bad_request("University email is required.")
    if not email.endswith(UNIVERSITY_DOMAIN) or len(email) <= len(UNIVERSITY_DOMAIN):
        raise bad_request(f"Only {UNIVERSITY_DOMAIN} email addresses are accepted.")
    local = email[: -len(UNIVERSITY_DOMAIN)]
    if not re.fullmatch(r"[a-z0-9._%+\-]+", local):
        raise bad_request("The university email address is not valid.")


def clean_text(value, label, max_length=120):
    text = " ".join(str(value or "").split())
    if not text:
        raise bad_request(f"{label} is required.")
    if len(text) > max_length:
        raise bad_request(f"{label} must be at most {max_length} characters.")
    return text


def check_letters_only(value, label):
    text = clean_text(value, label)
    if not LETTERS_ONLY.match(text):
        raise bad_request(f"{label} must contain letters only. Numbers are not allowed.")
    return text


def check_student_id(value):
    text = str(value or "").strip()
    if not text:
        raise bad_request("Student ID is required.")
    if not STUDENT_ID_FORMAT.match(text):
        raise bad_request("Student ID must be exactly 7 digits (example: 0000000).")
    return text


def check_password(password):
    text = password or ""
    if len(text) < PASSWORD_MIN_LENGTH:
        raise bad_request(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(text.encode("utf-8")) > 72:
        raise bad_request("Password must be at most 72 characters long.")
    if not re.search(r"[A-Z]", text):
        raise bad_request("Password must include at least 1 uppercase letter.")
    if not re.search(r"[0-9]", text):
        raise bad_request("Password must include at least 1 number.")
    if not SPECIAL_CHARACTER.search(text):
        raise bad_request("Password must include at least 1 special character.")


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password, hashed):
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(payload, minutes):
    now = datetime.now(timezone.utc)
    body = {**payload, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(body, get_settings().jwt_secret, algorithm="HS256")


def decode_token(token, purpose):
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != purpose:
        return None
    return payload


def set_cookie(response: Response, name, value, max_age):
    settings = get_settings()
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_cookie(response: Response, name):
    settings = get_settings()
    response.delete_cookie(
        name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def start_session(response: Response, user):
    settings = get_settings()
    token = create_token(
        {"purpose": "session", "sub": str(user["id"]), "tv": user["token_version"]},
        settings.session_hours * 60,
    )
    set_cookie(response, SESSION_COOKIE, token, settings.session_hours * 3600)
