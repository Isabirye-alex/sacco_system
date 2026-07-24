"""
System Administration Module: platform users, roles, and audit logging.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import UserRole
from app.models.base import TimestampMixin, UUIDPKMixin


import secrets
from sqlalchemy.orm import Session


def generate_8char_code() -> str:
    return secrets.token_hex(4).upper()


def generate_unique_referral_code(db: Session) -> str:
    for _ in range(10):
        code = generate_8char_code()
        if not db.query(User).filter(User.referral_code == code).first():
            return code
    return generate_8char_code()


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    referral_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False, default=generate_8char_code)

    # Optional link to a member profile if this user is a SACCO member
    member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)
    member: Mapped[Optional["Member"]] = relationship(back_populates="user_account") # type: ignore

    # Two-Factor Authentication (2FA) fields
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AuditLog(Base, UUIDPKMixin):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False) # type: ignore

    actor: Mapped[Optional["User"]] = relationship(foreign_keys=[actor_user_id])
