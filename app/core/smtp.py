"""Google Apps Script-backed email transport for SACCO notifications."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("sacco.smtp")


class SmtpError(Exception):
    pass


def _is_explicit_success_payload(response_text: str) -> bool:
    normalized = response_text.strip().lower()
    if not normalized:
        return False
    if "<html" in normalized or "<!doctype html" in normalized:
        return False

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        success_markers = ("success", "sent", "queued", "ok")
        return any(marker in normalized for marker in success_markers)

    if isinstance(payload, dict):
        result = payload.get("result")
        sent = payload.get("sent")
        if result == "success":
            return True
        if sent is True:
            return True
        return False

    return False


def send_via_gmail_webhook(to: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    webhook_url = getattr(settings, "GMAIL_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    clean_html = html_body or body
    if len(clean_html) > 4000:
        clean_html = clean_html[:4000]

    query_params = {
        "to": to,
        "subject": subject,
        "body": body,
        "html_body": clean_html
    }

    delimiter = "&" if "?" in webhook_url else "?"
    full_url = f"{webhook_url}{delimiter}{urllib.parse.urlencode(query_params)}"

    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        method="GET"
    )
    try:
        # Increase timeout to 35s so Google Apps Script mail dispatch can finish cleanly
        with urllib.request.urlopen(req, timeout=35) as resp:
            resp_str = resp.read().decode("utf-8", errors="ignore")
            if resp.status in (200, 201) and _is_explicit_success_payload(resp_str):
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
    except TimeoutError as exc:
        logger.error("Gmail Webhook timed out: %s", exc)
        print(f"❌ [GMAIL WEBHOOK TIMEOUT] {exc}", flush=True)
        raise SmtpError("Google Webhook connection timed out. Retrying recommended.") from exc
    except Exception as exc:
        logger.error("Gmail Webhook failed: %s", exc)
        print(f"❌ [GMAIL WEBHOOK ERROR] {exc}", flush=True)
        raise SmtpError(f"Google Webhook Error: {exc}") from exc
    return False


from app.core.email_template import build_sacco_email_html


def send_email(to: str, subject: str, body: str, html_body: Optional[str] = None) -> None:
    """
    Sends email exclusively through the configured Google Apps Script webhook.
    Raises SmtpError on any failure.
    """
    if not html_body:
        html_body = build_sacco_email_html(subject, body, getattr(settings, "SMTP_FROM_NAME", "") or getattr(settings, "SACCO_NAME", "SACCO PRO"))

    webhook_url = getattr(settings, "GMAIL_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SmtpError(
            "Google Apps Script webhook is not configured. Set GMAIL_WEBHOOK_URL to the deployed Apps Script Web App URL."
        )

    if send_via_gmail_webhook(to, subject, body, html_body):
        return

    raise SmtpError(
        "Google Apps Script webhook is configured but did not return an explicit delivery confirmation. "
        "Make sure the deployed Web App returns JSON like {\"result\": \"success\"} and that GMAIL_WEBHOOK_URL points to the deployed URL."
    )


def verify_smtp_connection(target_email: str) -> None:
    """Sends a test email through the configured Google Apps Script webhook."""
    send_email(
        to=target_email,
        subject="[SACCO System] Test Email Verification",
        body="This is a test email sent from SACCO System using Google Apps Script webhook configuration. Your email settings are working correctly!",
    )

