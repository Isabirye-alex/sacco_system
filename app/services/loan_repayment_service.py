"""
Applies a repayment amount across a loan's outstanding installments,
oldest first. Shared by the manual repayment endpoint, payroll deduction
reconciliation, and mobile-money webhook confirmation so all three book
partial payments identically - and so all three post the same, correct
principal/interest split to the general ledger (see
app/services/gl_posting_service.post_loan_repayment_gl).

Note on the split: LoanRepaymentSchedule only tracks a single amount_paid
per installment rather than separate principal/interest/penalty-paid
columns, so when a payment covers only *part* of an installment, this
allocates it proportionally across that installment's principal/interest/
penalty components rather than a strict "interest first" waterfall. That's
a reasonable approximation for GL purposes without a schema change, but
worth knowing if you later want strict interest-first allocation.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import LoanStatus
from app.models.loan import LoanApplication, LoanTransaction

TWO_PLACES = Decimal("0.01")


@dataclass
class RepaymentBreakdown:
    principal_paid: Decimal
    interest_paid: Decimal
    penalty_paid: Decimal
    unapplied: Decimal  # left over if the payment exceeded the full outstanding balance


def apply_loan_repayment(
    db: Session,
    loan: LoanApplication,
    amount: Decimal,
    narrative: Optional[str] = None,
    performed_by_user_id: Optional[str] = None,
) -> RepaymentBreakdown:
    remaining = amount
    principal_component = Decimal("0")
    interest_component = Decimal("0")
    penalty_component = Decimal("0")

    for installment in loan.schedule:
        if installment.is_paid or remaining <= 0:
            continue
        installment_due = installment.principal_due + installment.interest_due + installment.penalty_due
        outstanding = installment_due - installment.amount_paid
        if outstanding <= 0:
            continue
        applied = min(remaining, outstanding)

        if installment_due > 0:
            principal_component += applied * installment.principal_due / installment_due
            interest_component += applied * installment.interest_due / installment_due
            penalty_component += applied * installment.penalty_due / installment_due

        installment.amount_paid += applied
        remaining -= applied
        if installment.amount_paid >= installment_due:
            installment.is_paid = True

    db.add(
        LoanTransaction(
            loan_id=loan.id,
            txn_type="repayment",
            amount=amount,
            narrative=narrative,
            performed_by_user_id=performed_by_user_id,
        )
    )

    if loan.schedule and all(i.is_paid for i in loan.schedule):
        loan.status = LoanStatus.CLOSED

    return RepaymentBreakdown(
        principal_paid=principal_component.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        interest_paid=interest_component.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        penalty_paid=penalty_component.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        unapplied=remaining,
    )
