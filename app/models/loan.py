"""
Credit / Loan Management Module: products, applications, guarantors,
repayment schedules, disbursements, and collateral.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import DisbursementChannel, GuarantorStatus, LoanStatus
from app.models.base import TimestampMixin, UUIDPKMixin


class LoanProduct(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "loan_products"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    interest_rate_annual: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    max_repayment_months: Mapped[int] = mapped_column(nullable=False)
    grace_period_days: Mapped[int] = mapped_column(default=0)
    penalty_rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    requires_guarantors: Mapped[bool] = mapped_column(Boolean, default=True)
    min_guarantors: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    applications: Mapped[list["LoanApplication"]] = relationship(back_populates="product")


class LoanApplication(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "loan_applications"

    loan_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("loan_products.id"), nullable=False)
    amount_requested: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_approved: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    repayment_months: Mapped[int] = mapped_column(nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[LoanStatus] = mapped_column(Enum(LoanStatus), default=LoanStatus.PENDING, nullable=False)

    is_non_member_applicant: Mapped[bool] = mapped_column(Boolean, default=False)  # "loan seeking" for non-members

    credit_score: Mapped[Optional[int]] = mapped_column(nullable=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    disbursement_channel: Mapped[Optional[DisbursementChannel]] = mapped_column(
        Enum(DisbursementChannel), nullable=True
    )
    disbursed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    disbursement_savings_account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("savings_accounts.id"), nullable=True
    )

    member: Mapped["Member"] = relationship(back_populates="loan_applications", foreign_keys=[member_id])
    product: Mapped["LoanProduct"] = relationship(back_populates="applications")
    guarantors: Mapped[list["Guarantor"]] = relationship(back_populates="loan", cascade="all, delete-orphan")
    schedule: Mapped[list["LoanRepaymentSchedule"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", order_by="LoanRepaymentSchedule.installment_number"
    )
    transactions: Mapped[list["LoanTransaction"]] = relationship(back_populates="loan", cascade="all, delete-orphan")
    collaterals: Mapped[list["Collateral"]] = relationship(back_populates="loan", cascade="all, delete-orphan")


class Guarantor(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "guarantors"

    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_applications.id"), nullable=False)
    guarantor_member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount_guaranteed: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[GuarantorStatus] = mapped_column(Enum(GuarantorStatus), default=GuarantorStatus.PENDING)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    loan: Mapped["LoanApplication"] = relationship(back_populates="guarantors")


class LoanRepaymentSchedule(Base, UUIDPKMixin):
    __tablename__ = "loan_repayment_schedules"

    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_applications.id"), nullable=False)
    installment_number: Mapped[int] = mapped_column(nullable=False)
    due_date: Mapped[date] = mapped_column(nullable=False)
    principal_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interest_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    penalty_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    loan: Mapped["LoanApplication"] = relationship(back_populates="schedule")


class LoanTransaction(Base, UUIDPKMixin):
    __tablename__ = "loan_transactions"

    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_applications.id"), nullable=False)
    txn_type: Mapped[str] = mapped_column(String(30), nullable=False)  # disbursement, repayment, penalty, writeoff
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    performed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    loan: Mapped["LoanApplication"] = relationship(back_populates="transactions")


class Collateral(Base, UUIDPKMixin):
    __tablename__ = "collaterals"

    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_applications.id"), nullable=False)
    collateral_type: Mapped[str] = mapped_column(String(50), nullable=False)  # logbook, land_title, equipment
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    document_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    loan: Mapped["LoanApplication"] = relationship(back_populates="collaterals")
