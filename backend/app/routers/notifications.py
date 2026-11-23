from fastapi import APIRouter, HTTPException, Request

from ..common import ensure_current_term, iso, parse_uuid
from ..db import transaction
from ..deps import current_user

router = APIRouter(prefix="/notifications")


def ensure_deadline_reminders(conn, user):
    # Deadline reminders are created lazily when a student checks notifications, so no cron job is needed.
    if user["role"] != "student":
        return
    term = ensure_current_term(conn)
    rows = conn.execute(
        """
        select scholarship_key, deadline, deadline_at
        from term_scholarships
        where term_id = %s and status = 'Open' and deadline_at is not null
          and deadline_at > now() and deadline_at <= now() + interval '7 days'
        """,
        (term["id"],),
    ).fetchall()
    for item in rows:
        message = f"Reminder: The deadline for {item['scholarship_key']} is {item['deadline']}."
        exists = conn.execute(
            """
            select 1 from notifications
            where user_id = %s and message = %s and (created_at at time zone 'Asia/Manila')::date = (now() at time zone 'Asia/Manila')::date
            """,
            (user["id"], message),
        ).fetchone()
        if not exists:
            conn.execute(
                "insert into notifications (user_id, application_id, message, type) values (%s, null, %s, 'student')",
                (user["id"], message),
            )


@router.get("")
def list_notifications(request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        ensure_deadline_reminders(conn, user)
        rows = conn.execute(
            """
            select n.id, n.application_id, n.message, n.type, n.is_read, n.created_at
            from notifications n
            left join applications a on a.id = n.application_id
            where n.user_id = %s and (n.application_id is null or a.deleted_at is null)
            order by n.created_at desc
            limit 200
            """,
            (user["id"],),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "appId": str(row["application_id"]) if row["application_id"] else None,
                "message": row["message"],
                "type": row["type"],
                "read": row["is_read"],
                "date": iso(row["created_at"]),
            }
            for row in rows
        ]


@router.get("/unread-count")
def unread_count(request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        ensure_deadline_reminders(conn, user)
        row = conn.execute(
            """
            select count(*) as total
            from notifications n
            left join applications a on a.id = n.application_id
            where n.user_id = %s and not n.is_read and (n.application_id is null or a.deleted_at is null)
            """,
            (user["id"],),
        ).fetchone()
        return {"count": row["total"]}


@router.post("/read-all")
def read_all(request: Request):
    with transaction() as conn:
        user = current_user(conn, request)
        conn.execute(
            "update notifications set is_read = true where user_id = %s and not is_read", (user["id"],)
        )
        return {"ok": True}


@router.patch("/{notification_id}/read")
def mark_read(notification_id: str, request: Request):
    target_id = parse_uuid(notification_id)
    with transaction() as conn:
        user = current_user(conn, request)
        row = conn.execute(
            "update notifications set is_read = true where id = %s and user_id = %s returning id",
            (target_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notification not found.")
        return {"ok": True}
