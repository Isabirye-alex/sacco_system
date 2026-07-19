"""
A single-row settings table for general business configuration that isn't
GL-account related (see app/models/gl_settings.py for that). Currently
just the referral commission amount; extensible later without a schema
migration for every new setting if you keep adding simple scalar fields
here.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DEFAULT_SETTINGS_ID = "default"


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=DEFAULT_SETTINGS_ID)

    # Flat commission paid to a member when someone they referred becomes
    # a registered member - see app/routers/referrals.py.
    referral_commission_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
