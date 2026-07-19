from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.hr_payroll import PayrollRunStatus, PayslipPaymentStatus
from app.schemas.common import ORMBase


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=2)
    national_id: str
    phone_number: str
    email: Optional[EmailStr] = None
    position: str
    department: Optional[str] = None
    employment_date: date
    basic_salary: Decimal = Field(gt=0)
    allowances: Decimal = Decimal("0")
    tin: Optional[str] = None
    nssf_number: Optional[str] = None
    mobile_money_number: Optional[str] = None
    bank_account_number: Optional[str] = None
    member_id: Optional[str] = None  # link if this employee is also a SACCO member
    user_id: Optional[str] = None  # link if this employee has a system login


class EmployeeUpdate(BaseModel):
    basic_salary: Optional[Decimal] = None
    allowances: Optional[Decimal] = None
    position: Optional[str] = None
    department: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile_money_number: Optional[str] = None
    bank_account_number: Optional[str] = None
    is_active: Optional[bool] = None


class EmployeeRead(ORMBase):
    id: str
    employee_number: str
    full_name: str
    national_id: str
    phone_number: str
    email: Optional[EmailStr] = None
    position: str
    department: Optional[str] = None
    employment_date: date
    basic_salary: Decimal
    allowances: Decimal
    tin: Optional[str] = None
    nssf_number: Optional[str] = None
    mobile_money_number: Optional[str] = None
    bank_account_number: Optional[str] = None
    member_id: Optional[str] = None
    user_id: Optional[str] = None
    is_active: bool


class PayrollRunCreate(BaseModel):
    period: str  # e.g. "2026-07"
    employee_ids: list[str]  # who to include in this run


class PayslipLineOverride(BaseModel):
    employee_id: str
    loan_deduction_amount: Optional[Decimal] = None  # override the auto-suggested amount; 0 to skip deduction


class ProcessPayrollRequest(BaseModel):
    overrides: list[PayslipLineOverride] = []


class PayslipRead(ORMBase):
    id: str
    payroll_run_id: str
    employee_id: str
    basic_salary: Decimal
    allowances: Decimal
    gross_pay: Decimal
    paye_amount: Decimal
    nssf_employee_amount: Decimal
    nssf_employer_amount: Decimal
    loan_deduction_amount: Decimal
    loan_id: Optional[str] = None
    net_pay: Decimal
    payment_status: PayslipPaymentStatus
    paid_at: Optional[datetime] = None


class PayrollRunRead(ORMBase):
    id: str
    period: str
    status: PayrollRunStatus
    processed_at: Optional[datetime] = None
    total_gross: Decimal
    total_paye: Decimal
    total_nssf_employee: Decimal
    total_nssf_employer: Decimal
    total_loan_deductions: Decimal
    total_net: Decimal
    created_at: datetime


class PayrollRunDetailRead(PayrollRunRead):
    payslips: list[PayslipRead] = []
