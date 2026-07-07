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
def declare_dividend( # type: ignore
    payload: DividendDeclarationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)), # type: ignore
):
    """
    Declares a per-share dividend rate and generates a pending payout per
    member holding. Actual payout crediting is a separate finance step
    (kept manual/deliberate given the regulatory sensitivity of dividends).
    """
    declaration = DividendDeclaration(financial_year=payload.financial_year, rate_per_share=payload.rate_per_share)
    db.add(declaration)
    db.flush()

    holdings = db.query(ShareHolding).filter(ShareHolding.number_of_shares > 0).all()
    total = 0
    for holding in holdings:
        amount = holding.number_of_shares * payload.rate_per_share
        total += amount
        db.add(DividendPayout(declaration_id=declaration.id, member_id=holding.member_id, amount=amount))
    declaration.total_amount = total # type: ignore

    record_audit(
        db, actor_user_id=current_user.id, action="shares.dividend_declare", entity_type="DividendDeclaration",
        entity_id=declaration.id,
        details=f"Declared {payload.financial_year} dividend at {payload.rate_per_share}/share, UGX {total} to {len(holdings)} holding(s)",
    )
    db.commit()
    return {"declaration_id": declaration.id, "total_amount": str(total), "members_paid": len(holdings)} # type: ignore
