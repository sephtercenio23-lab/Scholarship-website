import smtplib
from contextvars import ContextVar
from email.message import EmailMessage

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from .config import get_settings

SMTP_TIMEOUT = 8
UNIVERSITY_NAME = "Panpacific University"

_email_queue = ContextVar("email_queue", default=None)


def mail_configured():
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def deliver(to_address, subject, body, settings=None):
    settings = settings or get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
        server.starttls()
    with server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def send_mail(to_address, subject, body):
    try:
        deliver(to_address, subject, body)
    except (smtplib.SMTPException, OSError):
        raise HTTPException(status_code=502, detail="The email could not be sent. Please try again later.")


def render_message(body):
    settings = get_settings()
    lines = [UNIVERSITY_NAME, "", body.strip()]
    if settings.public_base_url:
        lines.extend(["", f"Sign in to the scholarship portal: {settings.public_base_url}"])
    return "\n".join(lines) + "\n"


def queue_email(user_id, application_id, to_address, subject, body):
    if not mail_configured() or not to_address:
        return
    queue = _email_queue.get()
    if queue is None:
        queue = []
        _email_queue.set(queue)
    queue.append(
        {
            "user_id": str(user_id) if user_id else None,
            "application_id": str(application_id) if application_id else None,
            "to": to_address,
            "subject": subject,
            "body": render_message(body),
        }
    )


def flush_email_queue():
    try:
        items = _email_queue.get()
        if not items:
            return
        _email_queue.set([])
        if not mail_configured():
            return
        settings = get_settings()
        with psycopg.connect(
            settings.database_url,
            row_factory=dict_row,
            prepare_threshold=None,
            connect_timeout=10,
        ) as conn:
            for item in items:
                status = "sent"
                error = None
                try:
                    deliver(item["to"], item["subject"], item["body"], settings)
                except Exception as exc:
                    status = "failed"
                    error = " ".join(str(exc).split())[:1000] or exc.__class__.__name__
                try:
                    conn.execute(
                        """
                        insert into email_log (user_id, application_id, subject, status, error)
                        values (%s, %s, %s, %s, %s)
                        """,
                        (
                            item["user_id"],
                            item["application_id"],
                            item["subject"],
                            status,
                            error,
                        ),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
    except Exception:
        pass
