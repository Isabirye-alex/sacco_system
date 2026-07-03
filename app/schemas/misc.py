from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import (
    DeductionStatus,
    NotificationChannel,
    NotificationStatus,
    RiskFlagStatus,
    RiskFlagType,
    ShareTxnType,
)
from app.schemas.common import ORMBase


# ---- Accounting ----
class ChartOfAccountCreate(BaseModel):
    code: str
    name: str
    account_type: str


class ChartOfAccountRead(ORMBase):
    id: str
    code: str
    name: str
    account_type: str
    is_active: bool


class JournalLineInput(BaseModel):
    account_id: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: Optional[str] = None


class JournalEntryCreate(BaseModel):
    entry_date: date = Field(default_factory=date.today)
    narrative: Optional[str] = None
    lines: list[JournalLineInput] = Field(min_length=2)


class JournalLineRead(ORMBase):
    id: str
    account_id: str
    debit: Decimal
    credit: Decimal
    description: Optional[str] = None


class JournalEntryRead(ORMBase):
    id: str
    entry_number: str
    entry_date: date
    narrative: Optional[str] = None
    source_module: Optional[str] = None
    status: str
    lines: list[JournalLineRead] = []


class TrialBalanceLine(BaseModel):
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal


# ---- Payroll ----
class EmployerCreate(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None


class EmployerRead(ORMBase):
    id: str
    name: str
    contact_person: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None


class PayrollDeductionLine(BaseModel):
    member_id: str
    loan_id: Optional[str] = None
    savings_account_id: Optional[str] = None
    amount: Decimal = Field(gt=0)


class PayrollFileCreate(BaseModel):
    employer_id: str
    period: str
    file_reference: Optional[str] = None
    deductions: list[PayrollDeductionLine]


class PayrollDeductionRead(ORMBase):
    id: str
    member_id: str
    loan_id: Optional[str] = None
    savings_account_id: Optional[str] = None
    amount: Decimal
    status: DeductionStatus
    exception_reason: Optional[str] = None


class PayrollFileRead(ORMBase):
    id: str
    employer_id: str
    period: str
    total_amount: Decimal
    deductions: list[PayrollDeductionRead] = []


# ---- Shares ----
class ShareProductCreate(BaseModel):
    name: str
    nominal_value: Decimal = Field(gt=0)
    min_shares_per_member: int = 1
    max_shares_per_member: Optional[int] = None


class ShareProductRead(ORMBase):
    id: str
    name: str
    nominal_value: Decimal
    min_shares_per_member: int
    max_shares_per_member: Optional[int] = None
    is_active: bool


class ShareTransactionCreate(BaseModel):
    txn_type: ShareTxnType
    number_of_shares: int = Field(gt=0)
    counterparty_member_id: Optional[str] = None


class ShareTransactionRead(ORMBase):
    id: str
    txn_type: ShareTxnType
    number_of_shares: int
    amount: Decimal
    counterparty_member_id: Optional[str] = None
    board_approved: bool
    created_at: datetime


class ShareHoldingRead(ORMBase):
    id: str
    member_id: str
    product_id: str
    number_of_shares: int
    transactions: list[ShareTransactionRead] = []


class DividendDeclarationCreate(BaseModel):
    financial_year: str
    rate_per_share: Decimal = Field(gt=0)


# ---- Notifications ----
class NotificationCreate(BaseModel):
    member_id: Optional[str] = None
    user_id: Optional[str] = None
    channel: NotificationChannel
    subject: Optional[str] = None
    body: str
    event_type: Optional[str] = None


class NotificationRead(ORMBase):
    id: str
    member_id: Optional[str] = None
    user_id: Optional[str] = None
    channel: NotificationChannel
    subject: Optional[str] = None
    body: str
    status: NotificationStatus
    event_type: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None


# ---- Groups ----
class MyGroupMembershipRead(BaseModel):
    group_id: str
    group_name: str
    role: str
    joined_date: date


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class GroupRead(ORMBase):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool


class GroupMembershipCreate(BaseModel):
    member_id: str
    role: str = "member"


class GroupContributionCreate(BaseModel):
    member_id: str
    amount: Decimal = Field(gt=0)
    contribution_date: date = Field(default_factory=date.today)


class GroupContributionRead(ORMBase):
    id: str
    member_id: str
    amount: Decimal
    contribution_date: date


# ---- Risk & Compliance ----
class RiskFlagCreate(BaseModel):
    flag_type: RiskFlagType
    member_id: Optional[str] = None
    loan_id: Optional[str] = None
    description: str


class RiskFlagResolve(BaseModel):
    resolution_notes: str


class RiskFlagRead(ORMBase):
    id: str
    flag_type: RiskFlagType
    member_id: Optional[str] = None
    loan_id: Optional[str] = None
    description: str
    status: RiskFlagStatus
    resolution_notes: Optional[str] = None
    created_at: datetime
