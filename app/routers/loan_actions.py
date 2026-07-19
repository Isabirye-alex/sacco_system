"""
Loan Actions Module: three endpoints that replace frontend actions which
were previously faked (see delivery notes) - "Waive Penalties" and "Write
off Loan" showed a success toast without calling any backend at all, and
"Alert Guarantors" was sending the collections notice to the borrower
instead of the actual guarantors.

Kept as its own router (rather than pasted into your existing loans.py)
so applying it is a clean drop-in: add one import + one
app.include_router() line in main.py, no risk of a copy-paste merge
conflict with whatever you've already customized in loans.py.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import LoanStatus, UserRole
from app.dependencies import require_roles
from app.models.loan import LoanApplication
from app.models.member import Member
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_loan_writeoff_gl

router = APIRouter(prefix="/api/v1/loans", tags=["Credit & Loans"])

LOAN_OFFICER_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER)


class LoanWriteOffRequest(BaseModel):
    reason: str


class LoanReturnForCorrectionRequest(BaseModel):
    notes: str


@router.post("/applications/{loan_id}/return-for-correction")
def return_loan_for_correction(
    loan_id: str,
    payload: LoanReturnForCorrectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    """
    Moves the loan to UNDER_REVIEW (a real, existing status - distinct
    from PENDING, meaning "seen and awaiting the applicant's action")
    and notifies the borrower what needs fixing. Previously this only
    raised a misused risk flag and never touched the loan's actual status
    at all.
    """
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status not in (LoanStatus.PENDING, LoanStatus.UNDER_REVIEW):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending loans can be returned for correction.")

    loan.status = LoanStatus.UNDER_REVIEW

    from app.core.enums import NotificationChannel
    from app.services.notification_service import dispatch, queue_notification

    if loan.member:
        notification = queue_notification(
            db, channel=NotificationChannel.SMS,
            body=f"Your loan application {loan.loan_number} needs corrections: {payload.notes}",
            member_id=loan.member_id, event_type="loan_returned_for_correction",
        )
        try:
            dispatch(notification)
        except Exception:
            pass

    record_audit(
        db, actor_user_id=current_user.id, action="loan.returned_for_correction", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Returned {loan.loan_number} for correction: {payload.notes}",
    )
    db.commit()
    db.refresh(loan)
    return {"loan_id": loan.id, "status": loan.status.value}


@router.post("/applications/{loan_id}/waive-penalties")
def waive_loan_penalties(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")

    waived_total = Decimal("0")
    installments_touched = 0
    for installment in loan.schedule:
        if installment.is_paid or installment.penalty_due <= 0:
            continue
        waived_total += installment.penalty_due
        installment.penalty_due = Decimal("0")
        installments_touched += 1

    record_audit(
        db, actor_user_id=current_user.id, action="loan.penalties_waived", entity_type="LoanApplication",
        entity_id=loan.id,
        details=f"Waived UGX {waived_total} in penalties across {installments_touched} installment(s) on {loan.loan_number}",
    )
    db.commit()
    return {"installments_waived": installments_touched, "total_waived": str(waived_total)}


@router.post("/applications/{loan_id}/write-off")
def write_off_loan(
    loan_id: str,
    payload: LoanWriteOffRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    """
    Closes out every unpaid installment and books the loss to the GL
    (debit Loan Loss Expense, credit Loans Receivable - see
    gl_posting_service.post_loan_writeoff_gl). Requires
    GLSettings.loan_loss_expense_account_id to be configured, same
    soft-skip-with-warning behavior as the rest of the GL posting system
    if it isn't.
    """
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status not in (LoanStatus.ACTIVE, LoanStatus.DEFAULTED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active or already-defaulted loans can be written off.")

    outstanding = Decimal("0")
    for installment in loan.schedule:
        if installment.is_paid:
            continue
        due = installment.principal_due + installment.interest_due + installment.penalty_due
        outstanding += max(due - installment.amount_paid, Decimal("0"))
        installment.is_paid = True  # closes the schedule; the loss is booked via the GL entry, not further collection

    if outstanding <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This loan has no outstanding balance to write off.")

    post_loan_writeoff_gl(db, loan, outstanding, performed_by_user_id=current_user.id)
    loan.status = LoanStatus.DEFAULTED

    record_audit(
        db, actor_user_id=current_user.id, action="loan.write_off", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Wrote off UGX {outstanding} on {loan.loan_number}. Reason: {payload.reason}",
    )
    db.commit()
    db.refresh(loan)
    return {"loan_id": loan.id, "amount_written_off": str(outstanding), "status": loan.status.value}


@router.post("/applications/{loan_id}/notify-guarantors")
def notify_guarantors(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    """Sends a collections alert to each of THIS loan's actual guarantors - not the borrower."""
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")

    from app.core.enums import NotificationChannel
    from app.services.notification_service import dispatch, queue_notification

    notified = 0
    for guarantor in loan.guarantors:
        member = db.get(Member, guarantor.guarantor_member_id)
        if not member:
            continue
        notification = queue_notification(
            db, channel=NotificationChannel.SMS,
            body=f"ALERT: The loan {loan.loan_number} you guaranteed is overdue. Please encourage the borrower to clear the outstanding amount.",
            member_id=member.id, event_type="guarantor_collections_alert",
        )
        try:
            dispatch(notification)
        except Exception:
            pass  # a failed SMS shouldn't block notifying the rest of the guarantors
        notified += 1

    record_audit(
        db, actor_user_id=current_user.id, action="loan.guarantors_notified", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Notified {notified} guarantor(s) on {loan.loan_number}",
    )
    db.commit()
    return {"guarantors_notified": notified}
