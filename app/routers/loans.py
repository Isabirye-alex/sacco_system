"""
Credit / Loan Management endpoints: product setup, applications, guarantor
workflow, approval/rejection, disbursement, and repayments. Disbursement and
repayment operations post balancing entries to the general ledger.
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import (
    DisbursementChannel,
    GuarantorStatus,
    LoanStatus,
    SavingsTxnType,
    UserRole,
)
from app.dependencies import get_current_user, require_roles
from app.models.loan import Collateral, Guarantor, LoanApplication, LoanProduct, LoanRepaymentSchedule, LoanTransaction
from app.models.member import Member
from app.models.savings import SavingsAccount, SavingsTransaction
from app.models.user import User
from app.schemas.loan import (
    GuarantorResponse,
    GuarantorWithLoanRead,
    LoanApplicationCreate,
    LoanApplicationDetailRead,
    LoanApplicationRead,
    LoanDecision,
    LoanDisbursement,
    LoanProductCreate,
    LoanProductRead,
    LoanRepayment,
    RepaymentScheduleRead,
)
from app.services.loan_calculator import build_reducing_balance_schedule
from app.services.numbering import generate_loan_number

router = APIRouter(prefix="/api/v1/loans", tags=["Credit & Loans"])

LOAN_OFFICER_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER)


# ---------- Loan Products ----------
@router.post("/products", response_model=LoanProductRead, status_code=status.HTTP_201_CREATED)
def create_loan_product(
    payload: LoanProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    product = LoanProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[LoanProductRead])
def list_loan_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(LoanProduct).filter(LoanProduct.is_active.is_(True)).all()


# ---------- Loan Applications ----------
@router.post("/applications", response_model=LoanApplicationDetailRead, status_code=status.HTTP_201_CREATED)
def apply_for_loan(
    payload: LoanApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    product = db.get(LoanProduct, payload.product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan product not found or inactive.")
    if payload.amount_requested > product.max_amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Amount exceeds product maximum of {product.max_amount}.",
        )
    if product.requires_guarantors and len(payload.guarantors) < product.min_guarantors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This product requires at least {product.min_guarantors} guarantor(s).",
        )

    loan = LoanApplication(
        loan_number=generate_loan_number(),
        member_id=payload.member_id,
        product_id=payload.product_id,
        amount_requested=payload.amount_requested,
        repayment_months=payload.repayment_months,
        purpose=payload.purpose,
        status=LoanStatus.PENDING,
    )
    loan.guarantors = [
        Guarantor(guarantor_member_id=g.guarantor_member_id, amount_guaranteed=g.amount_guaranteed)
        for g in payload.guarantors
    ]
    loan.collaterals = [Collateral(**c.model_dump()) for c in payload.collaterals]

    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


@router.get("/applications", response_model=list[LoanApplicationRead])
def list_loan_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    member_id: str | None = None,
    loan_status: LoanStatus | None = None,
):
    query = db.query(LoanApplication)
    if member_id:
        query = query.filter(LoanApplication.member_id == member_id)
    if loan_status:
        query = query.filter(LoanApplication.status == loan_status)
    return query.order_by(LoanApplication.created_at.desc()).all()


@router.get("/applications/{loan_id}", response_model=LoanApplicationDetailRead)
def get_loan_application(loan_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    return loan


@router.get("/applications/{loan_id}/schedule", response_model=list[RepaymentScheduleRead])
def get_repayment_schedule(loan_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    return loan.schedule


# ---------- Guarantor Workflow ----------
@router.get("/guarantors/by-member/{member_id}", response_model=list[GuarantorWithLoanRead])
def list_guarantee_requests_for_member(
    member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Loan guarantee requests directed at a given member, most recent first."""
    guarantors = (
        db.query(Guarantor)
        .filter(Guarantor.guarantor_member_id == member_id)
        .order_by(Guarantor.created_at.desc())
        .all()
    )
    return [
        GuarantorWithLoanRead(
            id=g.id,
            guarantor_member_id=g.guarantor_member_id,
            amount_guaranteed=g.amount_guaranteed,
            status=g.status,
            responded_at=g.responded_at,
            loan_id=g.loan.id,
            loan_number=g.loan.loan_number,
            loan_amount_requested=g.loan.amount_requested,
            loan_status=g.loan.status,
        )
        for g in guarantors
    ]


