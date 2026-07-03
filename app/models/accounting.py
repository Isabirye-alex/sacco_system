"""
Accounting Module: chart of accounts and double-entry general ledger.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import JournalEntryStatus
from app.models.base import TimestampMixin, UUIDPKMixin


class ChartOfAccount(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "chart_of_accounts"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)  # asset, liability, equity, income, expense
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    lines: Mapped[list["JournalLine"]] = relationship(back_populates="account")


class JournalEntry(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "journal_entries"

    entry_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(default=date.today, nullable=False)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_module: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # savings, loan, shares, payroll
    source_reference_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(Enum(JournalEntryStatus), default=JournalEntryStatus.POSTED)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="JournalLine.id"
    )


class JournalLine(Base, UUIDPKMixin):
    __tablename__ = "journal_lines"

    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    entry: Mapped["JournalEntry"] = relationship(back_populates="lines")
    account: Mapped["ChartOfAccount"] = relationship(back_populates="lines")
