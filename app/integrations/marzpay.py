"""
Thin client for the MarzPay API (https://wallet.wearemarz.com/documentation).

Covers what the SACCO system needs:
- collect_money(): request a mobile money collection (member -> SACCO), used
  for member-initiated savings deposits and loan repayments.
- send_money(): disburse a mobile money payment (SACCO -> member), used for
  mobile-money loan disbursements.
- get_collection() / get_disbursement(): server-to-server status lookup,
  used to independently verify a webhook callback rather than trusting the
  callback body (MarzPay does not document a webhook signature scheme).

Auth: MarzPay uses HTTP Basic auth with your API key as the username and
API secret as the password (`Authorization: Basic base64(key:secret)`).
"""
import base64
import logging
from decimal import Decimal
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("sacco.marzpay")


class MarzPayError(Exception):
    """Raised when MarzPay returns an error or an unexpected response shape."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None): # type: ignore
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload # type: ignore


def _auth_header() -> dict: # type: ignore
    if not settings.MARZPAY_API_KEY or not settings.MARZPAY_API_SECRET:
        raise MarzPayError("MarzPay API credentials are not configured (MARZPAY_API_KEY / MARZPAY_API_SECRET).")
    token = base64.b64encode(f"{settings.MARZPAY_API_KEY}:{settings.MARZPAY_API_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}"} # type: ignore


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.MARZPAY_BASE_URL, timeout=30.0, headers=_auth_header()) # type: ignore


def _normalize_phone(phone_number: str) -> str:
    """MarzPay expects +256XXXXXXXXX. Accepts local (07..) or already-international input."""
    digits = "".join(ch for ch in phone_number if ch.isdigit() or ch == "+")
    if digits.startswith("+256"):
        return digits
    if digits.startswith("256"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+256{digits[1:]}"
    raise MarzPayError(f"Could not normalize phone number '{phone_number}' to +256 format.")


def collect_money( # type: ignore
    amount: Decimal,
    phone_number: str,
    reference: str,
    description: str,
    callback_url: str,
) -> dict: # type: ignore
    """
    Requests a mobile money collection (customer pays the SACCO).
    `reference` must be a unique UUID string - use MobileMoneyTransaction.id.
    Raises MarzPayError on non-2xx or malformed responses.
    """
    payload = { # type: ignore
        "amount": int(amount),
        "phone_number": _normalize_phone(phone_number),
        "country": "UG",
        "reference": reference,
        "description": description[:255],
        "callback_url": callback_url,
    }
    with _client() as client:
        try:
            resp = client.post("/collect-money", json=payload) # type: ignore
        except httpx.HTTPError as exc:
            raise MarzPayError(f"Network error calling MarzPay collect-money: {exc}") from exc

    data = _parse_response(resp) # type: ignore
    return data # type: ignore


def send_money( # type: ignore
    amount: Decimal,
    phone_number: str,
    reference: str,
    description: str,
    callback_url: str,
) -> dict: # type: ignore
    """
    Sends a mobile money disbursement (SACCO pays the customer).
    `reference` must be a unique UUID string - use MobileMoneyTransaction.id.
    """
    payload = { # type: ignore
        "amount": int(amount),
        "phone_number": _normalize_phone(phone_number),
        "country": "UG",
        "reference": reference,
        "description": description[:255],
        "callback_url": callback_url,
    }
    with _client() as client:
        try:
            resp = client.post("/send-money", json=payload) # type: ignore
        except httpx.HTTPError as exc:
            raise MarzPayError(f"Network error calling MarzPay send-money: {exc}") from exc

    data = _parse_response(resp) # type: ignore
    return data # type: ignore


def get_collection(uuid: str) -> dict: # type: ignore
    """Server-to-server status check for a collection, by MarzPay transaction uuid."""
    with _client() as client:
        try:
            resp = client.get(f"/collect-money/{uuid}")
        except httpx.HTTPError as exc:
            raise MarzPayError(f"Network error calling MarzPay get-collection: {exc}") from exc
    return _parse_response(resp) # type: ignore


def get_disbursement(uuid: str) -> dict: # type: ignore
    """Server-to-server status check for a disbursement, by MarzPay transaction uuid."""
    with _client() as client:
        try:
            resp = client.get(f"/send-money/{uuid}")
        except httpx.HTTPError as exc:
            raise MarzPayError(f"Network error calling MarzPay get-disbursement: {exc}") from exc
    return _parse_response(resp) # type: ignore


def _parse_response(resp: httpx.Response) -> dict: # type: ignore
    try:
        body = resp.json()
    except ValueError as exc:
        raise MarzPayError(f"MarzPay returned a non-JSON response (HTTP {resp.status_code}).", resp.status_code) from exc

    if resp.status_code >= 400 or body.get("status") == "error":
        raise MarzPayError(
            body.get("message", f"MarzPay request failed with HTTP {resp.status_code}."),
            resp.status_code,
            body,
        )
    return body