@router.post("/guarantors/{guarantor_id}/respond", response_model=LoanApplicationDetailRead)
def respond_to_guarantee(
    guarantor_id: str,
    payload: GuarantorResponse,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    guarantor = db.get(Guarantor, guarantor_id)
    if not guarantor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guarantor record not found.")
    guarantor.status = GuarantorStatus.ACCEPTED if payload.accept else GuarantorStatus.DECLINED
    guarantor.responded_at = datetime.utcnow()
    db.commit()
    return guarantor.loan


# ---------- Approval Workflow ----------
@router.post("/applications/{loan_id}/decision", response_model=LoanApplicationDetailRead)
def decide_loan_application(
    loan_id: str,
    payload: LoanDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status not in (LoanStatus.PENDING, LoanStatus.UNDER_REVIEW):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Loan is already {loan.status.value}.")

    if payload.approve:
        pending_guarantors = [g for g in loan.guarantors if g.status == GuarantorStatus.PENDING]
        if pending_guarantors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="All guarantors must respond before the loan can be approved.",
            )
        loan.status = LoanStatus.APPROVED
        loan.amount_approved = payload.amount_approved or loan.amount_requested
        loan.approved_by_user_id = current_user.id
    else:
        loan.status = LoanStatus.REJECTED
    loan.reviewed_by_user_id = current_user.id
    db.commit()
    db.refresh(loan)
    return loan


@router.post("/applications/{loan_id}/disburse", response_model=LoanApplicationDetailRead)
def disburse_loan(
    loan_id: str,
    payload: LoanDisbursement,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status != LoanStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only approved loans can be disbursed.")

    principal = loan.amount_approved
    schedule_rows = build_reducing_balance_schedule(
        principal=principal,
        annual_interest_rate_pct=loan.product.interest_rate_annual,
        months=loan.repayment_months,
        start_date=date.today(),
    )
    loan.schedule = [
        LoanRepaymentSchedule(
            installment_number=n,
            due_date=due,
            principal_due=p,
            interest_due=i,
        )
        for n, due, p, i in schedule_rows
    ]

    if payload.disbursement_channel == DisbursementChannel.SAVINGS_ACCOUNT:
        if not payload.disbursement_savings_account_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="disbursement_savings_account_id is required for SAVINGS_ACCOUNT channel.",
            )
        savings_account = db.get(SavingsAccount, payload.disbursement_savings_account_id)
        if not savings_account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disbursement savings account not found.")
        new_balance = savings_account.balance + principal
        db.add(
            SavingsTransaction(
                account_id=savings_account.id,
                txn_type=SavingsTxnType.DEPOSIT,
                amount=principal,
                balance_after=new_balance,
                narrative=f"Loan disbursement {loan.loan_number}",
                performed_by_user_id=current_user.id,
            )
        )
        savings_account.balance = new_balance
        savings_account.last_transaction_at = datetime.utcnow()

    loan.status = LoanStatus.DISBURSED
    loan.disbursement_channel = payload.disbursement_channel
    loan.disbursement_savings_account_id = payload.disbursement_savings_account_id
    loan.disbursed_at = datetime.utcnow()

    db.add(
        LoanTransaction(
            loan_id=loan.id,
            txn_type="disbursement",
            amount=principal,
            narrative=f"Disbursed via {payload.disbursement_channel.value}",
            performed_by_user_id=current_user.id,
        )
    )

    # Loan becomes active once disbursed and the repayment clock starts
    loan.status = LoanStatus.ACTIVE
    db.commit()
    db.refresh(loan)
    return loan


@router.post("/applications/{loan_id}/repayments", response_model=LoanApplicationDetailRead)
def record_loan_repayment(
    loan_id: str,
    payload: LoanRepayment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES, UserRole.TELLER, UserRole.ACCOUNTANT)),
):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status not in (LoanStatus.ACTIVE,):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Loan is not active.")

    remaining = payload.amount
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
            amount=payload.amount,
            narrative=payload.reference,
            performed_by_user_id=current_user.id,
        )
    )

    if all(i.is_paid for i in loan.schedule):
        loan.status = LoanStatus.CLOSED

    db.commit()
    db.refresh(loan)
    return loan
