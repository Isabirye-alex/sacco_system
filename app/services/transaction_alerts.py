"""
Sends SMS alerts for financial transactions (deposits, withdrawals, loan
disbursements, loan repayments). An SMS failure is always swallowed here -
a failed text message must never roll back or fail the underlying
financial transaction that triggered it. Failures are recorded on the
Notification row itself (status=FAILED, error_message set) so staff can
see and retry from the admin portal's Notifications view.
"""
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import NotificationChannel, NotificationStatus
from app.models.member import Member
from app.services.notification_service import dispatch, queue_notification

logger = logging.getLogger("sacco.transaction_alerts")


def _safe_send(db: Session, member: Member, message: str, event_type: str) -> None:
    if not member or not member.phone_number:
        return
    notification = queue_notification(
        db=db, channel=NotificationChannel.SMS, body=message, member_id=member.id, event_type=event_type
    )
    try:
        dispatch(notification)
        notification.status = NotificationStatus.SENT
        notification.sent_at = datetime.utcnow() # pyright: ignore[reportDeprecated]
    except Exception as exc:  # noqa: BLE001 - SMS must never break the caller's transaction
        notification.status = NotificationStatus.FAILED
        notification.error_message = str(exc)
        logger.warning("SMS alert failed for member %s (%s): %s", member.id, event_type, exc)


def notify_deposit(db: Session, member: Member, account_number: str, amount: Decimal, balance: Decimal) -> None:
    message = (
        f"Dear {member.first_name}, UGX {amount:,.2f} has been deposited to your "
        f"{account_number} account. New balance: UGX {balance:,.2f}. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "savings_deposit")


def notify_withdrawal(db: Session, member: Member, account_number: str, amount: Decimal, balance: Decimal) -> None:
    message = (
        f"Dear {member.first_name}, UGX {amount:,.2f} has been withdrawn from your "
        f"{account_number} account. New balance: UGX {balance:,.2f}. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "savings_withdrawal")


def notify_loan_disbursement(db: Session, member: Member, loan_number: str, amount: Decimal) -> None:
    message = (
        f"Dear {member.first_name}, your loan {loan_number} of UGX {amount:,.2f} has been "
        f"disbursed. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "loan_disbursement")


def notify_loan_repayment(db: Session, member: Member, loan_number: str, amount: Decimal) -> None:
    message = (
        f"Dear {member.first_name}, we received your repayment of UGX {amount:,.2f} on loan "
        f"{loan_number}. Thank you. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "loan_repayment")
