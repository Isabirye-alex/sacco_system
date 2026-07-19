"""
Notification service: queues notifications and dispatches them through the
configured channel (email/SMS/push). SMS (MarzSMS) and Email (SMTP) are
real integrations; Push remains a logging stub - no push provider has been
requested yet.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import NotificationChannel, NotificationStatus
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
    if notification.member and notification.member.email:
        return notification.member.email
    if notification.user:
        return notification.user.email
    return None


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
