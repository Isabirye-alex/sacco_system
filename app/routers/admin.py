"""
System Administration Module endpoints: platform user management and
audit log inspection. All endpoints require ADMIN role.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_active_admin
from app.models.user import AuditLog, User
from app.schemas.user import AuditLogRead, UserRead, UserUpdate
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/admin", tags=["System Administration"])


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_admin)):
    return db.query(User).all()


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="user.update", entity_type="User",
        entity_id=user.id, details=f"Updated fields: {', '.join(changes.keys())} on {user.email}",
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
    entity_type: str | None = None,
    limit: int = 100,
):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [AuditLogRead.from_orm_with_actor(log) for log in logs] # type: ignore
