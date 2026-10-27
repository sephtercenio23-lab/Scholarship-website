from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request

from ..common import AUDIT_ACTIONS, MANILA_TZ, audit_out
from ..db import transaction
from ..deps import current_user
from ..security import bad_request

router = APIRouter(prefix="/admin")


def parse_audit_date(value, label):
    text = " ".join(str(value or "").split())
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise bad_request(f"{label} must be a valid date in YYYY-MM-DD format.")


@router.get("/audit-log")
def get_audit_log(
    request: Request,
    action: str = "",
    actor: str = "",
    fromDate: str = "",
    toDate: str = "",
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    action = " ".join(action.split())
    actor = " ".join(actor.split())
    if action and action not in AUDIT_ACTIONS:
        raise bad_request("Unknown audit action filter.")
    start_date = parse_audit_date(fromDate, "Start date")
    end_date = parse_audit_date(toDate, "End date")
    if start_date and end_date and start_date > end_date:
        raise bad_request("The start date cannot be after the end date.")
    where = []
    params = []
    if action:
        where.append("action = %s")
        params.append(action)
    if actor:
        where.append("actor_name ilike %s")
        params.append(f"%{actor}%")
    if start_date:
        where.append("created_at >= %s")
        params.append(datetime.combine(start_date, datetime.min.time(), tzinfo=MANILA_TZ))
    if end_date:
        where.append("created_at < %s")
        params.append(
            datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=MANILA_TZ)
        )
    clause = " where " + " and ".join(where) if where else ""
    with transaction() as conn:
        current_user(conn, request, "admin")
        total = conn.execute(
            f"select count(*) as total from audit_log{clause}", params
        ).fetchone()["total"]
        rows = conn.execute(
            f"""
            select * from audit_log{clause}
            order by created_at desc, id desc
            limit %s offset %s
            """,
            (*params, pageSize, (page - 1) * pageSize),
        ).fetchall()
        return {
            "items": [audit_out(row) for row in rows],
            "page": page,
            "pageSize": pageSize,
            "total": total,
        }
