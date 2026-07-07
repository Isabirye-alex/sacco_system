from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.mobile_money import MobileMoneyDirection, MobileMoneyPurpose, MobileMoneyStatus
from app.schemas.common import ORMBase


class MobileMoneyDepositRequest(BaseModel):
    member_id: str
    savings_account_id: str
    amount: Decimal = Field(gt=0)
    phone_number: Optional[str] = None  # defaults to the member's phone_number on file


class MobileMoneyWithdrawalRequest(BaseModel):
    member_id: str
    savings_account_id: str
    amount: Decimal = Field(gt=0)
    phone_number: Optional[str] = None


class MobileMoneyLoanRepaymentRequest(BaseModel):
    member_id: str
    loan_id: str
    amount: Decimal = Field(gt=0)
    phone_number: Optional[str] = None


class MobileMoneyLoanDisbursementRequest(BaseModel):
    phone_number: Optional[str] = None  # defaults to the member's phone_number on file


class MobileMoneyTransactionRead(ORMBase):
    id: str
    direction: MobileMoneyDirection
    purpose: MobileMoneyPurpose
    status: MobileMoneyStatus
    member_id: str
    savings_account_id: Optional[str] = None
    loan_id: Optional[str] = None
    amount: Decimal
    phone_number: str
    provider: Optional[str] = None
    provider_transaction_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None


class MarzPayCallbackPayload(BaseModel):
    """
    Loose model for the inbound webhook body. We deliberately don't trust
    this for anything financial - only `transaction.uuid` is used, to look
    up the corresponding row here and then re-verify status directly with
    MarzPay's API. See app/routers/mobile_money.py.
    """
    event_type: Optional[str] = None
    transaction: dict # type: ignore
    collection: Optional[dict] = None # type: ignore
    disbursement: Optional[dict] = None # type: ignore
