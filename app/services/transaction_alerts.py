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
        notification.sent_at = datetime.utcnow()
    except Exception as exc:  # noqa: BLE001 - SMS must never break the caller's transaction
        notification.status = NotificationStatus.FAILED
        notification.error_message = str(exc)
        logger.warning("SMS alert failed for member %s (%s): %s", member.id, event_type, exc)


def mask_account_number(account_number: str) -> str:
    """
    Masks savings account numbers for privacy in SMS/notification messages.
    e.g., "SAV-0001-2026" -> "SAV-****2026"
          "1002345678" -> "****5678"
          "SA-1002" -> "****"
    """
    if not account_number:
        return ""
    clean = account_number.strip()
    if len(clean) <= 4:
        return "****"
    if "-" in clean:
        parts = clean.split("-")
        prefix = parts[0]
        rest = "".join(parts[1:])
        if len(rest) > 4:
            return f"{prefix}-****{rest[-4:]}"
        return f"{prefix}-****"
    return f"****{clean[-4:]}"


def notify_deposit(db: Session, member: Member, account_number: str, amount: Decimal, balance: Decimal) -> None:
    masked_acc = mask_account_number(account_number)
    message = (
        f"Dear {member.first_name}, UGX {amount:,.2f} has been deposited to your "
        f"{masked_acc} account. New balance: UGX {balance:,.2f}. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "savings_deposit")


def notify_withdrawal(db: Session, member: Member, account_number: str, amount: Decimal, balance: Decimal) -> None:
    masked_acc = mask_account_number(account_number)
    message = (
        f"Dear {member.first_name}, UGX {amount:,.2f} has been withdrawn from your "
        f"{masked_acc} account. New balance: UGX {balance:,.2f}. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "savings_withdrawal")


def notify_new_member(db: Session, member: Member) -> None:
    message = (
        f"Welcome to {settings.SACCO_NAME}, {member.first_name}! Your membership account has been "
        f"successfully created. Member No: {member.member_number}. Thank you for joining us."
    )
    _safe_send(db, member, message, "new_member_created")


def notify_savings_account_opened(db: Session, member: Member, account_number: str, product_name: str) -> None:
    masked_acc = mask_account_number(account_number)
    message = (
        f"Dear {member.first_name}, your new {product_name} savings account ({masked_acc}) has been "
        f"successfully created. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "savings_account_opened")


def notify_member_status_change(db: Session, member: Member, new_status: str) -> None:
    message = (
        f"Dear {member.first_name}, your membership status with {settings.SACCO_NAME} is now "
        f"{new_status.title()}."
    )
    _safe_send(db, member, message, "member_status_changed")


def notify_loan_decision(db: Session, member: Member, loan_number: str, decision: str, amount: Decimal) -> None:
    message = (
        f"Dear {member.first_name}, your loan application {loan_number} for UGX {amount:,.2f} has been "
        f"{decision.lower()}. - {settings.SACCO_NAME}"
    )
    _safe_send(db, member, message, "loan_decision")


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


def notify_referral_commission(db: Session, member: Member, amount: Decimal, referred_name: str) -> None:
    message = (
        f"Dear {member.first_name}, you've earned a UGX {amount:,.2f} referral commission for inviting "
        f"{referred_name} to join {settings.SACCO_NAME}. It's been credited to your savings account."
    )
    _safe_send(db, member, message, "referral_commission")



def send_referral_invite(
    referred_contact: str, referred_name: str, referrer_name: str, referral_code: str, channel: NotificationChannel
) -> None:
    """
    Sends the invite directly to the referred_contact (a non-member - no
    Member row exists for them yet), so this bypasses the member-bound
    queue_notification/dispatch pattern used everywhere else and calls the
    provider client directly. Raises on failure - the referrals router
    catches it and marks the Referral with an error rather than pretending
    the invite went out.
    """
    message = (
        f"Hi {referred_name}, {referrer_name} thinks you'd be a great fit for {settings.SACCO_NAME}! "
        f"Visit our office and mention code {referral_code} to join."
    )
    if channel == NotificationChannel.SMS:
        from app.integrations.marzsms import send_sms

        send_sms(recipient=referred_contact, message=message)
    elif channel == NotificationChannel.EMAIL:
        from app.integrations.smtp_client import send_email

        send_email(to=referred_contact, subject=f"You're invited to join {settings.SACCO_NAME}", body=message)
    else:
        raise ValueError(f"Referral invites only support SMS or email, got '{channel}'.")
