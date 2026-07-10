"""
Savings Module endpoints: products, accounts, and transactions.
Deposits/withdrawals atomically update the account balance and post a
balancing entry to the general ledger.
"""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import SavingsTxnType, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.member import Member
from app.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction
from app.models.user import User
from app.schemas.savings import (
    SavingsAccountCreate,
    SavingsAccountRead,
    SavingsProductCreate,
    SavingsProductRead,
    SavingsProductUpdate,
    SavingsTransactionCreate,
    SavingsTransactionRead,
)
from app.services.numbering import generate_savings_account_number
from app.services.transaction_alerts import notify_deposit, notify_withdrawal
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_savings_transaction_gl

router = APIRouter(prefix="/api/v1/savings", tags=["Savings"])

TELLER_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.TELLER, UserRole.ACCOUNTANT)


# ---------- Savings Products ----------
@router.post("/products", response_model=SavingsProductRead, status_code=status.HTTP_201_CREATED)
def create_savings_product(
    payload: SavingsProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    product = SavingsProduct(**payload.model_dump())
    db.add(product)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="savings.product_create", entity_type="SavingsProduct",
        entity_id=product.id, details=f"Created product {product.name} ({product.product_type})",
    )
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[SavingsProductRead])
def list_savings_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(SavingsProduct).filter(SavingsProduct.is_active.is_(True)).all()


@router.patch("/products/{product_id}", response_model=SavingsProductRead)
def update_savings_product(
    product_id: str,
    payload: SavingsProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Mainly used to link/relink a product's GL liability account - see app/services/gl_posting_service.py."""
    product = db.get(SavingsProduct, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings product not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="savings.product_update", entity_type="SavingsProduct",
        entity_id=product.id, details=f"Updated {product.name}: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(product)
    return product


# ---------- Savings Accounts ----------
@router.post("/accounts", response_model=SavingsAccountRead, status_code=status.HTTP_201_CREATED)
def open_savings_account(
    payload: SavingsAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*TELLER_ROLES)),
):
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    product = db.get(SavingsProduct, payload.product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings product not found or inactive.")

    account = SavingsAccount(
        account_number=generate_savings_account_number(),
        member_id=payload.member_id,
        product_id=payload.product_id,
        target_amount=payload.target_amount,
    )
    db.add(account)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="savings.account_open", entity_type="SavingsAccount",
        entity_id=account.id, details=f"Opened {account.account_number} for {member.member_number} ({product.name})",
    )
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts/{account_id}", response_model=SavingsAccountRead)
def get_savings_account(
    account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    account = db.get(SavingsAccount, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found.")
    return account


@router.get("/members/{member_id}/accounts", response_model=list[SavingsAccountRead])
def list_member_savings_accounts(
    member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return db.query(SavingsAccount).filter(SavingsAccount.member_id == member_id).all()


# ---------- Transactions ----------
@router.post(
    "/accounts/{account_id}/transactions",
    response_model=SavingsTransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def post_savings_transaction(
    account_id: str,
    payload: SavingsTransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*TELLER_ROLES)),
):
    account = db.get(SavingsAccount, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found or inactive.")

    is_credit = payload.txn_type in (
        SavingsTxnType.DEPOSIT,
        SavingsTxnType.INTEREST_POSTING,
        SavingsTxnType.TRANSFER_IN,
    )
    new_balance = account.balance + payload.amount if is_credit else account.balance - payload.amount

    if not is_credit and new_balance < account.product.minimum_balance:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Withdrawal would breach minimum balance of {account.product.minimum_balance}.",
        )

    txn = SavingsTransaction(
        account_id=account.id,
        txn_type=payload.txn_type,
        amount=payload.amount,
        balance_after=new_balance,
        narrative=payload.narrative,
        reference=payload.reference,
        performed_by_user_id=current_user.id,
    )
    account.balance = new_balance
    account.last_transaction_at = datetime.utcnow()
    account.member.last_activity_at = datetime.utcnow()
    db.add(txn)
    db.flush()  # assigns txn.id, needed below both as a JournalEntry source reference and for the response

    post_savings_transaction_gl(db, account, txn, channel=payload.channel, performed_by_user_id=current_user.id)

    if payload.txn_type == SavingsTxnType.DEPOSIT:
        notify_deposit(db, account.member, account.account_number, payload.amount, new_balance)
    elif payload.txn_type == SavingsTxnType.WITHDRAWAL:
        notify_withdrawal(db, account.member, account.account_number, payload.amount, new_balance)

    record_audit(
        db, actor_user_id=current_user.id, action=f"savings.{payload.txn_type.value}",
        entity_type="SavingsAccount", entity_id=account.id,
        details=f"{payload.txn_type.value} of {payload.amount} on {account.account_number}",
    )

    db.commit()
    db.refresh(txn)
    return txn


@router.get("/accounts/{account_id}/transactions", response_model=list[SavingsTransactionRead])
def list_savings_transactions(
    account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    account = db.get(SavingsAccount, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found.")
    return account.transactions
