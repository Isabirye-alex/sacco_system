"""
A single-row settings table holding the small set of "system" GL accounts
that automatic postings need on the *other* side of every entry:

- cash_account_id: physical cash movements (teller deposits/withdrawals,
  cash loan disbursements)
- mobile_money_account_id: MarzPay-mediated movements (a clearing/holding
  account for funds in transit through your mobile money wallet)
- interest_income_account_id: where loan interest is recognized as income
  when a repayment is applied

Savings/loan products each point at their own liability/asset account (see
gl_liability_account_id on SavingsProduct and gl_asset_account_id on
LoanProduct) - this table is only for the shared "other side" accounts that
every product's transactions have in common.

Single row by convention (id is always "default") rather than a full
multi-branch/multi-till setup - see gl_posting_service.py docstring for why
that's a reasonable simplification for now.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

DEFAULT_SETTINGS_ID = "default"


class GLSettings(Base):
    __tablename__ = "gl_settings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=DEFAULT_SETTINGS_ID)

    cash_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    mobile_money_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    interest_income_account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("chart_of_accounts.id"), nullable=True
    )
    # Interest PAID to savers (an expense) - distinct from interest_income_account_id,
    # which is interest EARNED from loans (income). Used by
    # app/services/savings_interest_service.py.
    interest_expense_account_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("chart_of_accounts.id"), nullable=True
    )

    # Staff payroll accounts - see app/services/gl_posting_service.post_payroll_gl
    salaries_expense_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    nssf_expense_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    paye_payable_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    nssf_payable_account_id: Mapped[Optional[str]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cash_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[cash_account_id])
    mobile_money_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[mobile_money_account_id])
    interest_income_account: Mapped[Optional["ChartOfAccount"]] = relationship(
        foreign_keys=[interest_income_account_id]
    )
    interest_expense_account: Mapped[Optional["ChartOfAccount"]] = relationship(
        foreign_keys=[interest_expense_account_id]
    )
    salaries_expense_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[salaries_expense_account_id])
    nssf_expense_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[nssf_expense_account_id])
    paye_payable_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[paye_payable_account_id])
    nssf_payable_account: Mapped[Optional["ChartOfAccount"]] = relationship(foreign_keys=[nssf_payable_account_id])
