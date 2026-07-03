"""
HR & Payroll Deductions Module: employer profiles and deduction reconciliation.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import DeductionStatus
from app.models.base import TimestampMixin, UUIDPKMixin


class Employer(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "employers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    payroll_files: Mapped[list["PayrollFile"]] = relationship(back_populates="employer")


class PayrollFile(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payroll_files"

    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2026-06"
    file_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    uploaded_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    employer: Mapped["Employer"] = relationship(back_populates="payroll_files")
    deductions: Mapped[list["PayrollDeduction"]] = relationship(
        back_populates="payroll_file", cascade="all, delete-orphan"
    )


class PayrollDeduction(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payroll_deductions"

    payroll_file_id: Mapped[str] = mapped_column(ForeignKey("payroll_files.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    loan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("loan_applications.id"), nullable=True)
    savings_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("savings_accounts.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[DeductionStatus] = mapped_column(Enum(DeductionStatus), default=DeductionStatus.PENDING)
    exception_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    payroll_file: Mapped["PayrollFile"] = relationship(back_populates="deductions")
