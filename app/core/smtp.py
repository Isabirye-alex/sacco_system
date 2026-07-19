"""
Plain SMTP email sending using Python's standard library (smtplib +
email.message) - no third-party email API, since you said "SMTP, I'll
provide host" rather than a specific provider like SendGrid. Works with
Gmail, Outlook/Microsoft 365, or any other SMTP-speaking provider; you
just need the host, port, username, and password (for Gmail/Microsoft,
that's almost always an app-specific password, not your normal login
password, since both block plain SMTP auth with regular passwords by
default now).
"""
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("sacco.smtp")


class SmtpError(Exception):
    pass


def send_email(to: str, subject: str, body: str, html_body: Optional[str] = None) -> None:
    """
    Sends a plain-text (optionally also HTML) email. Raises SmtpError on
    any failure - callers must catch this themselves; see
    app/services/notification_service.py for how the rest of the system
    treats an email failure the same way it treats an SMS failure (logged,
    never allowed to break the transaction that triggered it).
    """
    if not settings.SMTP_HOST:
        raise SmtpError("SMTP is not configured (SMTP_HOST is empty).")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
            if settings.SMTP_USE_TLS:
                client.starttls()
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            client.send_message(message)
    except smtplib.SMTPException as exc:
        raise SmtpError(f"SMTP send failed: {exc}") from exc
    except OSError as exc:
        raise SmtpError(f"Could not connect to SMTP server: {exc}") from exc
