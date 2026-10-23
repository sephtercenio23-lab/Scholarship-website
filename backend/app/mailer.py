import smtplib
from email.message import EmailMessage

from fastapi import HTTPException

from .config import get_settings


def mail_configured():
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def send_mail(to_address, subject, body):
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()
        with server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError):
        raise HTTPException(status_code=502, detail="The email could not be sent. Please try again later.")
