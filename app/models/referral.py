"""
Referral Module: a member invites a non-member to join the SACCO (via SMS
or email) and earns a commission once that person actually becomes a
member. Deliberately kept separate from self-service registration - this
system doesn't have a public sign-up flow, so "the non-member registering"
means staff creating a Member record for them and citing the referral code
(see MemberCreate.referral_code in app/schemas/member.py), not an
automated online registration.
"""
import enum
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import NotificationChannel
from app.models.base import TimestampMixin, UUIDPKMixin


class ReferralStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    INVALID = "invalid"
    # Legacy statuses
    INVITED = "invited"
    REGISTERED = "registered"
    COMMISSION_PAID = "commission_paid"
    EXPIRED = "expired"


def generate_referral_code() -> str:
    return secrets.token_hex(4).upper()  # e.g. "A1B2C3D4"


class Referral(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_user_id", "tier", name="uq_referral_user_tier"),
    )

    referrer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    referred_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ReferralStatus] = mapped_column(Enum(ReferralStatus), default=ReferralStatus.PENDING, nullable=False)

    # Legacy & supplementary fields
    referral_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True, index=True, nullable=True, default=generate_referral_code)
    referrer_member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)

    referred_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    referred_contact: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)  # phone or email
    channel: Mapped[Optional[NotificationChannel]] = mapped_column(Enum(NotificationChannel), nullable=True)

    invited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    registered_member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    commission_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    commission_paid_savings_account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("savings_accounts.id"), nullable=True
    )
    commission_paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    commission_paid_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    referrer_user: Mapped["User"] = relationship(foreign_keys=[referrer_id])
    referred_user: Mapped["User"] = relationship(foreign_keys=[referred_user_id])
    referrer: Mapped[Optional["Member"]] = relationship(foreign_keys=[referrer_member_id])
    registered_member: Mapped[Optional["Member"]] = relationship(foreign_keys=[registered_member_id])

