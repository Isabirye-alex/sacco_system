"""
Applies a one-time flat penalty to overdue, unpaid loan installments.

Design: each LoanProduct has a `penalty_rate_pct`. When an installment's
due_date has passed and it's still not fully paid, this calculates
penalty = outstanding_balance_on_that_installment * penalty_rate_pct / 100
and writes it into `penalty_due` once. Idempotent by construction - an
installment that already has penalty_due > 0 is skipped, so running this
job repeatedly (whether the scheduled daily job or someone hitting the
manual trigger) never charges the same installment twice.

Known simplification: this is a one-time flat penalty per installment,
not a compounding/daily-accruing penalty. Real SACCOs vary a lot here -
some charge a flat fee once overdue, others accrue daily/monthly. Flat
one-time is the simpler, safer default; ask if you need accrual instead.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import LoanStatus
from app.models.loan import LoanApplication, LoanRepaymentSchedule

TWO_PLACES = Decimal("0.01")


def apply_overdue_penalties(db: Session, as_of: Optional[date] = None) -> dict:
    as_of = as_of or date.today()

    active_loan_ids = db.scalars(
        select(LoanApplication.id).where(LoanApplication.status == LoanStatus.ACTIVE)
    ).all()
    if not active_loan_ids:
        return {"installments_penalized": 0, "loans_affected": 0, "total_penalty": "0.00"}

    overdue_installments = db.scalars(
        select(LoanRepaymentSchedule).where(
            LoanRepaymentSchedule.loan_id.in_(active_loan_ids),
            LoanRepaymentSchedule.is_paid.is_(False),
            LoanRepaymentSchedule.due_date < as_of,
            LoanRepaymentSchedule.penalty_due == 0,  # idempotency guard
        )
    ).all()

    loans_affected = set()
    total_penalty = Decimal("0")

    for installment in overdue_installments:
        loan = installment.loan
        penalty_rate = loan.product.penalty_rate_pct
        if not penalty_rate:
            continue
        outstanding = (installment.principal_due + installment.interest_due) - installment.amount_paid
        if outstanding <= 0:
            continue
        penalty = (outstanding * penalty_rate / Decimal("100")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if penalty <= 0:
            continue
        installment.penalty_due = penalty
        total_penalty += penalty
        loans_affected.add(loan.id)

    return {
        "installments_penalized": len([i for i in overdue_installments if i.penalty_due > 0]),
        "loans_affected": len(loans_affected),
        "total_penalty": str(total_penalty.quantize(TWO_PLACES)),
    }
