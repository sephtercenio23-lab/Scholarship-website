from fastapi import HTTPException, Request

from .security import SESSION_COOKIE, decode_token


def current_user(conn, request: Request, *roles):
    token = request.cookies.get(SESSION_COOKIE)
    payload = decode_token(token, "session") if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    try:
        row = conn.execute(
            "select * from users where id = %s and deleted_at is null", (payload.get("sub"),)
        ).fetchone()
    except Exception:
        conn.rollback()
        row = None
    if not row or row["token_version"] != payload.get("tv"):
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")
    if roles and row["role"] not in roles:
        raise HTTPException(status_code=403, detail="You do not have permission to do this.")
    return row
