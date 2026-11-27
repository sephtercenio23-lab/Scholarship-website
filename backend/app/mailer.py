import base64
import os
import smtplib
from contextvars import ContextVar
from email.message import EmailMessage
from urllib.parse import urlparse

import httpx
import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from .config import get_settings

SMTP_TIMEOUT = 8
UNIVERSITY_NAME = "Panpacific University"

_email_queue = ContextVar("email_queue", default=None)
_request_base_url = ContextVar("request_base_url", default="")


def set_request_base_url(url):
    return _request_base_url.set(url or "")


def reset_request_base_url(token):
    _request_base_url.reset(token)


def host_only(value):
    text = str(value or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    try:
        return (parsed.hostname or "").lower()
    except ValueError:
        return ""


def normalize_base_url(value):
    text = str(value or "").strip().rstrip("/")
    if not text or any(ch.isspace() for ch in text):
        return ""
    if "://" not in text:
        host_part = text.split("/", 1)[0]
        if host_part.startswith("["):
            host_check = host_part.split("]", 1)[0].lstrip("[").lower()
        else:
            host_check = host_part.split(":", 1)[0].lower()
        scheme = "http" if host_check in {"localhost", "127.0.0.1", "::1"} else "https"
        text = f"{scheme}://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    try:
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return ""
    if not hostname:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def request_origin(request):
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    host = forwarded_host or (request.headers.get("host") or "").strip()
    if not host or host_only(host) == "testserver":
        return ""
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else getattr(request.url, "scheme", "")
    if scheme not in {"http", "https"}:
        scheme = "http" if host_only(host) in {"localhost", "127.0.0.1", "::1"} else "https"
    return normalize_base_url(f"{scheme}://{host}")


def is_ephemeral_vercel_host(value, vercel_url="", vercel_prod_url="", vercel_branch_url=""):
    host = host_only(value)
    if not host or not host.endswith(".vercel.app"):
        return False
    permanent_hosts = {host_only(vercel_prod_url), host_only(vercel_branch_url)} - {""}
    if host in permanent_hosts:
        return False
    vercel_host = host_only(vercel_url)
    if vercel_host and host == vercel_host:
        return True
    # Vercel deployment-specific URLs use <project>-<9-char-id>-<scope>.vercel.app
    # (unlike branch URLs <project>-git-<branch>-<scope>.vercel.app) and are removed
    # by Vercel's retention policy.
    label = host[: -len(".vercel.app")]
    parts = label.split("-")
    for idx in range(1, len(parts) - 1):
        if parts[idx - 1] == "git":
            continue
        if len(parts[idx]) == 9 and parts[idx].isalnum():
            return True
    prod_host = host_only(vercel_prod_url)
    if prod_host.endswith(".vercel.app"):
        prod_label = prod_host[: -len(".vercel.app")]
        if label.startswith(f"{prod_label}-"):
            suffix = label[len(prod_label) + 1 :]
            if len(suffix) == 9 and suffix.isalnum():
                return True
    if vercel_host.endswith(".vercel.app"):
        vercel_label = vercel_host[: -len(".vercel.app")]
        vercel_parts = vercel_label.rsplit("-", 1)
        if len(vercel_parts) == 2 and len(vercel_parts[1]) == 9 and vercel_parts[1].isalnum():
            if label.startswith(f"{vercel_parts[0]}-"):
                suffix = label[len(vercel_parts[0]) + 1 :]
                if len(suffix) == 9 and suffix.isalnum():
                    return True
    return False


def resolve_public_base_url(settings=None, request_url=""):
    settings = settings or get_settings()
    vercel_prod = normalize_base_url(os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", ""))
    vercel_branch = normalize_base_url(os.environ.get("VERCEL_BRANCH_URL", ""))
    vercel_url = os.environ.get("VERCEL_URL", "")

    configured = normalize_base_url(settings.public_base_url)
    req_url = normalize_base_url(request_url or _request_base_url.get())

    def ephemeral(candidate):
        return is_ephemeral_vercel_host(
            candidate,
            vercel_url=vercel_url,
            vercel_prod_url=vercel_prod,
            vercel_branch_url=vercel_branch,
        )

    if configured and not ephemeral(configured):
        return configured
    if vercel_prod:
        return vercel_prod
    if req_url and not ephemeral(req_url):
        return req_url
    if vercel_branch:
        return vercel_branch
    if req_url:
        return req_url
    return configured


def mail_configured():
    """True when either delivery channel (Resend API or SMTP) is configured."""
    settings = get_settings()
    smtp_ready = bool(settings.smtp_host and settings.smtp_from)
    resend_ready = bool(settings.resend_api_key and settings.resend_from)
    return smtp_ready or resend_ready


def reset_mail_configured():
    return mail_configured()


def split_mime(mime_type):
    maintype, _, subtype = str(mime_type or "application/octet-stream").partition("/")
    return maintype or "application", subtype or "octet-stream"


def deliver(to_address, subject, body, settings=None, attachments=None):
    settings = settings or get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    for attachment in attachments or []:
        maintype, subtype = split_mime(attachment.get("mime"))
        message.add_attachment(
            attachment["content"],
            maintype=maintype,
            subtype=subtype,
            filename=attachment.get("filename") or "attachment",
        )
    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
        server.starttls()
    with server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def deliver_resend(to_address, subject, body, settings=None, attachments=None):
    settings = settings or get_settings()
    payload = {
        "from": settings.resend_from,
        "to": [to_address],
        "subject": subject,
        "text": body,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment.get("filename") or "attachment",
                "content": base64.b64encode(attachment["content"]).decode("ascii"),
            }
            for attachment in attachments
        ]
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json=payload,
        timeout=SMTP_TIMEOUT,
    )
    response.raise_for_status()


def deliver_any(to_address, subject, body, settings=None, attachments=None):
    """Deliver through the Resend API when configured, otherwise through SMTP."""
    settings = settings or get_settings()
    if settings.resend_api_key and settings.resend_from:
        deliver_resend(to_address, subject, body, settings, attachments)
    else:
        deliver(to_address, subject, body, settings, attachments)


def send_mail(to_address, subject, body, attachments=None):
    try:
        deliver_any(to_address, subject, body, attachments=attachments)
    except (httpx.HTTPError, smtplib.SMTPException, OSError):
        raise HTTPException(status_code=502, detail="The email could not be sent. Please try again later.")


def render_message(body):
    settings = get_settings()
    lines = [UNIVERSITY_NAME, "", body.strip()]
    portal_url = resolve_public_base_url(settings)
    if portal_url:
        lines.extend(["", f"Sign in to the scholarship portal: {portal_url}"])
    return "\n".join(lines) + "\n"


def queue_email(user_id, application_id, to_address, subject, body, attachments=None):
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
            "attachments": list(attachments or []),
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
                    deliver_any(
                        item["to"],
                        item["subject"],
                        item["body"],
                        settings,
                        item.get("attachments"),
                    )
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
