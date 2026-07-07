"""
Mobile Money Module: tracks every MarzPay collection (member -> SACCO) and
disbursement (SACCO -> member) request, independently of whether it has
been confirmed yet. This is the audit trail and the idempotency guard for
webhook processing.
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class MobileMoneyDirection(str, enum.Enum):
    COLLECTION = "collection"      # member pays the SACCO
    DISBURSEMENT = "disbursement"  # SACCO pays the member


class MobileMoneyPurpose(str, enum.Enum):
    SAVINGS_DEPOSIT = "savings_deposit"
    SAVINGS_WITHDRAWAL = "savings_withdrawal"
    LOAN_REPAYMENT = "loan_repayment"
    LOAN_DISBURSEMENT = "loan_disbursement"


class MobileMoneyStatus(str, enum.Enum):
    PENDING = "pending"        # created locally, not yet sent to MarzPay
    PROCESSING = "processing"  # accepted by MarzPay, awaiting customer/provider action
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MobileMoneyTransaction(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "mobile_money_transactions"

    direction: Mapped[MobileMoneyDirection] = mapped_column(Enum(MobileMoneyDirection), nullable=False)
    purpose: Mapped[MobileMoneyPurpose] = mapped_column(Enum(MobileMoneyPurpose), nullable=False)
    status: Mapped[MobileMoneyStatus] = mapped_column(
        Enum(MobileMoneyStatus), default=MobileMoneyStatus.PENDING, nullable=False
    )

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    savings_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("savings_accounts.id"), nullable=True)
    loan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("loan_applications.id"), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # mtn | airtel

    # `id` (our UUID PK) doubles as the `reference` we send to MarzPay, so a
    # MarzPay reference always maps back to exactly one row here.
    marzpay_transaction_uuid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    initiated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_last_callback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    member: Mapped["Member"] = relationship() # type: ignore
