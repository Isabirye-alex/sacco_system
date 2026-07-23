"""
Bank Reconciliation Module: database models for bank statements and line matching.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class BankStatement(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "bank_statements"

    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    uploaded_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    transactions: Mapped[list["BankStatementTransaction"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )


class BankStatementTransaction(Base, UUIDPKMixin):
    __tablename__ = "bank_statement_transactions"

    statement_id: Mapped[str] = mapped_column(ForeignKey("bank_statements.id"), nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_journal_entry_id: Mapped[Optional[str]] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    statement: Mapped["BankStatement"] = relationship(back_populates="transactions")
