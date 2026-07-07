"""
Notification Module endpoints: queue and send member/staff notifications.
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.enums import NotificationStatus, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.notification import Notification
from app.models.user import User
from app.schemas.misc import NotificationCreate, NotificationRead
from app.services.notification_service import dispatch, queue_notification

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


def _send_in_background(notification_id: str):
    """
    Uses its own DB session (rather than the request-scoped one, which is
    closed by the time this background task runs) to avoid using a session
    after it has been returned to the pool.
    """
    db = SessionLocal()
    try:
        notification = db.get(Notification, notification_id)
        if not notification:
            return
        try:
            dispatch(notification)
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.utcnow() # type: ignore
        except Exception as exc:  # pragma: no cover - defensive
            notification.status = NotificationStatus.FAILED
            notification.error_message = str(exc)
        db.commit()
    finally:
        db.close()


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
def send_notification(
    payload: NotificationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)), # type: ignore
):
    notification = queue_notification(
        db=db,
        channel=payload.channel,
        body=payload.body,
        member_id=payload.member_id,
        user_id=payload.user_id,
        subject=payload.subject,
        event_type=payload.event_type,
    )
    db.commit()
    db.refresh(notification)
    background_tasks.add_task(_send_in_background, notification.id)
    return notification


@router.get("/members/{member_id}", response_model=list[NotificationRead])
def list_member_notifications(member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Notification).filter(Notification.member_id == member_id).order_by(Notification.created_at.desc()).all()
