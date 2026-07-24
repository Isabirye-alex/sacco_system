from datetime import datetime, date
from decimal import Decimal
import uuid

from sqlalchemy import Column, String, Numeric, Boolean, DateTime, Date, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.core.database import Base

class TargetVault(Base):
    __tablename__ = "target_vaults"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_number = Column(String(32), unique=True, nullable=False, index=True)
    member_id = Column(String(36), ForeignKey("members.id"), nullable=False)
    name = Column(String(128), nullable=False)  # e.g., "Land Purchase Vault", "School Fees Vault"
    vault_type = Column(String(32), default="GOAL")  # "GOAL" or "FIXED_DEPOSIT"
    
    target_amount = Column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    current_balance = Column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    interest_rate_annual = Column(Numeric(5, 2), nullable=False, default=Decimal("5.00"))
    early_withdrawal_penalty_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("2.50"))
    
    lock_period_months = Column(Integer, default=6)
    start_date = Column(Date, default=date.today)
    maturity_date = Column(Date, nullable=True)
    
    is_locked = Column(Boolean, default=True)
    status = Column(String(32), default="ACTIVE")  # "ACTIVE", "MATURED", "BROKEN"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    member = relationship("Member", backref="vaults")
