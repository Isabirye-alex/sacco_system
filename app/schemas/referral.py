from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.enums import NotificationChannel
from app.models.referral import ReferralStatus
from app.schemas.common import ORMBase


class ReferralCreate(BaseModel):
    referrer_member_id: str
    referred_name: str = Field(min_length=2)
    referred_contact: str  # phone (for sms) or email
    channel: NotificationChannel


class ReferralRead(ORMBase):
    id: str
    referral_code: str
    referrer_member_id: str
    referred_name: str
    referred_contact: str
    channel: NotificationChannel
    status: ReferralStatus
    invited_at: datetime
    registered_member_id: Optional[str] = None
    registered_at: Optional[datetime] = None
    commission_amount: Optional[Decimal] = None
    commission_paid_at: Optional[datetime] = None


class PayCommissionRequest(BaseModel):
    savings_account_id: str  # the referrer's account to credit


class SystemSettingsUpdate(BaseModel):
    referral_commission_amount: Optional[Decimal] = None


class SystemSettingsRead(ORMBase):
    id: str
    referral_commission_amount: Decimal
    updated_at: datetime
