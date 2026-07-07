"""
Client for the MarzSMS API (https://sms.wearemarz.com/docs) - verified
against their published documentation.

Much simpler than MarzPay's payment APIs: a single synchronous POST that
returns the send result immediately - no webhook needed, since SMS delivery
status isn't part of what this system needs to react to (unlike a mobile
money payment, a failed SMS shouldn't roll back or block anything financial).

Auth: HTTP Basic, API key as username, API secret as password (a separate
MarzSMS account/keys from your MarzPay wallet credentials).
"""
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("sacco.marzsms")


class MarzSmsError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None): # type: ignore
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload # type: ignore


def _normalize_phone(phone_number: str) -> str:
    """MarzSMS accepts +256XXXXXXXXX or 256XXXXXXXXX; we normalize local 07... input too."""
    digits = "".join(ch for ch in phone_number if ch.isdigit() or ch == "+")
    if digits.startswith("+256"):
        return digits
    if digits.startswith("256"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+256{digits[1:]}"
    raise MarzSmsError(f"Could not normalize phone number '{phone_number}' to +256 format.")


def send_sms(recipient: str, message: str) -> dict: # type: ignore
    """
    Sends a single SMS via MarzSMS. Raises MarzSmsError on any failure
    (bad credentials, insufficient balance, invalid number, server error).
    Callers must catch this - an SMS failure must never break the
    underlying financial transaction it's reporting on. See
    app/services/transaction_alerts.py for the safe wrapper used elsewhere.

    Message is capped at 320 chars (2 SMS units) per MarzSMS's documented limit.
    """
    if not settings.MARZSMS_API_KEY or not settings.MARZSMS_API_SECRET:
        raise MarzSmsError("MarzSMS API credentials are not configured (MARZSMS_API_KEY / MARZSMS_API_SECRET).")

    payload = {"recipient": _normalize_phone(recipient), "message": message[:320]}

    try:
        resp = httpx.post(
            f"{settings.MARZSMS_BASE_URL}/sms/send",
            json=payload,
            auth=(settings.MARZSMS_API_KEY, settings.MARZSMS_API_SECRET),
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise MarzSmsError(f"Network error calling MarzSMS: {exc}") from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise MarzSmsError(f"MarzSMS returned a non-JSON response (HTTP {resp.status_code}).") from exc

    # Documented error shapes: 401 invalid_credentials, 402 insufficient_balance,
    # 422 invalid_phone_numbers / validation, 500 send_failed.
    if resp.status_code >= 400 or not body.get("success"):
        raise MarzSmsError(
            body.get("message", f"MarzSMS request failed with HTTP {resp.status_code}."),
            resp.status_code,
            body,
        )
    return body


def get_balance() -> dict: # type: ignore
    """GET /api/v1/account/balance - useful for a low-balance warning in the admin portal."""
    if not settings.MARZSMS_API_KEY or not settings.MARZSMS_API_SECRET:
        raise MarzSmsError("MarzSMS API credentials are not configured.")
    try:
        resp = httpx.get(
            f"{settings.MARZSMS_BASE_URL}/account/balance",
            auth=(settings.MARZSMS_API_KEY, settings.MARZSMS_API_SECRET),
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise MarzSmsError(f"Network error calling MarzSMS: {exc}") from exc
    body = resp.json()
    if resp.status_code >= 400 or not body.get("success"):
        raise MarzSmsError(body.get("message", "Failed to fetch MarzSMS balance."), resp.status_code, body)
    return body["data"]
