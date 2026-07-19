from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMBase


class GLSettingsUpdate(BaseModel):
    cash_account_id: Optional[str] = None
    mobile_money_account_id: Optional[str] = None
    interest_income_account_id: Optional[str] = None
    interest_expense_account_id: Optional[str] = None
    salaries_expense_account_id: Optional[str] = None
    nssf_expense_account_id: Optional[str] = None
    paye_payable_account_id: Optional[str] = None
    nssf_payable_account_id: Optional[str] = None


class GLSettingsRead(ORMBase):
    id: str
    cash_account_id: Optional[str] = None
    mobile_money_account_id: Optional[str] = None
    interest_income_account_id: Optional[str] = None
    interest_expense_account_id: Optional[str] = None
    salaries_expense_account_id: Optional[str] = None
    nssf_expense_account_id: Optional[str] = None
    paye_payable_account_id: Optional[str] = None
    nssf_payable_account_id: Optional[str] = None
    updated_at: datetime
