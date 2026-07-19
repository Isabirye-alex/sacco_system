"""
Savings Module: savings products, accounts, and transactions.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import SavingsTxnType
from app.models.base import TimestampMixin, UUIDPKMixin


class SavingsProduct(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "savings_products"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)  # regular, fixed_deposit, target, emergency
    interest_rate_annual: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    interest_frequency: Mapped[str] = mapped_column(String(20), default="monthly")  # daily/monthly/annual
    minimum_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    cooling_period_days: Mapped[int] = mapped_column(default=0)
    withdrawal_penalty_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # The liability account this product's balances post against (what the
    # SACCO owes savers). Nullable so existing products keep working before
    # someone assigns one - see app/services/gl_posting_service.py, which
    # skips (and logs a warning) rather than failing a deposit when this is
    # unset, but you won't get a balanced ledger until it's configured.
    gl_liability_account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("chart_of_accounts.id"), nullable=True
    )

    accounts: Mapped[list["SavingsAccount"]] = relationship(back_populates="product")
    gl_liability_account: Mapped[Optional["ChartOfAccount"]] = relationship()


class SavingsAccount(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "savings_accounts"

    account_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("savings_products.id"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    target_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_date: Mapped[date] = mapped_column(default=date.today)
    last_transaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Guards against posting interest twice for the same calendar month -
    # see app/services/savings_interest_service.py.
    last_interest_posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    member: Mapped["Member"] = relationship(back_populates="savings_accounts")
    product: Mapped["SavingsProduct"] = relationship(back_populates="accounts")
    transactions: Mapped[list["SavingsTransaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="SavingsTransaction.created_at"
    )


class SavingsTransaction(Base, UUIDPKMixin):
    __tablename__ = "savings_transactions"

    account_id: Mapped[str] = mapped_column(ForeignKey("savings_accounts.id"), nullable=False)
    txn_type: Mapped[SavingsTxnType] = mapped_column(Enum(SavingsTxnType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    performed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    account: Mapped["SavingsAccount"] = relationship(back_populates="transactions")
