"""
Shares Management Module: share products, holdings, transfers, and dividends.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import ShareTxnType
from app.models.base import TimestampMixin, UUIDPKMixin


class ShareProduct(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "share_products"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    nominal_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    min_shares_per_member: Mapped[int] = mapped_column(default=1)
    max_shares_per_member: Mapped[Optional[int]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    holdings: Mapped[list["ShareHolding"]] = relationship(back_populates="product")


class ShareHolding(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "share_holdings"

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("share_products.id"), nullable=False)
    number_of_shares: Mapped[int] = mapped_column(default=0)

    product: Mapped["ShareProduct"] = relationship(back_populates="holdings")
    transactions: Mapped[list["ShareTransaction"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )


class ShareTransaction(Base, UUIDPKMixin):
    __tablename__ = "share_transactions"

    holding_id: Mapped[str] = mapped_column(ForeignKey("share_holdings.id"), nullable=False)
    txn_type: Mapped[ShareTxnType] = mapped_column(Enum(ShareTxnType), nullable=False)
    number_of_shares: Mapped[int] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    counterparty_member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)
    board_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False) # type: ignore

    holding: Mapped["ShareHolding"] = relationship(back_populates="transactions")


class DividendDeclaration(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "dividend_declarations"

    financial_year: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_per_share: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    declared_date: Mapped[date] = mapped_column(default=date.today)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class DividendPayout(Base, UUIDPKMixin):
    __tablename__ = "dividend_payouts"

    declaration_id: Mapped[str] = mapped_column(ForeignKey("dividend_declarations.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    option: Mapped[str] = mapped_column(String(20), default="payout")  # payout | reinvest
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
