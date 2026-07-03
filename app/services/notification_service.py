"""
Notification service: queues notifications and dispatches them through the
configured channel (email/SMS/push). Actual provider integration (SMTP,
Africa's Talking, FCM) is stubbed behind a single send() call so the
providers can be swapped in without touching calling code.
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


def dispatch(notification: Notification) -> None:
    """
    Stub dispatcher. Replace the branches below with real SMTP / Africa's
    Talking / FCM calls. Any exception should be caught and stored on
    notification.error_message with status=FAILED by the caller.
    """
    if notification.channel == NotificationChannel.EMAIL:
        logger.info("Sending EMAIL to member=%s subject=%s", notification.member_id, notification.subject)
    elif notification.channel == NotificationChannel.SMS:
        logger.info("Sending SMS to member=%s", notification.member_id)
    elif notification.channel == NotificationChannel.PUSH:
        logger.info("Sending PUSH to user=%s", notification.user_id)
