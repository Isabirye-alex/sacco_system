from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import DisbursementChannel, GuarantorStatus, LoanStatus
from app.schemas.common import ORMBase


class LoanProductCreate(BaseModel):
    name: str
    interest_rate_annual: Decimal
    max_repayment_months: int
    grace_period_days: int = 0
    penalty_rate_pct: Decimal = Decimal("0")
    max_amount: Decimal
    requires_guarantors: bool = True
    min_guarantors: int = 1
    gl_asset_account_id: Optional[str] = None


class LoanProductUpdate(BaseModel):
    """Used mainly to link/relink a product's GL asset account after setup."""
    gl_asset_account_id: Optional[str] = None
    is_active: Optional[bool] = None


class LoanProductRead(ORMBase):
    id: str
    name: str
    interest_rate_annual: Decimal
    max_repayment_months: int
    grace_period_days: int
    penalty_rate_pct: Decimal
    max_amount: Decimal
    requires_guarantors: bool
    min_guarantors: int
    gl_asset_account_id: Optional[str] = None
    is_active: bool


class GuarantorCreate(BaseModel):
    guarantor_member_id: str
    amount_guaranteed: Decimal = Field(gt=0)


class GuarantorRead(ORMBase):
    id: str
    guarantor_member_id: str
    amount_guaranteed: Decimal
    status: GuarantorStatus
    responded_at: Optional[datetime] = None


class GuarantorResponse(BaseModel):
    accept: bool


class CollateralCreate(BaseModel):
    collateral_type: str
    description: Optional[str] = None
    estimated_value: Decimal = Field(gt=0)
    document_reference: Optional[str] = None


class CollateralRead(ORMBase):
    id: str
    collateral_type: str
    description: Optional[str] = None
    estimated_value: Decimal
    document_reference: Optional[str] = None


class GroupGuaranteeCreate(BaseModel):
    group_id: str
    amount_guaranteed: Decimal = Field(gt=0)


class GroupGuaranteeRead(ORMBase):
    id: str
    group_id: str
    loan_id: str
    amount_guaranteed: Decimal
    approved: bool
    approved_by_user_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class LoanApplicationCreate(BaseModel):
    member_id: str
    product_id: str
    amount_requested: Decimal = Field(gt=0)
    repayment_months: int = Field(gt=0)
    purpose: Optional[str] = None
    guarantors: list[GuarantorCreate] = []
    collaterals: list[CollateralCreate] = []


class LoanReschedule(BaseModel):
    new_repayment_months: int = Field(gt=0)
    new_interest_rate_annual: Optional[Decimal] = None  # defaults to keeping the product's current rate
    reason: str


class LoanDecision(BaseModel):
    approve: bool
    amount_approved: Optional[Decimal] = None
    notes: Optional[str] = None


class LoanDisbursement(BaseModel):
    disbursement_channel: DisbursementChannel
    disbursement_savings_account_id: Optional[str] = None


class GuarantorWithLoanRead(GuarantorRead):
    loan_id: str
    loan_number: str
    loan_amount_requested: Decimal
    loan_status: LoanStatus


class LoanRepayment(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: Optional[str] = None
    # Same purpose as SavingsTransactionCreate.channel - which system
    # account this repayment posts against on the ledger.
    channel: str = Field(default="cash", pattern="^(cash|mobile_money)$")


class LoanApplicationRead(ORMBase):
    id: str
    loan_number: str
    member_id: str
    product_id: str
    amount_requested: Decimal
    amount_approved: Optional[Decimal] = None
    repayment_months: int
    purpose: Optional[str] = None
    status: LoanStatus
    is_non_member_applicant: bool
    reviewed_by_user_id: Optional[str] = None
    approved_by_user_id: Optional[str] = None
    disbursed_at: Optional[datetime] = None
    created_at: datetime


class LoanApplicationDetailRead(LoanApplicationRead):
    guarantors: list[GuarantorRead] = []
    collaterals: list[CollateralRead] = []


class RepaymentScheduleRead(ORMBase):
    id: str
    installment_number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty_due: Decimal
    amount_paid: Decimal
    is_paid: bool


class LoanTransactionRead(ORMBase):
    id: str
    txn_type: str
    amount: Decimal
    narrative: Optional[str] = None
    performed_by_user_id: Optional[str] = None
    created_at: datetime
