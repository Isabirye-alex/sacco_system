"""
Credit / Loan Management endpoints: product setup, applications, guarantor
workflow, approval/rejection, disbursement, and repayments. Disbursement and
repayment operations post balancing entries to the general ledger.
"""
from datetime import datetime
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
from app.models.loan import Collateral, Guarantor, LoanApplication, LoanProduct, LoanTransaction
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
    LoanProductUpdate,
    LoanRepayment,
    LoanTransactionRead,
    RepaymentScheduleRead,
)
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_loan_disbursement_gl, post_loan_repayment_gl
from app.services.loan_disbursement_service import activate_disbursed_loan
from app.services.loan_repayment_service import apply_loan_repayment
from app.services.numbering import generate_loan_number
from app.services.transaction_alerts import notify_loan_disbursement, notify_loan_repayment

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
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="loans.product_create", entity_type="LoanProduct",
        entity_id=product.id, details=f"Created product {product.name}",
    )
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[LoanProductRead])
def list_loan_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(LoanProduct).filter(LoanProduct.is_active.is_(True)).all()


@router.patch("/products/{product_id}", response_model=LoanProductRead)
def update_loan_product(
    product_id: str,
    payload: LoanProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Mainly used to link/relink a product's GL asset account - see app/services/gl_posting_service.py."""
    product = db.get(LoanProduct, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan product not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="loans.product_update", entity_type="LoanProduct",
        entity_id=product.id, details=f"Updated {product.name}: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(product)
    return product


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
        record_audit(
            db, actor_user_id=current_user.id, action="loan.approve", entity_type="LoanApplication",
            entity_id=loan.id, details=f"Approved {loan.loan_number} for {loan.amount_approved}. Notes: {payload.notes or '-'}",
        )
    else:
        loan.status = LoanStatus.REJECTED
        record_audit(
            db, actor_user_id=current_user.id, action="loan.reject", entity_type="LoanApplication",
            entity_id=loan.id, details=f"Rejected {loan.loan_number}. Notes: {payload.notes or '-'}",
        )
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

    savings_account = None
    if payload.disbursement_channel == DisbursementChannel.SAVINGS_ACCOUNT:
        if not payload.disbursement_savings_account_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="disbursement_savings_account_id is required for SAVINGS_ACCOUNT channel.",
            )
        savings_account = db.get(SavingsAccount, payload.disbursement_savings_account_id)
        if not savings_account:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disbursement savings account not found.")
        new_balance = savings_account.balance + loan.amount_approved
        db.add(
            SavingsTransaction(
                account_id=savings_account.id,
                txn_type=SavingsTxnType.DEPOSIT,
                amount=loan.amount_approved,
                balance_after=new_balance,
                narrative=f"Loan disbursement {loan.loan_number}",
                performed_by_user_id=current_user.id,
            )
        )
        savings_account.balance = new_balance
        savings_account.last_transaction_at = datetime.utcnow()
    elif payload.disbursement_channel == DisbursementChannel.MOBILE_MONEY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Use POST /api/v1/mobile-money/loans/{loan_id}/disburse for mobile money disbursements - "
                "it must go through MarzPay and confirm via webhook before the loan is activated."
            ),
        )

    activate_disbursed_loan(
        db,
        loan,
        channel=payload.disbursement_channel,
        savings_account_id=payload.disbursement_savings_account_id,
        performed_by_user_id=current_user.id,
    )

    post_loan_disbursement_gl(
        db, loan, channel=payload.disbursement_channel,
        disbursement_savings_account=savings_account, performed_by_user_id=current_user.id,
    )
    notify_loan_disbursement(db, loan.member, loan.loan_number, loan.amount_approved)
    record_audit(
        db, actor_user_id=current_user.id, action="loan.disburse", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Disbursed {loan.loan_number} via {payload.disbursement_channel.value}",
    )

    db.commit()
    db.refresh(loan)
    return loan


@router.get("/applications/{loan_id}/transactions", response_model=list[LoanTransactionRead])
def list_loan_transactions(loan_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Disbursement and repayment history for a loan, including who performed each one."""
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    return (
        db.query(LoanTransaction)
        .filter(LoanTransaction.loan_id == loan_id)
        .order_by(LoanTransaction.created_at.desc())
        .all()
    )


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

    breakdown = apply_loan_repayment(
        db, loan, payload.amount, narrative=payload.reference, performed_by_user_id=current_user.id
    )
    post_loan_repayment_gl(
        db, loan,
        principal_paid=breakdown.principal_paid, interest_paid=breakdown.interest_paid,
        penalty_paid=breakdown.penalty_paid, channel=payload.channel, performed_by_user_id=current_user.id,
    )

    notify_loan_repayment(db, loan.member, loan.loan_number, payload.amount)
    record_audit(
        db, actor_user_id=current_user.id, action="loan.repayment", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Repayment of {payload.amount} on {loan.loan_number}",
    )

    db.commit()
    db.refresh(loan)
    return loan
