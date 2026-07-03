"""
HR & Payroll Deductions Module endpoints: employer management and payroll
deduction file processing with per-line reconciliation against loans and
savings accounts.
"""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import DeductionStatus, SavingsTxnType, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.loan import LoanApplication, LoanTransaction
from app.models.payroll import Employer, PayrollDeduction, PayrollFile
from app.models.savings import SavingsAccount, SavingsTransaction
from app.models.user import User
from app.schemas.misc import EmployerCreate, EmployerRead, PayrollFileCreate, PayrollFileRead

router = APIRouter(prefix="/api/v1/payroll", tags=["HR & Payroll"])

HR_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.HR_OFFICER, UserRole.ACCOUNTANT)


@router.post("/employers", response_model=EmployerRead, status_code=status.HTTP_201_CREATED)
def create_employer(
    payload: EmployerCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))
):
    employer = Employer(**payload.model_dump())
    db.add(employer)
    db.commit()
    db.refresh(employer)
    return employer


@router.get("/employers", response_model=list[EmployerRead])
def list_employers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Employer).all()


@router.post("/files", response_model=PayrollFileRead, status_code=status.HTTP_201_CREATED)
def upload_payroll_file(
    payload: PayrollFileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*HR_ROLES)),
):
    """
    Ingests a batch of payroll deduction lines for a period and immediately
    attempts to reconcile each line against the target loan or savings
    account. Lines that cannot be matched are flagged as exceptions for
    manual review rather than silently failing the whole batch.
    """
    employer = db.get(Employer, payload.employer_id)
    if not employer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employer not found.")

    payroll_file = PayrollFile(
        employer_id=payload.employer_id,
        period=payload.period,
        file_reference=payload.file_reference,
        uploaded_by_user_id=current_user.id,
        total_amount=sum((line.amount for line in payload.deductions), Decimal("0")),
    )
    db.add(payroll_file)
    db.flush()

    for line in payload.deductions:
        deduction = PayrollDeduction(
            payroll_file_id=payroll_file.id,
            member_id=line.member_id,
            loan_id=line.loan_id,
            savings_account_id=line.savings_account_id,
            amount=line.amount,
        )
        try:
            _reconcile_deduction(db, deduction, current_user)
        except ValueError as exc:
            deduction.status = DeductionStatus.EXCEPTION
            deduction.exception_reason = str(exc)
        db.add(deduction)

    db.commit()
    db.refresh(payroll_file)
    return payroll_file


def _reconcile_deduction(db: Session, deduction: PayrollDeduction, current_user: User) -> None:
    if deduction.loan_id:
        loan = db.get(LoanApplication, deduction.loan_id)
        if not loan:
            raise ValueError("Referenced loan not found.")
        for installment in loan.schedule:
            if installment.is_paid or deduction.amount <= 0:
                continue
            due = installment.principal_due + installment.interest_due + installment.penalty_due
            outstanding = due - installment.amount_paid
            applied = min(deduction.amount, outstanding)
            installment.amount_paid += applied
            if installment.amount_paid >= due:
                installment.is_paid = True
        db.add(
            LoanTransaction(
                loan_id=loan.id,
                txn_type="repayment",
                amount=deduction.amount,
                narrative="Payroll deduction",
                performed_by_user_id=current_user.id,
            )
        )
    elif deduction.savings_account_id:
        account = db.get(SavingsAccount, deduction.savings_account_id)
        if not account:
            raise ValueError("Referenced savings account not found.")
        new_balance = account.balance + deduction.amount
        db.add(
            SavingsTransaction(
                account_id=account.id,
                txn_type=SavingsTxnType.DEPOSIT,
                amount=deduction.amount,
                balance_after=new_balance,
                narrative="Payroll deduction",
                performed_by_user_id=current_user.id,
            )
        )
        account.balance = new_balance
        account.last_transaction_at = datetime.utcnow()
    else:
        raise ValueError("Deduction line has no loan_id or savings_account_id target.")

    deduction.status = DeductionStatus.RECONCILED
    deduction.reconciled_at = datetime.utcnow()


@router.get("/files/{payroll_file_id}", response_model=PayrollFileRead)
def get_payroll_file(payroll_file_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))):
    payroll_file = db.get(PayrollFile, payroll_file_id)
    if not payroll_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll file not found.")
    return payroll_file
