"""
Applies a repayment amount across a loan's outstanding installments,
oldest first. Shared by the manual repayment endpoint, payroll deduction
reconciliation, and mobile-money webhook confirmation so all three book
partial payments identically.
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import LoanStatus
from app.models.loan import LoanApplication, LoanTransaction


def apply_loan_repayment(
    db: Session,
    loan: LoanApplication,
    amount: Decimal,
    narrative: Optional[str] = None,
    performed_by_user_id: Optional[str] = None,
) -> LoanApplication:
    remaining = amount
    for installment in loan.schedule:
        if installment.is_paid or remaining <= 0:
            continue
        installment_due = installment.principal_due + installment.interest_due + installment.penalty_due
        outstanding = installment_due - installment.amount_paid
        applied = min(remaining, outstanding)
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

    return loan
