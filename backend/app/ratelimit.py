from datetime import datetime, timezone

import psycopg
from fastapi import HTTPException

from .db import transaction

LOGIN_MAX_FAILURES = 20
LOGIN_WINDOW_SECONDS = 900
REGISTER_MAX_REQUESTS = 10
REGISTER_WINDOW_SECONDS = 600
RESET_MAX_REQUESTS = 10
RESET_WINDOW_SECONDS = 900


def client_ip(request):
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if forwarded:
        return forwarded[-1]
    return request.client.host if request.client else "unknown"


def record_hit(conn, scope, bucket, window_seconds):
    return conn.execute(
        """
        insert into rate_limits (scope, bucket, hits, expires_at)
        values (%s, %s, 1, now() + make_interval(secs => %s::double precision))
        on conflict (scope, bucket) do update
          set hits = case
              when rate_limits.expires_at <= now() then 1
              else rate_limits.hits + 1
            end,
            expires_at = case
              when rate_limits.expires_at <= now()
                then now() + make_interval(secs => %s::double precision)
              else rate_limits.expires_at
            end
        returning hits, expires_at
        """,
        (scope, bucket, window_seconds, window_seconds),
    ).fetchone()


def enforce_rate_limit(scope, request, limit, window_seconds, message):
    row = None
    try:
        with transaction() as conn:
            conn.execute("delete from rate_limits where expires_at <= now()")
            row = record_hit(conn, scope, client_ip(request), window_seconds)
    except psycopg.errors.UndefinedTable:
        return
    if not row or row["hits"] <= limit:
        return
    remaining = max(1, int((row["expires_at"] - datetime.now(timezone.utc)).total_seconds()))
    raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(remaining)})
