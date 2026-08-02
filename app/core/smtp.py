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
import json
import logging
import smtplib
import socket
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("sacco.smtp")


class SmtpError(Exception):
    pass


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, (smtplib.SMTPException, smtplib.SMTPAuthenticationError)):
        return False
    if isinstance(exc, (socket.error, TimeoutError, ConnectionError, ConnectionRefusedError)):
        return True
    err_str = str(exc).lower()
    return "unreachable" in err_str or "connection" in err_str or "refused" in err_str


def send_via_resend_api(to: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    api_key = getattr(settings, "RESEND_API_KEY", "").strip()
    if not api_key:
        return False
    from_email = settings.SMTP_FROM_EMAIL.strip() or "onboarding@resend.dev"
    from_header = f"{settings.SMTP_FROM_NAME or 'SACCO System'} <{from_email}>" if "@" in from_email and not from_email.endswith("@gmail.com") else "SACCO System <onboarding@resend.dev>"
    req_data = {
        "from": from_header,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html_body:
        req_data["html"] = html_body
    
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(req_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                logger.info("Email sent to %s via Resend HTTP API", to)
                print(f"✅ [HTTP EMAIL SENT] Successfully sent to {to} via Resend HTTPS API", flush=True)
                return True
    except Exception as exc:
        logger.error("Resend API failed: %s", exc)
        print(f"❌ [RESEND API ERROR] {exc}", flush=True)
    return False


def send_via_brevo_api(to: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    api_key = getattr(settings, "BREVO_API_KEY", "").strip()
    if not api_key:
        return False
    from_email = settings.SMTP_FROM_EMAIL.strip() or settings.SMTP_USERNAME.strip() or "notifications@sacco.com"
    req_data = {
        "sender": {"name": settings.SMTP_FROM_NAME or "SACCO System", "email": from_email},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }
    if html_body:
        req_data["htmlContent"] = html_body
    
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(req_data).encode("utf-8"),
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                logger.info("Email sent to %s via Brevo HTTP API", to)
                print(f"✅ [HTTP EMAIL SENT] Successfully sent to {to} via Brevo HTTPS API", flush=True)
                return True
    except Exception as exc:
        logger.error("Brevo API failed: %s", exc)
        print(f"❌ [BREVO API ERROR] {exc}", flush=True)
    return False


def send_email(to: str, subject: str, body: str, html_body: Optional[str] = None) -> None:
    """
    Sends a plain-text (optionally also HTML) email via HTTPS API (Resend/Brevo) or SMTP (Google SMTP & App Password).
    Raises SmtpError on any failure.
    """
    # 1. Try Resend or Brevo HTTP API first if API key configured (bypasses raw socket SMTP blocks)
    if send_via_resend_api(to, subject, body, html_body) or send_via_brevo_api(to, subject, body, html_body):
        return

    if not settings.SMTP_HOST:
        raise SmtpError("SMTP is not configured (SMTP_HOST is empty and no HTTP Email API key set).")

    from_email = settings.SMTP_FROM_EMAIL.strip() or settings.SMTP_USERNAME.strip()
    if not from_email:
        raise SmtpError("SMTP sender email is not configured (set SMTP_FROM_EMAIL or SMTP_USERNAME).")

    from_name = getattr(settings, "SMTP_FROM_NAME", "") or getattr(settings, "SACCO_NAME", "SACCO System")
    
    # Strip spaces from Google App Password if user pasted "xxxx yyyy zzzz wwww"
    password = settings.SMTP_PASSWORD.replace(" ", "") if settings.SMTP_PASSWORD else ""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    use_ssl = getattr(settings, "SMTP_USE_SSL", False) or settings.SMTP_PORT == 465
    use_tls = getattr(settings, "SMTP_USE_TLS", True) or getattr(settings, "SMTP_USER_TLS", True)
    if not use_ssl and settings.SMTP_PORT == 587:
        use_tls = True

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
                if settings.SMTP_USERNAME:
                    client.login(settings.SMTP_USERNAME, password)
                client.send_message(message)
        else:
            try:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
                    if use_tls:
                        client.starttls()
                    if settings.SMTP_USERNAME:
                        client.login(settings.SMTP_USERNAME, password)
                    client.send_message(message)
            except Exception as net_err:
                if _is_network_error(net_err):
                    logger.warning("Port %s unreachable (%s). Retrying via SSL on port 465...", settings.SMTP_PORT, net_err)
                    print(f"⚠️ [SMTP FALLBACK] Port {settings.SMTP_PORT} blocked ({net_err}). Retrying via SSL port 465...", flush=True)
                    with smtplib.SMTP_SSL(settings.SMTP_HOST, 465, timeout=15) as client:
                        if settings.SMTP_USERNAME:
                            client.login(settings.SMTP_USERNAME, password)
                        client.send_message(message)
                else:
                    raise
        logger.info("Email successfully sent to %s via %s", to, settings.SMTP_HOST)
    except smtplib.SMTPAuthenticationError as exc:
        is_google = "gmail.com" in settings.SMTP_HOST.lower()
        hint = (
            " Check your Gmail email and 16-character App Password (requires 2-Step Verification enabled)."
            if is_google else ""
        )
        err_msg = f"SMTP authentication failed ({exc.smtp_code}): {exc.smtp_error.decode('utf-8', errors='ignore') if isinstance(exc.smtp_error, bytes) else exc.smtp_error}.{hint}"
        logger.error("❌ %s", err_msg)
        print(f"❌ [SMTP AUTH ERROR] {err_msg}", flush=True)
        raise SmtpError(err_msg) from exc
    except smtplib.SMTPException as exc:
        err_msg = f"SMTP send failed: {exc}"
        logger.error("❌ %s", err_msg)
        print(f"❌ [SMTP ERROR] {err_msg}", flush=True)
        raise SmtpError(err_msg) from exc
    except OSError as exc:
        err_msg = (
            f"Could not connect to SMTP server ({settings.SMTP_HOST}:{settings.SMTP_PORT}): {exc}. "
            "Render Free instances block raw socket SMTP ports (25, 465, 587). "
            "To send emails on Render Free tier, add RESEND_API_KEY (free 3,000 emails/mo at https://resend.com) "
            "or BREVO_API_KEY in your Render Environment variables to send emails over HTTPS (port 443)."
        )
        logger.error("❌ %s", err_msg)
        print(f"❌ [SMTP CONNECTION ERROR] {err_msg}", flush=True)
        raise SmtpError(err_msg) from exc
    except Exception as exc:
        err_msg = f"Unexpected SMTP error: {exc}"
        logger.error("❌ %s", err_msg, exc_info=True)
        print(f"❌ [SMTP UNEXPECTED ERROR] {err_msg}", flush=True)
        raise SmtpError(err_msg) from exc
    except Exception as exc:
        err_msg = f"Unexpected SMTP error: {exc}"
        logger.error("❌ %s", err_msg, exc_info=True)
        print(f"❌ [SMTP UNEXPECTED ERROR] {err_msg}", flush=True)
        raise SmtpError(err_msg) from exc


def verify_smtp_connection(target_email: str) -> None:
    """
    Sends a test email to verify Google SMTP / App Password credentials.
    """
    send_email(
        to=target_email,
        subject="[SACCO System] Test Email Verification",
        body="This is a test email sent from SACCO System using Google SMTP configuration. Your email settings are working correctly!"
    )

