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


class SmartRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Preserve POST method and payload across Google Apps Script 302 redirects
        return urllib.request.Request(
            newurl,
            data=req.data,
            headers=dict(req.headers),
            method=req.get_method()
        )


def send_via_gmail_webhook(to: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    webhook_url = getattr(settings, "GMAIL_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False
    
    req_data = {
        "to": to,
        "subject": subject,
        "body": body,
        "html_body": html_body or body
    }
    
    opener = urllib.request.build_opener(SmartRedirectHandler())
    json_bytes = json.dumps(req_data).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=json_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with opener.open(req, timeout=15) as resp:
            resp_str = resp.read().decode("utf-8", errors="ignore")
            if resp.status in (200, 201) or "success" in resp_str.lower():
                logger.info("Email sent to %s via Google Apps Script Webhook", to)
                print(f"✅ [HTTP EMAIL SENT] Successfully sent to {to} via Google Apps Script Webhook", flush=True)
                return True
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        logger.error("Gmail Webhook HTTP %s: %s | Response: %s", exc.code, exc.reason, err_body)
        print(f"❌ [GMAIL WEBHOOK ERROR {exc.code}] {exc.reason} - Details: {err_body}", flush=True)
        if exc.code == 403:
            raise SmtpError(
                "Google Apps Script returned 403 Forbidden. "
                "In Google Apps Script, click Deploy -> Manage deployments -> Edit (pencil) -> Change 'Who has access' to 'Anyone' -> Deploy a New Version."
            ) from exc
        raise SmtpError(f"Google Webhook Error ({exc.code}): {err_body or exc.reason}") from exc
    except Exception as exc:
        logger.error("Gmail Webhook failed: %s", exc)
        print(f"❌ [GMAIL WEBHOOK ERROR] {exc}", flush=True)
        raise SmtpError(f"Google Webhook Error: {exc}") from exc
    return False


from app.core.email_template import build_sacco_email_html


def send_email(to: str, subject: str, body: str, html_body: Optional[str] = None) -> None:
    """
    Sends a plain-text (optionally also HTML) email via HTTPS API (Google Apps Script Webhook) or SMTP fallback.
    Raises SmtpError on any failure.
    """
    if not html_body:
        html_body = build_sacco_email_html(subject, body, getattr(settings, "SMTP_FROM_NAME", "") or getattr(settings, "SACCO_NAME", "SACCO PRO"))

    # 1. Try Google Apps Script Webhook first (bypasses raw socket SMTP blocks on Render)
    if send_via_gmail_webhook(to, subject, body, html_body):
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

