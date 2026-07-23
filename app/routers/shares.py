"""
Shares Management Module endpoints: share products, member holdings,
subscription/transfer/redemption transactions, and dividend declarations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import ShareTxnType, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.member import Member
from app.models.shares import DividendDeclaration, DividendPayout, ShareHolding, ShareProduct, ShareTransaction
from app.models.user import User
from app.schemas.misc import (
    DividendDeclarationCreate,
    ShareHoldingRead,
    ShareProductCreate,
    ShareProductRead,
    ShareTransactionCreate,
    ShareTransactionRead,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/shares", tags=["Shares Management"])

MANAGER_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


@router.post("/products", response_model=ShareProductRead, status_code=status.HTTP_201_CREATED)
def create_share_product(
    payload: ShareProductCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*MANAGER_ROLES)) # type: ignore
):
    product = ShareProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ShareProductRead])
def list_share_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ShareProduct).filter(ShareProduct.is_active.is_(True)).all()


@router.get("/members/{member_id}/holdings", response_model=list[ShareHoldingRead])
def list_member_holdings(member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ShareHolding).filter(ShareHolding.member_id == member_id).all()


@router.post(
    "/members/{member_id}/products/{product_id}/transactions",
    response_model=ShareTransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def record_share_transaction(
    member_id: str,
    product_id: str,
    payload: ShareTransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES, UserRole.ACCOUNTANT)), # type: ignore
):
    member = db.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    product = db.get(ShareProduct, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share product not found.")

    holding = (
        db.query(ShareHolding)
        .filter(ShareHolding.member_id == member_id, ShareHolding.product_id == product_id)
        .first()
    )
    if not holding:
        holding = ShareHolding(member_id=member_id, product_id=product_id, number_of_shares=0)
        db.add(holding)
        db.flush()

    amount = product.nominal_value * payload.number_of_shares

    if payload.txn_type == ShareTxnType.SUBSCRIPTION:
        holding.number_of_shares += payload.number_of_shares
    elif payload.txn_type == ShareTxnType.REDEMPTION:
        if payload.number_of_shares > holding.number_of_shares:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Insufficient shares to redeem.")
        holding.number_of_shares -= payload.number_of_shares
    elif payload.txn_type == ShareTxnType.TRANSFER:
        if not payload.counterparty_member_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="counterparty_member_id is required for transfers.")
        if payload.number_of_shares > holding.number_of_shares:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Insufficient shares to transfer.")
        counterparty_holding = (
            db.query(ShareHolding)
            .filter(ShareHolding.member_id == payload.counterparty_member_id, ShareHolding.product_id == product_id)
            .first()
        )
        if not counterparty_holding:
            counterparty_holding = ShareHolding(
                member_id=payload.counterparty_member_id, product_id=product_id, number_of_shares=0
            )
            db.add(counterparty_holding)
        holding.number_of_shares -= payload.number_of_shares
        counterparty_holding.number_of_shares += payload.number_of_shares

    txn = ShareTransaction(
        holding_id=holding.id,
        txn_type=payload.txn_type,
        number_of_shares=payload.number_of_shares,
        amount=amount,
        counterparty_member_id=payload.counterparty_member_id,
        board_approved=False,
    )
    db.add(txn)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action=f"shares.{payload.txn_type.value}", entity_type="ShareHolding",
        entity_id=holding.id, details=f"{payload.txn_type.value} of {payload.number_of_shares} share(s) for {member.member_number}",
    )
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/dividends/declare", status_code=status.HTTP_201_CREATED)
def declare_dividend(
    payload: DividendDeclarationCreate,
    reinvest_to_savings: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
):
    """
    Declares a per-share dividend rate and generates a payout per member holding.
    If `reinvest_to_savings=True`, payouts are automatically credited directly into member savings accounts.
    """
    from datetime import datetime
    from app.models.savings import SavingsAccount, SavingsTransaction
    from app.core.enums import SavingsTxnType
    from app.services.gl_posting_service import post_savings_transaction_gl

    declaration = DividendDeclaration(financial_year=payload.financial_year, rate_per_share=payload.rate_per_share)
    db.add(declaration)
    db.flush()

    holdings = db.query(ShareHolding).filter(ShareHolding.number_of_shares > 0).all()
    total = 0
    reinvested_count = 0

    for holding in holdings:
        amount = holding.number_of_shares * payload.rate_per_share
        total += amount
        payout = DividendPayout(declaration_id=declaration.id, member_id=holding.member_id, amount=amount)

        if reinvest_to_savings:
            savings_acc = db.query(SavingsAccount).filter(
                SavingsAccount.member_id == holding.member_id,
                SavingsAccount.is_active.is_(True)
            ).first()
            if savings_acc:
                new_bal = savings_acc.balance + amount
                txn = SavingsTransaction(
                    account_id=savings_acc.id,
                    txn_type=SavingsTxnType.DEPOSIT,
                    amount=amount,
                    balance_after=new_bal,
                    narrative=f"Dividend Reinvestment ({payload.financial_year})",
                    performed_by_user_id=current_user.id,
                )
                savings_acc.balance = new_bal
                savings_acc.last_transaction_at = datetime.utcnow()
                db.add(txn)
                db.flush()
                post_savings_transaction_gl(db, savings_acc, txn, performed_by_user_id=current_user.id)
                payout.paid_at = datetime.utcnow()
                payout.payment_reference = f"REINVEST-{savings_acc.account_number}"
                reinvested_count += 1

        db.add(payout)

    declaration.total_amount = total

    record_audit(
        db, actor_user_id=current_user.id, action="shares.dividend_declare", entity_type="DividendDeclaration",
        entity_id=declaration.id,
        details=f"Declared {payload.financial_year} dividend at {payload.rate_per_share}/share, total UGX {total} across {len(holdings)} holding(s). Reinvested: {reinvested_count}",
    )
    db.commit()
    return {
        "declaration_id": declaration.id,
        "total_amount": str(total),
        "members_paid": len(holdings),
        "reinvested_to_savings": reinvested_count,
    }
