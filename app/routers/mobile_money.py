"""
Mobile Money Module endpoints, backed by MarzPay.

Two directions:
- Collections (member -> SACCO): savings deposits, loan repayments. Member
  initiates, MarzPay prompts their phone, webhook confirms.
- Disbursements (SACCO -> member): loan disbursement via mobile money.
  Staff initiates, webhook confirms.

Nothing here credits or debits a real ledger balance until the webhook has
independently re-verified the transaction status with MarzPay's API -
MarzPay does not document a webhook signature scheme, so the callback body
itself is treated as a hint, not a source of truth.
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.enums import DisbursementChannel, LoanStatus, SavingsTxnType, UserRole
from app.dependencies import get_current_user, require_roles
from app.integrations import marzpay
from app.integrations.marzpay import MarzPayError
from app.models.loan import LoanApplication
from app.models.member import Member
from app.models.mobile_money import (
    MobileMoneyDirection,
    MobileMoneyPurpose,
    MobileMoneyStatus,
    MobileMoneyTransaction,
)
from app.models.savings import SavingsAccount, SavingsTransaction
from app.models.user import User
from app.schemas.mobile_money import (
    MobileMoneyDepositRequest,
    MobileMoneyLoanDisbursementRequest,
    MobileMoneyLoanRepaymentRequest,
    MobileMoneyTransactionRead,
    MobileMoneyWithdrawalRequest,
)
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_loan_disbursement_gl, post_loan_repayment_gl, post_savings_transaction_gl
from app.services.loan_disbursement_service import activate_disbursed_loan
from app.services.loan_repayment_service import apply_loan_repayment
from app.services.transaction_alerts import notify_deposit, notify_loan_disbursement, notify_loan_repayment, notify_withdrawal

router = APIRouter(prefix="/api/v1/mobile-money", tags=["Mobile Money"])
logger = logging.getLogger("sacco.mobile_money")

LOAN_OFFICER_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER)


def _callback_url() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/mobile-money/webhook"


# ---------------------------------------------------------------------------
# Collections: member pays the SACCO
# ---------------------------------------------------------------------------
@router.post("/deposits", response_model=MobileMoneyTransactionRead, status_code=status.HTTP_201_CREATED)
def initiate_savings_deposit(
    payload: MobileMoneyDepositRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    account = db.get(SavingsAccount, payload.savings_account_id)
    if not account or account.member_id != member.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found for this member.")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This savings account is closed.")

    phone = payload.phone_number or member.phone_number
    txn = MobileMoneyTransaction(
        direction=MobileMoneyDirection.COLLECTION,
        purpose=MobileMoneyPurpose.SAVINGS_DEPOSIT,
        member_id=member.id,
        savings_account_id=account.id,
        amount=payload.amount,
        phone_number=phone,
        initiated_by_user_id=current_user.id,
    )
    db.add(txn)
    db.flush()  # assigns txn.id, used as the MarzPay reference

    _dispatch_collection(txn, description=f"Savings deposit {account.account_number}")
    record_audit(
        db, actor_user_id=current_user.id, action="mobile_money.deposit_initiate", entity_type="SavingsAccount",
        entity_id=account.id, details=f"Initiated mobile money deposit of {payload.amount}",
    )
    db.commit()
    db.refresh(txn)
    return txn


def _extract_marzpay_data(response: dict) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(response, dict):
        return None, None
    data = response.get("data")
    if not isinstance(data, dict):
        return None, None
    tx_data = data.get("transaction") or {}
    sub_data = data.get("withdrawal") or data.get("disbursement") or data.get("collection") or {}
    uuid = tx_data.get("uuid") if isinstance(tx_data, dict) else None
    provider = sub_data.get("provider") if isinstance(sub_data, dict) else None
    return uuid, provider


@router.post("/withdrawals", response_model=MobileMoneyTransactionRead, status_code=status.HTTP_201_CREATED)
def initiate_savings_withdrawal(
    payload: MobileMoneyWithdrawalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Member-initiated withdrawal: money is sent to the member's phone via
    MarzPay disbursement. The balance is NOT deducted here - only once the
    webhook confirms the disbursement actually succeeded (see
    _finalize_success). This avoids deducting a member's balance for a
    payout that MarzPay later fails to deliver.
    """
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    account = db.get(SavingsAccount, payload.savings_account_id)
    if not account or account.member_id != member.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found for this member.")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This savings account is closed.")

    projected_balance = account.balance - payload.amount
    if projected_balance < account.product.minimum_balance:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Withdrawal would breach minimum balance of {account.product.minimum_balance}.",
        )

    phone = payload.phone_number or member.phone_number
    txn = MobileMoneyTransaction(
        direction=MobileMoneyDirection.DISBURSEMENT,
        purpose=MobileMoneyPurpose.SAVINGS_WITHDRAWAL,
        member_id=member.id,
        savings_account_id=account.id,
        amount=payload.amount,
        phone_number=phone,
        initiated_by_user_id=current_user.id,
    )
    db.add(txn)
    db.flush()

    try:
        response = marzpay.send_money(
            amount=txn.amount,
            phone_number=phone,
            reference=txn.id,
            description=f"Savings withdrawal {account.account_number}",
            callback_url=_callback_url(),
        )
        uuid, provider = _extract_marzpay_data(response)
        txn.marzpay_transaction_uuid = uuid
        txn.provider = provider
        txn.status = MobileMoneyStatus.PROCESSING
    except MarzPayError as exc:
        txn.status = MobileMoneyStatus.FAILED
        txn.failure_reason = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Mobile Money Gateway Error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error during mobile money withdrawal: %s", exc)
        txn.status = MobileMoneyStatus.FAILED
        txn.failure_reason = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Mobile Money Error: {exc}") from exc

    record_audit(
        db, actor_user_id=current_user.id, action="mobile_money.withdrawal_initiate", entity_type="SavingsAccount",
        entity_id=account.id, details=f"Initiated mobile money withdrawal of {payload.amount}",
    )
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/loan-repayments", response_model=MobileMoneyTransactionRead, status_code=status.HTTP_201_CREATED)
def initiate_loan_repayment(
    payload: MobileMoneyLoanRepaymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    loan = db.get(LoanApplication, payload.loan_id)
    if not loan or loan.member_id != member.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found for this member.")
    if loan.status != LoanStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This loan is not active.")

    phone = payload.phone_number or member.phone_number
    txn = MobileMoneyTransaction(
        direction=MobileMoneyDirection.COLLECTION,
        purpose=MobileMoneyPurpose.LOAN_REPAYMENT,
        member_id=member.id,
        loan_id=loan.id,
        amount=payload.amount,
        phone_number=phone,
        initiated_by_user_id=current_user.id,
    )
    db.add(txn)
    db.flush()

    _dispatch_collection(txn, description=f"Loan repayment {loan.loan_number}")
    record_audit(
        db, actor_user_id=current_user.id, action="mobile_money.repayment_initiate", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Initiated mobile money repayment of {payload.amount}",
    )
    db.commit()
    db.refresh(txn)
    return txn


def _dispatch_collection(txn: MobileMoneyTransaction, description: str) -> None:
    try:
        response = marzpay.collect_money(
            amount=txn.amount,
            phone_number=txn.phone_number,
            reference=txn.id,
            description=description,
            callback_url=_callback_url(),
        )
        uuid, provider = _extract_marzpay_data(response)
        txn.marzpay_transaction_uuid = uuid
        txn.provider = provider
        txn.status = MobileMoneyStatus.PROCESSING
    except MarzPayError as exc:
        txn.status = MobileMoneyStatus.FAILED
        txn.failure_reason = str(exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MarzPay error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error during mobile money collection: %s", exc)
        txn.status = MobileMoneyStatus.FAILED
        txn.failure_reason = str(exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Mobile Money Error: {exc}") from exc


# ---------------------------------------------------------------------------
# Disbursements: SACCO pays the member
# ---------------------------------------------------------------------------
@router.post(
    "/loans/{loan_id}/disburse",
    response_model=MobileMoneyTransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def initiate_loan_disbursement(
    loan_id: str,
    payload: MobileMoneyLoanDisbursementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*LOAN_OFFICER_ROLES)),
):
    loan = db.get(LoanApplication, loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found.")
    if loan.status != LoanStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only approved loans can be disbursed.")

    member = loan.member
    phone = payload.phone_number or member.phone_number

    txn = MobileMoneyTransaction(
        direction=MobileMoneyDirection.DISBURSEMENT,
        purpose=MobileMoneyPurpose.LOAN_DISBURSEMENT,
        member_id=member.id,
        loan_id=loan.id,
        amount=loan.amount_approved,
        phone_number=phone,
        initiated_by_user_id=current_user.id,
    )
    db.add(txn)
    db.flush()

    try:
        response = marzpay.send_money(
            amount=txn.amount,
            phone_number=phone,
            reference=txn.id,
            description=f"Loan disbursement {loan.loan_number}",
            callback_url=_callback_url(),
        )
    except MarzPayError as exc:
        txn.status = MobileMoneyStatus.FAILED
        txn.failure_reason = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MarzPay error: {exc}") from exc

    tx_data = response.get("data", {}).get("transaction", {})
    withdrawal_data = response.get("data", {}).get("withdrawal", {}) or response.get("data", {}).get("disbursement", {})
    txn.marzpay_transaction_uuid = tx_data.get("uuid")
    txn.provider = withdrawal_data.get("provider")
    txn.status = MobileMoneyStatus.PROCESSING

    # Loan stays APPROVED (not ACTIVE) until the webhook confirms the money
    # actually left - see activate_disbursed_loan(), called from the webhook.
    record_audit(
        db, actor_user_id=current_user.id, action="mobile_money.disbursement_initiate", entity_type="LoanApplication",
        entity_id=loan.id, details=f"Initiated mobile money disbursement of {txn.amount} to {phone}",
    )
    db.commit()
    db.refresh(txn)
    return txn


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------
@router.get("/transactions/{transaction_id}", response_model=MobileMoneyTransactionRead)
def get_mobile_money_transaction(
    transaction_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    txn = db.get(MobileMoneyTransaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")

    if txn.status == MobileMoneyStatus.PROCESSING and txn.marzpay_transaction_uuid:
        try:
            if txn.direction == MobileMoneyDirection.COLLECTION:
                verified = marzpay.get_collection(txn.marzpay_transaction_uuid)
            else:
                verified = marzpay.get_disbursement(txn.marzpay_transaction_uuid)

            verified_tx = verified.get("data", {}).get("transaction", {})
            verified_status = verified_tx.get("status")
            provider_id = (
                verified.get("data", {}).get("collection", {}).get("provider_transaction_id")
                or verified.get("data", {}).get("disbursement", {}).get("provider_transaction_id")
            )
            if provider_id:
                txn.provider_transaction_id = provider_id

            if verified_status == "completed":
                _finalize_success(db, txn)
                db.commit()
                db.refresh(txn)
            elif verified_status in ("failed", "cancelled"):
                txn.status = MobileMoneyStatus.FAILED if verified_status == "failed" else MobileMoneyStatus.CANCELLED
                txn.failure_reason = f"MarzPay reported status '{verified_status}'."
                db.commit()
                db.refresh(txn)
        except Exception as exc:
            logger.warning("MarzPay status check during transaction polling failed: %s", exc)

    return txn


@router.get("/members/{member_id}/transactions", response_model=list[MobileMoneyTransactionRead])
def list_member_mobile_money_transactions(
    member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return (
        db.query(MobileMoneyTransaction)
        .filter(MobileMoneyTransaction.member_id == member_id)
        .order_by(MobileMoneyTransaction.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Webhook: MarzPay calls this. No auth (MarzPay can't present a bearer
# token) - instead we re-verify the transaction status server-to-server
# before trusting anything in the payload. Always returns 200 so MarzPay
# doesn't retry indefinitely on things we've already handled or don't
# recognize.
# ---------------------------------------------------------------------------
@router.post("/webhook")
async def marzpay_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        logger.warning("MarzPay webhook: could not parse request body as JSON.")
        return {"status": "ignored", "reason": "invalid_json"}

    transaction_info = body.get("transaction") or {}
    reference = transaction_info.get("reference")
    marzpay_uuid = transaction_info.get("uuid")

    if not reference:
        logger.warning("MarzPay webhook: missing transaction.reference in payload.")
        return {"status": "ignored", "reason": "missing_reference"}

    txn = db.get(MobileMoneyTransaction, reference)
    if not txn:
        logger.warning("MarzPay webhook: no local transaction found for reference %s", reference)
        return {"status": "ignored", "reason": "unknown_reference"}

    # Idempotency: webhooks can be delivered more than once.
    if txn.status in (MobileMoneyStatus.COMPLETED, MobileMoneyStatus.FAILED, MobileMoneyStatus.CANCELLED):
        return {"status": "ok", "note": "already_processed"}

    txn.raw_last_callback = json.dumps(body)[:8000]

    # Re-verify with MarzPay directly rather than trusting the callback body.
    try:
        if txn.direction == MobileMoneyDirection.COLLECTION:
            verified = marzpay.get_collection(marzpay_uuid or txn.marzpay_transaction_uuid)
        else:
            verified = marzpay.get_disbursement(marzpay_uuid or txn.marzpay_transaction_uuid)
    except MarzPayError as exc:
        logger.error("MarzPay webhook: verification lookup failed for %s: %s", txn.id, exc)
        db.commit()
        # Don't finalize on an unverifiable callback; MarzPay may retry, or
        # staff can reconcile manually via the status endpoint.
        return {"status": "error", "reason": "verification_failed"}

    verified_tx = verified.get("data", {}).get("transaction", {})
    verified_status = verified_tx.get("status")
    provider_id = (
        verified.get("data", {}).get("collection", {}).get("provider_transaction_id")
        or verified.get("data", {}).get("disbursement", {}).get("provider_transaction_id")
    )
    txn.provider_transaction_id = provider_id

    if verified_status == "completed":
        _finalize_success(db, txn)
    elif verified_status in ("failed", "cancelled"):
        txn.status = MobileMoneyStatus.FAILED if verified_status == "failed" else MobileMoneyStatus.CANCELLED
        txn.failure_reason = f"MarzPay reported status '{verified_status}'."
    else:
        # Still pending/processing per MarzPay's own records - leave as is.
        db.commit()
        return {"status": "ok", "note": "not_yet_final"}

    db.commit()
    return {"status": "ok"}


def _finalize_success(db: Session, txn: MobileMoneyTransaction) -> None:
    txn.status = MobileMoneyStatus.COMPLETED
    txn.confirmed_at = datetime.utcnow()
    member = db.get(Member, txn.member_id)

    if txn.purpose == MobileMoneyPurpose.SAVINGS_DEPOSIT:
        account = db.get(SavingsAccount, txn.savings_account_id)
        if account:
            new_balance = account.balance + txn.amount
            savings_txn = SavingsTransaction(
                account_id=account.id,
                txn_type=SavingsTxnType.DEPOSIT,
                amount=txn.amount,
                balance_after=new_balance,
                narrative="Mobile money deposit",
                reference=txn.provider_transaction_id,
            )
            db.add(savings_txn)
            db.flush()
            account.balance = new_balance
            account.last_transaction_at = datetime.utcnow()
            if account.member:
                account.member.last_activity_at = datetime.utcnow()
            post_savings_transaction_gl(db, account, savings_txn, channel="mobile_money")
            if member:
                notify_deposit(db, member, account.account_number, txn.amount, new_balance)

    elif txn.purpose == MobileMoneyPurpose.SAVINGS_WITHDRAWAL:
        account = db.get(SavingsAccount, txn.savings_account_id)
        if account:
            new_balance = account.balance - txn.amount
            savings_txn = SavingsTransaction(
                account_id=account.id,
                txn_type=SavingsTxnType.WITHDRAWAL,
                amount=txn.amount,
                balance_after=new_balance,
                narrative="Mobile money withdrawal",
                reference=txn.provider_transaction_id,
            )
            db.add(savings_txn)
            db.flush()
            account.balance = new_balance
            account.last_transaction_at = datetime.utcnow()
            if account.member:
                account.member.last_activity_at = datetime.utcnow()
            post_savings_transaction_gl(db, account, savings_txn, channel="mobile_money")
            if member:
                notify_withdrawal(db, member, account.account_number, txn.amount, new_balance)

    elif txn.purpose == MobileMoneyPurpose.LOAN_REPAYMENT:
        loan = db.get(LoanApplication, txn.loan_id)
        if loan and loan.status == LoanStatus.ACTIVE:
            breakdown = apply_loan_repayment(db, loan, txn.amount, narrative="Mobile money repayment")
            post_loan_repayment_gl(
                db, loan, principal_paid=breakdown.principal_paid, interest_paid=breakdown.interest_paid,
                penalty_paid=breakdown.penalty_paid, channel="mobile_money",
            )
            if member:
                notify_loan_repayment(db, member, loan.loan_number, txn.amount)

    elif txn.purpose == MobileMoneyPurpose.LOAN_DISBURSEMENT:
        loan = db.get(LoanApplication, txn.loan_id)
        if loan:
            activate_disbursed_loan(
                db,
                loan,
                channel=DisbursementChannel.MOBILE_MONEY,
                narrative=f"Mobile money disbursement (MarzPay ref {txn.provider_transaction_id})",
            )
            post_loan_disbursement_gl(db, loan, channel=DisbursementChannel.MOBILE_MONEY)
            if member:
                notify_loan_disbursement(db, member, loan.loan_number, txn.amount)

    record_audit(
        db, actor_user_id=txn.initiated_by_user_id, action=f"mobile_money.{txn.purpose.value}_confirmed",
        entity_type="MobileMoneyTransaction", entity_id=txn.id,
        details=f"Confirmed {txn.direction.value} of {txn.amount} (MarzPay ref {txn.provider_transaction_id})",
    )
