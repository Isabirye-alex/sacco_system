"""
Shared logic for turning an APPROVED loan into an ACTIVE one once funds have
actually moved - whether that's an immediate internal transfer to a savings
account (synchronous) or a mobile money disbursement confirmed later by a
webhook (asynchronous). Both paths must build the same schedule and leave
the loan in the same state, so it lives here once instead of twice.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import DisbursementChannel, LoanStatus
from app.models.loan import LoanApplication, LoanRepaymentSchedule, LoanTransaction
from app.services.loan_calculator import build_reducing_balance_schedule


def activate_disbursed_loan(
    db: Session,
    loan: LoanApplication,
    channel: DisbursementChannel,
    savings_account_id: Optional[str] = None,
    performed_by_user_id: Optional[str] = None,
    narrative: Optional[str] = None,
) -> LoanApplication:
    """
    Idempotency guard: if the loan is already ACTIVE/DISBURSED/CLOSED, this
    is a no-op rather than rebuilding a second schedule (important because
    mobile money webhooks can be delivered more than once).
    """
    if loan.status in (LoanStatus.ACTIVE, LoanStatus.DISBURSED, LoanStatus.CLOSED):
        return loan

    principal: Decimal = loan.amount_approved # type: ignore
    schedule_rows = build_reducing_balance_schedule(
        principal=principal,
        annual_interest_rate_pct=loan.product.interest_rate_annual,
        months=loan.repayment_months,
        start_date=date.today(),
    )
    loan.schedule = [
        LoanRepaymentSchedule(installment_number=n, due_date=due, principal_due=p, interest_due=i)
        for n, due, p, i in schedule_rows
    ]

    loan.disbursement_channel = channel
    loan.disbursement_savings_account_id = savings_account_id
    loan.disbursed_at = datetime.utcnow() # type: ignore
    loan.status = LoanStatus.ACTIVE

    db.add(
        LoanTransaction(
            loan_id=loan.id,
            txn_type="disbursement",
            amount=principal,
            narrative=narrative or f"Disbursed via {channel.value}",
            performed_by_user_id=performed_by_user_id,
        )
    )
    return loan
