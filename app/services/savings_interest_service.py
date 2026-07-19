"""
Posts monthly savings interest for every active account whose product has
an interest_rate_annual > 0.

Formula: interest = balance * (annual_rate / 100 / 12) - a simple average-
monthly-balance approximation using the CURRENT balance at posting time,
not a true daily-average-balance calculation. Real SACCOs sometimes use
daily-average-balance for interest (fairer if balances fluctuate a lot
mid-month); this is the simpler starting point. Flag if you need
daily-average instead - it requires tracking a balance history, not just
the current balance.

Idempotency: guarded by SavingsAccount.last_interest_posted_at - an
account already posted within the current calendar month is skipped, so
running this job more than once in the same month (whether the scheduled
run or a manual trigger) won't double-pay interest.
"""
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import SavingsTxnType
from app.models.savings import SavingsAccount, SavingsTransaction
from app.services.gl_posting_service import post_savings_transaction_gl

logger = logging.getLogger("sacco.savings_interest")
TWO_PLACES = Decimal("0.01")


def _already_posted_this_month(account: SavingsAccount, today: date) -> bool:
    if not account.last_interest_posted_at:
        return False
    posted = account.last_interest_posted_at
    return posted.year == today.year and posted.month == today.month


def post_savings_interest(db: Session, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()

    accounts = db.scalars(
        select(SavingsAccount).where(SavingsAccount.is_active.is_(True), SavingsAccount.balance > 0)
    ).all()

    posted_count = 0
    skipped_no_rate = 0
    skipped_already_posted = 0
    total_interest = Decimal("0")

    for account in accounts:
        if _already_posted_this_month(account, as_of):
            skipped_already_posted += 1
            continue

        rate = account.product.interest_rate_annual
        if not rate or rate <= 0:
            skipped_no_rate += 1
            continue

        interest = (account.balance * rate / Decimal("100") / Decimal("12")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if interest <= 0:
            continue

        new_balance = account.balance + interest
        txn = SavingsTransaction(
            account_id=account.id,
            txn_type=SavingsTxnType.INTEREST_POSTING,
            amount=interest,
            balance_after=new_balance,
            narrative=f"Monthly interest posting ({rate}% p.a.)",
        )
        db.add(txn)
        db.flush()

        account.balance = new_balance
        account.last_interest_posted_at = datetime.utcnow()

        post_savings_transaction_gl(db, account, txn)

        posted_count += 1
        total_interest += interest

    return {
        "accounts_posted": posted_count,
        "accounts_skipped_no_rate": skipped_no_rate,
        "accounts_skipped_already_posted": skipped_already_posted,
        "total_interest": str(total_interest.quantize(TWO_PLACES)),
    }
