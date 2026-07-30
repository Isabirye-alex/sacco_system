from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional
import uuid
import calendar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.member import Member
from app.models.vault import TargetVault
from app.models.user import User
from app.schemas.vault import (
    VaultCreate,
    VaultDeposit,
    VaultWithdraw,
    VaultResponse,
    VaultSummary,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/vaults", tags=["Target Vaults"])


def _add_months(sourcedate: date, months: int) -> date:
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_vault_account_number(db: Session) -> str:
    # Generates e.g. VLT-83920145
    while True:
        num = f"VLT-{uuid.uuid4().hex[:8].upper()}"
        existing = db.query(TargetVault).filter(TargetVault.account_number == num).first()
        if not existing:
            return num


@router.post("", response_model=VaultResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=VaultResponse, status_code=status.HTTP_201_CREATED)
def create_target_vault(
    payload: VaultCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(Member).filter(Member.id == payload.member_id).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_444_NOT_FOUND if hasattr(status, "HTTP_444_NOT_FOUND") else 404,
            detail=f"Member with ID '{payload.member_id}' not found.",
        )

    account_num = _generate_vault_account_number(db)
    today = date.today()
    maturity = _add_months(today, payload.lock_period_months)

    vault = TargetVault(
        id=str(uuid.uuid4()),
        account_number=account_num,
        member_id=payload.member_id,
        name=payload.name,
        vault_type=payload.vault_type,
        target_amount=payload.target_amount,
        current_balance=Decimal("0.00"),
        interest_rate_annual=payload.interest_rate_annual,
        early_withdrawal_penalty_pct=payload.early_withdrawal_penalty_pct,
        lock_period_months=payload.lock_period_months,
        start_date=today,
        maturity_date=maturity,
        is_locked=True,
        status="ACTIVE",
    )

    db.add(vault)
    record_audit(
        db,
        actor_user_id=current_user.id,
        action="vault.created",
        entity_type="TargetVault",
        entity_id=vault.id,
        details=f"Created target vault '{vault.name}' ({vault.vault_type}) with target UGX {vault.target_amount}",
    )
    db.commit()
    db.refresh(vault)
    return vault


@router.get("", response_model=List[VaultResponse])
@router.get("/", response_model=List[VaultResponse])
def list_target_vaults(
    member_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(TargetVault)
    if member_id:
        query = query.filter(TargetVault.member_id == member_id)
    if status_filter:
        query = query.filter(TargetVault.status == status_filter.upper())

    return query.order_by(TargetVault.created_at.desc()).all()


@router.get("/member/{member_id}/summary", response_model=VaultSummary)
def get_member_vault_summary(
    member_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vaults = db.query(TargetVault).filter(TargetVault.member_id == member_id).all()
    
    total_vaults = len(vaults)
    active_vaults = sum(1 for v in vaults if v.status == "ACTIVE")
    matured_vaults = sum(1 for v in vaults if v.status == "MATURED")
    
    total_target = sum((v.target_amount for v in vaults), Decimal("0.00"))
    total_balance = sum((v.current_balance for v in vaults), Decimal("0.00"))

    progress = (total_balance / total_target * Decimal("100.00")) if total_target > Decimal("0.00") else Decimal("0.00")

    return VaultSummary(
        total_vaults=total_vaults,
        active_vaults=active_vaults,
        matured_vaults=matured_vaults,
        total_target_amount=total_target,
        total_current_balance=total_balance,
        overall_progress_pct=round(progress, 2),
    )


@router.get("/{vault_id}", response_model=VaultResponse)
def get_vault_details(
    vault_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vault = db.query(TargetVault).filter(TargetVault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Target vault not found.")
    return vault


@router.post("/{vault_id}/deposit", response_model=VaultResponse)
def deposit_into_vault(
    vault_id: str,
    payload: VaultDeposit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vault = db.query(TargetVault).filter(TargetVault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Target vault not found.")
    
    if vault.status != "ACTIVE":
        raise HTTPException(status_code=400, detail=f"Cannot deposit into a vault with status '{vault.status}'.")

    vault.current_balance += payload.amount
    
    # Auto-check if target amount is reached or matured
    if vault.current_balance >= vault.target_amount:
        vault.status = "MATURED"
        vault.is_locked = False

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="vault.deposit",
        entity_type="TargetVault",
        entity_id=vault.id,
        details=f"Deposited UGX {payload.amount} into vault '{vault.name}'. New balance: UGX {vault.current_balance}",
    )
    db.commit()
    db.refresh(vault)
    return vault


@router.post("/{vault_id}/withdraw", response_model=VaultResponse)
def withdraw_from_vault(
    vault_id: str,
    payload: VaultWithdraw,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vault = db.query(TargetVault).filter(TargetVault.id == vault_id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Target vault not found.")

    if vault.current_balance <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Vault balance is zero.")

    withdraw_amount = payload.amount if payload.amount is not None else vault.current_balance
    if withdraw_amount > vault.current_balance:
        raise HTTPException(status_code=400, detail="Withdrawal amount exceeds current vault balance.")

    today = date.today()
    is_early = vault.maturity_date and today < vault.maturity_date and vault.is_locked

    if is_early and not payload.force_early_withdrawal:
        penalty = (withdraw_amount * (vault.early_withdrawal_penalty_pct / Decimal("100.00"))).quantize(Decimal("0.01"))
        net_payout = withdraw_amount - penalty
        raise HTTPException(
            status_code=400,
            detail=(
                f"Vault is locked until {vault.maturity_date}. Early withdrawal incurs a "
                f"{vault.early_withdrawal_penalty_pct}% penalty (UGX {penalty}). "
                f"Net payout would be UGX {net_payout}. Set 'force_early_withdrawal': true to confirm."
            ),
        )

    penalty = Decimal("0.00")
    if is_early:
        penalty = (withdraw_amount * (vault.early_withdrawal_penalty_pct / Decimal("100.00"))).quantize(Decimal("0.01"))
        vault.status = "BROKEN"

    vault.current_balance -= withdraw_amount
    if vault.current_balance == Decimal("0.00") and vault.status != "BROKEN":
        vault.status = "MATURED"

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="vault.withdraw",
        entity_type="TargetVault",
        entity_id=vault.id,
        details=f"Withdrew UGX {withdraw_amount} (penalty UGX {penalty}) from vault '{vault.name}'. Status: {vault.status}",
    )
    db.commit()
    db.refresh(vault)
    return vault
