"""
Referral Module endpoints: a member invites a non-member (SMS or email),
and once staff registers that person as a member citing the referral code,
the referrer can be paid a commission - credited straight into their own
savings account, same as any other deposit (so it shows up in their
transaction history and posts to the ledger like everything else).
"""
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import SavingsTxnType, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.member import Member
from app.models.referral import Referral, ReferralStatus
from app.models.savings import SavingsAccount, SavingsTransaction
from app.models.system_settings_model import DEFAULT_SETTINGS_ID, SystemSettings
from app.models.user import User
from app.schemas.referral import (
    PayCommissionRequest,
    ReferralCreate,
    ReferralRead,
    SystemSettingsRead,
    SystemSettingsUpdate,
)
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_savings_transaction_gl
from app.services.transaction_alerts import notify_referral_commission, send_referral_invite

router = APIRouter(prefix="/api/v1/referrals", tags=["Referrals"])
logger = logging.getLogger("sacco.referrals")

MANAGER_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


def get_or_create_system_settings(db: Session) -> SystemSettings:
    settings_row = db.get(SystemSettings, DEFAULT_SETTINGS_ID)
    if not settings_row:
        settings_row = SystemSettings(id=DEFAULT_SETTINGS_ID)
        db.add(settings_row)
        db.flush()
    return settings_row


@router.post("", response_model=ReferralRead, status_code=status.HTTP_201_CREATED)
def create_referral(
    payload: ReferralCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    referrer = db.get(Member, payload.referrer_member_id)
    if not referrer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referring member not found.")

    referral = Referral(
        referrer_member_id=payload.referrer_member_id,
        referred_name=payload.referred_name,
        referred_contact=payload.referred_contact,
        channel=payload.channel,
    )
    db.add(referral)
    db.flush()

    try:
        send_referral_invite(
            referred_contact=payload.referred_contact,
            referred_name=payload.referred_name,
            referrer_name=referrer.full_name,
            referral_code=referral.referral_code,
            channel=payload.channel,
        )
    except Exception as exc:  # noqa: BLE001 - the referral record is still useful even if the invite failed to send
        logger.warning("Referral invite failed to send for referral %s: %s", referral.id, exc)

    record_audit(
        db, actor_user_id=current_user.id, action="referral.invite_sent", entity_type="Referral",
        entity_id=referral.id, details=f"{referrer.member_number} invited {payload.referred_name} via {payload.channel.value}",
    )
    db.commit()
    db.refresh(referral)
    return referral


@router.get("/members/{member_id}", response_model=list[ReferralRead])
def list_member_referrals(member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Referral)
        .filter(Referral.referrer_member_id == member_id)
        .order_by(Referral.invited_at.desc())
        .all()
    )


@router.get("", response_model=list[ReferralRead])
def list_referrals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
    referral_status: ReferralStatus | None = None,
):
    query = db.query(Referral)
    if referral_status:
        query = query.filter(Referral.status == referral_status)
    return query.order_by(Referral.invited_at.desc()).all()


@router.post("/{referral_id}/pay-commission", response_model=ReferralRead)
def pay_referral_commission(
    referral_id: str,
    payload: PayCommissionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referral not found.")
    if referral.status != ReferralStatus.REGISTERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Commission can only be paid once the referred person has registered (current status: {referral.status.value}).",
        )

    account = db.get(SavingsAccount, payload.savings_account_id)
    if not account or account.member_id != referral.referrer_member_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings account not found for the referring member.")

    settings_row = get_or_create_system_settings(db)
    amount = settings_row.referral_commission_amount
    if not amount or amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No referral commission amount is configured - set one in Referrals \u2192 System Settings first.",
        )

    new_balance = account.balance + amount
    txn = SavingsTransaction(
        account_id=account.id,
        txn_type=SavingsTxnType.DEPOSIT,
        amount=amount,
        balance_after=new_balance,
        narrative=f"Referral commission - {referral.referred_name}",
        performed_by_user_id=current_user.id,
    )
    db.add(txn)
    db.flush()
    account.balance = new_balance
    account.last_transaction_at = datetime.utcnow()
    post_savings_transaction_gl(db, account, txn, channel="cash", performed_by_user_id=current_user.id)

    referral.status = ReferralStatus.COMMISSION_PAID
    referral.commission_amount = amount
    referral.commission_paid_savings_account_id = account.id
    referral.commission_paid_at = datetime.utcnow()
    referral.commission_paid_by_user_id = current_user.id

    notify_referral_commission(db, referral.referrer, amount, referral.referred_name)
    record_audit(
        db, actor_user_id=current_user.id, action="referral.commission_paid", entity_type="Referral",
        entity_id=referral.id, details=f"Paid UGX {amount} commission to {referral.referrer.member_number}",
    )
    db.commit()
    db.refresh(referral)
    return referral


# ---------- System Settings (referral commission amount) ----------
@router.get("/system-settings", response_model=SystemSettingsRead)
def get_system_settings(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*MANAGER_ROLES))):
    settings_row = get_or_create_system_settings(db)
    db.commit()
    return settings_row


@router.patch("/system-settings", response_model=SystemSettingsRead)
def update_system_settings(
    payload: SystemSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
):
    settings_row = get_or_create_system_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings_row, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="referral.settings_update", entity_type="SystemSettings",
        entity_id=settings_row.id, details=f"Updated: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(settings_row)
    return settings_row
