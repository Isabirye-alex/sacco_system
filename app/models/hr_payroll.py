"""
Staff Payroll Module: distinct from the existing app/models/payroll.py
(Employer/PayrollDeduction), which handles reconciling deductions that an
EXTERNAL employer submits on behalf of THEIR staff who happen to be SACCO
members. This module is the SACCO's OWN staff payroll - gross pay, PAYE,
NSSF, and net pay for people the SACCO itself employs.
"""
import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class PayrollRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSED = "processed"


class PayslipPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"


class Employee(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "employees"

    employee_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    national_id: Mapped[str] = mapped_column(String(50), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    position: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    employment_date: Mapped[date] = mapped_column(Date, nullable=False)

    basic_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allowances: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    tin: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # Tax Identification Number
    nssf_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    mobile_money_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    bank_account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Optional links: a staff member may also be a SACCO member (so their
    # own loan repayment can be deducted from payroll) and/or hold a
    # system login (User) - neither is required.
    member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    member: Mapped[Optional["Member"]] = relationship()
    user: Mapped[Optional["User"]] = relationship()

    @property
    def gross_pay(self) -> Decimal:
        return self.basic_salary + self.allowances


class PayrollRun(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payroll_runs"

    period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2026-07"
    status: Mapped[PayrollRunStatus] = mapped_column(Enum(PayrollRunStatus), default=PayrollRunStatus.DRAFT)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    processed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    total_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_paye: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_nssf_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_nssf_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_loan_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    payslips: Mapped[list["Payslip"]] = relationship(back_populates="payroll_run", cascade="all, delete-orphan")


class Payslip(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payslips"

    payroll_run_id: Mapped[str] = mapped_column(ForeignKey("payroll_runs.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)

    basic_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allowances: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    paye_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nssf_employee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    nssf_employer_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    loan_deduction_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    loan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("loan_applications.id"), nullable=True)

    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    payment_status: Mapped[PayslipPaymentStatus] = mapped_column(
        Enum(PayslipPaymentStatus), default=PayslipPaymentStatus.PENDING
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    paid_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    payroll_run: Mapped["PayrollRun"] = relationship(back_populates="payslips")
    employee: Mapped["Employee"] = relationship()
