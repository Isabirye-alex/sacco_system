from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field
from app.schemas.common import ORMBase

class VaultCreate(BaseModel):
    member_id: str
    name: str = Field(..., description="Target vault name e.g. Land Purchase, Emergency Fund")
    vault_type: Optional[str] = Field("GOAL", description="Vault type or category e.g. GOAL, FIXED_DEPOSIT, emergency, education, custom")
    target_amount: Decimal = Field(..., gt=Decimal("0.00"), description="Target goal amount")
    lock_period_months: int = Field(6, ge=1, le=120, description="Lock period in months")
    interest_rate_annual: Decimal = Field(Decimal("5.00"), ge=Decimal("0.00"))
    early_withdrawal_penalty_pct: Decimal = Field(Decimal("2.50"), ge=Decimal("0.00"))

class VaultDeposit(BaseModel):
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Deposit amount into vault")

class VaultWithdraw(BaseModel):
    amount: Optional[Decimal] = Field(None, gt=Decimal("0.00"), description="Amount to withdraw. If None, withdraws full balance.")
    force_early_withdrawal: bool = Field(False, description="Explicit flag to break/withdraw early before maturity date")

class VaultResponse(ORMBase):
    id: str
    account_number: str
    member_id: str
    name: str
    vault_type: str
    target_amount: Decimal
    current_balance: Decimal
    interest_rate_annual: Decimal
    early_withdrawal_penalty_pct: Decimal
    lock_period_months: int
    start_date: date
    maturity_date: Optional[date] = None
    is_locked: bool
    status: str
    created_at: datetime
    last_updated_at: datetime

class VaultSummary(BaseModel):
    total_vaults: int
    active_vaults: int
    matured_vaults: int
    total_target_amount: Decimal
    total_current_balance: Decimal
    overall_progress_pct: Decimal
