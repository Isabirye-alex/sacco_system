from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import SavingsTxnType
from app.schemas.common import ORMBase


class SavingsProductCreate(BaseModel):
    name: str
    product_type: str
    interest_rate_annual: Decimal = Decimal("0")
    interest_frequency: str = "monthly"
    minimum_balance: Decimal = Decimal("0")
    cooling_period_days: int = 0
    withdrawal_penalty_pct: Decimal = Decimal("0")


class SavingsProductRead(ORMBase):
    id: str
    name: str
    product_type: str
    interest_rate_annual: Decimal
    interest_frequency: str
    minimum_balance: Decimal
    cooling_period_days: int
    withdrawal_penalty_pct: Decimal
    is_active: bool


class SavingsAccountCreate(BaseModel):
    member_id: str
    product_id: str
    target_amount: Optional[Decimal] = None


class SavingsAccountRead(ORMBase):
    id: str
    account_number: str
    member_id: str
    product_id: str
    balance: Decimal
    target_amount: Optional[Decimal] = None
    is_active: bool
    opened_date: date
    last_transaction_at: Optional[datetime] = None


class SavingsTransactionCreate(BaseModel):
    txn_type: SavingsTxnType
    amount: Decimal = Field(gt=0)
    narrative: Optional[str] = None
    reference: Optional[str] = None


class SavingsTransactionRead(ORMBase):
    id: str
    account_id: str
    txn_type: SavingsTxnType
    amount: Decimal
    balance_after: Decimal
    narrative: Optional[str] = None
    reference: Optional[str] = None
    created_at: datetime
