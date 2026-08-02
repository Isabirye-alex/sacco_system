"""
Notification service: queues notifications and dispatches them through the
configured channel (email/SMS/push). SMS (MarzSMS) and Email (SMTP) are
real integrations; Push remains a logging stub - no push provider has been
requested yet.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import NotificationChannel, NotificationStatus
from app.models.member import Member
from app.models.notification import Notification

logger = logging.getLogger("sacco.notifications")


def queue_notification(
    db: Session,
    channel: NotificationChannel,
    body: str,
    member_id: Optional[str] = None,
    user_id: Optional[str] = None,
    subject: Optional[str] = None,
    event_type: Optional[str] = None,
) -> Notification:
    notification = Notification(
        member_id=member_id,
        user_id=user_id,
        channel=channel,
        subject=subject,
        body=body,
        event_type=event_type,
        status=NotificationStatus.QUEUED,
    )
    db.add(notification)
    db.flush()
    return notification


def _recipient_email(notification: Notification) -> Optional[str]:
    if notification.member:
        if notification.member.email:
            return notification.member.email
        if getattr(notification.member, "user", None) and notification.member.user and notification.member.user.email:
            return notification.member.user.email
    if notification.user:
        return notification.user.email
    return None


def send_member_notifications(
    db: Session,
    member: Member,
    body: str,
    event_type: str,
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Backend-owned notification fanout for core events: sends the same
    message via SMS and email when those recipient details are present.
    Delivery failures are swallowed so the underlying business action is not
    blocked by an outbound channel issue.
    """
    if not member:
        return

    email_subject = subject or event_type.replace("_", " ").title()

    if member.phone_number:
        notification_sms = queue_notification(
            db=db,
            channel=NotificationChannel.SMS,
            body=body,
            member_id=member.id,
            user_id=user_id,
            event_type=event_type,
        )
        try:
            dispatch(notification_sms)
            notification_sms.status = NotificationStatus.SENT
            notification_sms.sent_at = datetime.utcnow()
        except Exception as exc:
            notification_sms.status = NotificationStatus.FAILED
            notification_sms.error_message = str(exc)
            logger.warning("SMS alert failed for member %s (%s): %s", member.id, event_type, exc)

    if member.email:
        notification_email = queue_notification(
            db=db,
            channel=NotificationChannel.EMAIL,
            subject=email_subject,
            body=body,
            member_id=member.id,
            user_id=user_id,
            event_type=event_type,
        )
        try:
            dispatch(notification_email)
            notification_email.status = NotificationStatus.SENT
            notification_email.sent_at = datetime.utcnow()
        except Exception as exc:
            notification_email.status = NotificationStatus.FAILED
            notification_email.error_message = str(exc)
            logger.warning("Email alert failed for member %s (%s): %s", member.id, event_type, exc)


def dispatch(notification: Notification) -> None:
    """
    Sends the notification through its channel. Raises on failure so the
    caller can mark the notification FAILED with the error message -
    callers must never let an SMS/email failure block or roll back the
    financial transaction that triggered it.
    """
    if notification.channel == NotificationChannel.SMS:
        phone = notification.member.phone_number if notification.member else None
        if not phone:
            raise ValueError("No phone number on file for this notification's recipient.")
        from app.integrations.marzsms import send_sms  # local import: keeps this optional at startup

        send_sms(recipient=phone, message=notification.body)

    elif notification.channel == NotificationChannel.EMAIL:
        email = _recipient_email(notification)
        if not email:
            raise ValueError("No email address on file for this notification's recipient.")
        from app.integrations.smtp_client import send_email  # local import: keeps this optional at startup

        send_email(to=email, subject=notification.subject or "Notification", body=notification.body)

    elif notification.channel == NotificationChannel.PUSH:
        logger.info("Sending PUSH to user=%s (no push provider configured yet - logging only)", notification.user_id)
