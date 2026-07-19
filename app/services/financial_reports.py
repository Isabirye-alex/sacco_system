"""
Computed financial/regulatory reports, built from real ledger, member, and
loan data - replacing the admin portal's "Reports" screen, which shipped
with hardcoded dummy numbers for everything except the trial balance.

============================================================================
IMPORTANT - TWO OF THESE ARE APPROXIMATIONS, NOT OFFICIAL REGULATORY FORMULAS
============================================================================
Liquidity Ratio and Capital Adequacy Ratio, as implemented here, are
simplified proxies:

- Liquidity Ratio = (Cash + Mobile Money account balances) / (Total member
  savings liability balances). Real prudential liquidity ratios (e.g. under
  SASRA's Tier 4 microfinance regulations in Uganda) typically have a more
  specific definition of "liquid assets" and "qualifying liabilities" than
  this.
- Capital Adequacy Ratio = Equity / Total Assets. Actual regulatory capital
  adequacy calculations use tiered capital definitions (core capital,
  institutional capital) against risk-weighted assets, which is materially
  more involved than this ratio.

Both are useful internal indicators, but do NOT submit them as-is for an
actual regulatory filing without checking them against SASRA's current
published methodology - I don't have confident enough detail on the exact
formula to implement it precisely, and a wrong number on a compliance
filing is a real problem. The Balance Sheet, Income Statement, Member
Growth, and Loan Recovery reports below are plain arithmetic on your own
data and don't have this caveat.
============================================================================
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import LoanStatus, MemberStatus
from app.models.accounting import ChartOfAccount, JournalEntry, JournalLine
from app.models.loan import LoanApplication, LoanTransaction
from app.models.member import Member
from app.models.savings import SavingsAccount

TWO_PLACES = Decimal("0.01")


def _account_balances(db: Session, account_type: str, as_of: Optional[date] = None) -> list[dict]:
    query = (
        db.query(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name,
            func.coalesce(func.sum(JournalLine.debit), 0).label("debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("credit"),
        )
        .outerjoin(JournalLine, JournalLine.account_id == ChartOfAccount.id)
        .outerjoin(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(ChartOfAccount.account_type == account_type)
    )
    if as_of:
        query = query.filter((JournalEntry.entry_date <= as_of) | (JournalEntry.id.is_(None)))
    query = query.group_by(ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name)

    results = []
    for row in query.all():
        debit, credit = Decimal(row.debit), Decimal(row.credit)
        # Normal-balance convention: assets/expenses are debit-normal, the
        # rest (liability/equity/income) are credit-normal.
        balance = (debit - credit) if account_type in ("asset", "expense") else (credit - debit)
        if balance == 0:
            continue
        results.append({"code": row.code, "name": row.name, "balance": balance.quantize(TWO_PLACES)})
    return results


def get_balance_sheet(db: Session, as_of: Optional[date] = None) -> dict:
    as_of = as_of or date.today()
    assets = _account_balances(db, "asset", as_of)
    liabilities = _account_balances(db, "liability", as_of)
    equity = _account_balances(db, "equity", as_of)

    total_assets = sum((a["balance"] for a in assets), Decimal("0"))
    total_liabilities = sum((l["balance"] for l in liabilities), Decimal("0"))
    total_equity = sum((e["balance"] for e in equity), Decimal("0"))

    return {
        "as_of": as_of.isoformat(),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": str(total_assets),
        "total_liabilities": str(total_liabilities),
        "total_equity": str(total_equity),
        "balances": total_assets == (total_liabilities + total_equity),
    }


def get_income_statement(db: Session, start_date: date, end_date: date) -> dict:
    def totals_for(account_type: str) -> list[dict]:
        query = (
            db.query(
                ChartOfAccount.code, ChartOfAccount.name,
                func.coalesce(func.sum(JournalLine.debit), 0).label("debit"),
                func.coalesce(func.sum(JournalLine.credit), 0).label("credit"),
            )
            .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(ChartOfAccount.account_type == account_type)
            .filter(JournalEntry.entry_date >= start_date, JournalEntry.entry_date <= end_date)
            .group_by(ChartOfAccount.code, ChartOfAccount.name)
        )
        rows = []
        for row in query.all():
            debit, credit = Decimal(row.debit), Decimal(row.credit)
            balance = (credit - debit) if account_type == "income" else (debit - credit)
            if balance == 0:
                continue
            rows.append({"code": row.code, "name": row.name, "amount": str(balance.quantize(TWO_PLACES))})
        return rows

    income_lines = totals_for("income")
    expense_lines = totals_for("expense")
    total_income = sum((Decimal(l["amount"]) for l in income_lines), Decimal("0"))
    total_expense = sum((Decimal(l["amount"]) for l in expense_lines), Decimal("0"))

    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "income": income_lines,
        "expenses": expense_lines,
        "total_income": str(total_income),
        "total_expenses": str(total_expense),
        "net_surplus": str((total_income - total_expense).quantize(TWO_PLACES)),
    }


def get_liquidity_ratio(db: Session, as_of: Optional[date] = None) -> dict:
    """See module docstring - this is a simplified proxy, not the official regulatory formula."""
    as_of = as_of or date.today()

    liquid_asset_codes = {"cash", "mobile money", "mobile_money"}  # matched loosely against account name/type below
    assets = _account_balances(db, "asset", as_of)
    liquid_assets = sum(
        (a["balance"] for a in assets if any(k in a["name"].lower() for k in ("cash", "till", "mobile money"))),
        Decimal("0"),
    )

    liabilities = _account_balances(db, "liability", as_of)
    total_deposits = sum((l["balance"] for l in liabilities), Decimal("0"))

    ratio = (liquid_assets / total_deposits * 100) if total_deposits > 0 else Decimal("0")
    return {
        "as_of": as_of.isoformat(),
        "liquid_assets": str(liquid_assets.quantize(TWO_PLACES)),
        "total_deposit_liabilities": str(total_deposits.quantize(TWO_PLACES)),
        "liquidity_ratio_pct": str(ratio.quantize(TWO_PLACES)),
        "is_approximation": True,
    }


def get_capital_adequacy(db: Session, as_of: Optional[date] = None) -> dict:
    """See module docstring - this is a simplified proxy, not the official SASRA formula."""
    as_of = as_of or date.today()
    balance_sheet = get_balance_sheet(db, as_of)
    total_assets = Decimal(balance_sheet["total_assets"])
    total_equity = Decimal(balance_sheet["total_equity"])
    ratio = (total_equity / total_assets * 100) if total_assets > 0 else Decimal("0")
    return {
        "as_of": as_of.isoformat(),
        "total_equity": str(total_equity.quantize(TWO_PLACES)),
        "total_assets": str(total_assets.quantize(TWO_PLACES)),
        "capital_adequacy_ratio_pct": str(ratio.quantize(TWO_PLACES)),
        "is_approximation": True,
    }


def get_member_growth(db: Session, months: int = 12) -> dict:
    """
    Membership counts by join-month for the trailing N months, plus a
    current status breakdown. Grouped in Python rather than with a SQL
    date-truncation function, since SQLite (dev) and Postgres (production)
    don't share one - this keeps it portable across both.
    """
    from collections import Counter
    from dateutil.relativedelta import relativedelta

    since = date.today().replace(day=1) - relativedelta(months=months - 1)

    all_members = db.query(Member.date_joined, Member.status).filter(Member.date_joined >= since).all()
    counter = Counter(m.date_joined.strftime("%Y-%m") for m in all_members if m.date_joined)
    monthly = [{"month": month, "new_members": count} for month, count in sorted(counter.items())]

    status_counts = dict(db.query(Member.status, func.count(Member.id)).group_by(Member.status).all())
    return {
        "monthly_new_members": monthly,
        "total_members": db.query(func.count(Member.id)).scalar() or 0,
        "by_status": {status.value if hasattr(status, "value") else status: count for status, count in status_counts.items()},
    }


def get_dashboard_trends(db: Session, months: int = 7) -> dict:
    """
    Real monthly savings deposit/withdrawal totals, loan disbursement/
    repayment totals, and savings product volume distribution - for the
    admin dashboard's trend charts. All computed from actual transaction
    timestamps, not derived/interpolated from a single current snapshot.
    """
    from collections import defaultdict

    from dateutil.relativedelta import relativedelta

    from app.core.enums import SavingsTxnType
    from app.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction

    since = date.today().replace(day=1) - relativedelta(months=months - 1)
    since_dt = datetime.combine(since, datetime.min.time())

    month_keys = []
    cursor = since
    for _ in range(months):
        month_keys.append(cursor.strftime("%Y-%m"))
        cursor = cursor + relativedelta(months=1)

    deposits_by_month = defaultdict(Decimal)
    withdrawals_by_month = defaultdict(Decimal)
    for txn_type, bucket in ((SavingsTxnType.DEPOSIT, deposits_by_month), (SavingsTxnType.WITHDRAWAL, withdrawals_by_month)):
        rows = (
            db.query(SavingsTransaction.amount, SavingsTransaction.created_at)
            .filter(SavingsTransaction.txn_type == txn_type, SavingsTransaction.created_at >= since_dt)
            .all()
        )
        for amount, created_at in rows:
            bucket[created_at.strftime("%Y-%m")] += Decimal(amount)

    disbursed_by_month = defaultdict(Decimal)
    repaid_by_month = defaultdict(Decimal)
    txn_rows = (
        db.query(LoanTransaction.txn_type, LoanTransaction.amount, LoanTransaction.created_at)
        .filter(LoanTransaction.created_at >= since_dt, LoanTransaction.txn_type.in_(["disbursement", "repayment"]))
        .all()
    )
    for txn_type, amount, created_at in txn_rows:
        key = created_at.strftime("%Y-%m")
        if txn_type == "disbursement":
            disbursed_by_month[key] += Decimal(amount)
        else:
            repaid_by_month[key] += Decimal(amount)

    monthly_savings = [
        {"month": m, "deposits": str(deposits_by_month[m].quantize(TWO_PLACES)), "withdrawals": str(withdrawals_by_month[m].quantize(TWO_PLACES))}
        for m in month_keys
    ]
    monthly_loans = [
        {"month": m, "disbursed": str(disbursed_by_month[m].quantize(TWO_PLACES)), "repaid": str(repaid_by_month[m].quantize(TWO_PLACES))}
        for m in month_keys
    ]

    # Real product volume distribution: sum of current balances grouped by product.
    product_rows = (
        db.query(SavingsProduct.name, func.coalesce(func.sum(SavingsAccount.balance), 0))
        .join(SavingsAccount, SavingsAccount.product_id == SavingsProduct.id)
        .filter(SavingsAccount.is_active.is_(True))
        .group_by(SavingsProduct.name)
        .all()
    )
    product_distribution = [{"product": name, "balance": str(Decimal(total).quantize(TWO_PLACES))} for name, total in product_rows if total]

    return {
        "monthly_savings": monthly_savings,
        "monthly_loans": monthly_loans,
        "product_distribution": product_distribution,
    }
    from datetime import datetime as dt, time as time_

    range_start = dt.combine(start_date, time_.min)
    range_end = dt.combine(end_date, time_.max)

    disbursed_loans = (
        db.query(LoanApplication)
        .filter(
            LoanApplication.disbursed_at.is_not(None),
            LoanApplication.disbursed_at >= range_start,
            LoanApplication.disbursed_at <= range_end,
        )
        .all()
    )
    total_disbursed = sum((l.amount_approved or Decimal("0")) for l in disbursed_loans)

    # Repayments actually *collected within this period* - using
    # LoanTransaction (which has a timestamp) rather than the schedule's
    # cumulative amount_paid (which has no date, so can't be period-scoped).
    repayments_in_period = (
        db.query(func.coalesce(func.sum(LoanTransaction.amount), 0))
        .filter(
            LoanTransaction.txn_type == "repayment",
            LoanTransaction.created_at >= range_start,
            LoanTransaction.created_at <= range_end,
        )
        .scalar()
    )

    active_count = db.query(func.count(LoanApplication.id)).filter(LoanApplication.status == LoanStatus.ACTIVE).scalar() or 0
    closed_count = db.query(func.count(LoanApplication.id)).filter(LoanApplication.status == LoanStatus.CLOSED).scalar() or 0
    defaulted_count = db.query(func.count(LoanApplication.id)).filter(LoanApplication.status == LoanStatus.DEFAULTED).scalar() or 0

    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "loans_disbursed_count": len(disbursed_loans),
        "total_disbursed": str(Decimal(total_disbursed).quantize(TWO_PLACES)),
        "total_repaid_in_period": str(Decimal(repayments_in_period or 0).quantize(TWO_PLACES)),
        "active_loans": active_count,
        "closed_loans": closed_count,
        "defaulted_loans": defaulted_count,
    }
