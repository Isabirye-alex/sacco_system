"""
Member Management endpoints.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import MemberStatus, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.member import Member, NextOfKin, TrustedContact
from app.models.referral import Referral, ReferralStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.member import MemberCreate, MemberDetailRead, MemberRead, MemberUpdate
from app.services.numbering import generate_member_number
from app.services.audit_service import record_audit
from app.services.transaction_alerts import notify_member_status_change, notify_new_member


router = APIRouter(prefix="/api/v1/members", tags=["Member Management"])

STAFF_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER, UserRole.TELLER)


@router.post("", response_model=MemberDetailRead, status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    if db.query(Member).filter(Member.national_id == payload.national_id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A member with this national ID already exists.")

    referral = None
    if payload.referral_code:
        referral = db.query(Referral).filter(Referral.referral_code == payload.referral_code.upper()).first()
        if not referral:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referral code not found.")
        if referral.status != ReferralStatus.INVITED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This referral code has already been used (status: {referral.status.value}).",
            )

    member = Member(
        member_number=generate_member_number(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        national_id=payload.national_id,
        date_of_birth=payload.date_of_birth,
        phone_number=payload.phone_number,
        email=payload.email,
        physical_address=payload.physical_address,
        occupation=payload.occupation,
        employer_id=payload.employer_id,
        last_activity_at=datetime.utcnow(),
    )
    member.next_of_kin = [NextOfKin(**nok.model_dump()) for nok in payload.next_of_kin]
    member.trusted_contacts = [TrustedContact(**tc.model_dump()) for tc in payload.trusted_contacts]

    db.add(member)
    db.flush()

    if referral:
        referral.status = ReferralStatus.REGISTERED
        referral.registered_member_id = member.id
        referral.registered_at = datetime.utcnow()
        record_audit(
            db, actor_user_id=current_user.id, action="referral.registered", entity_type="Referral",
            entity_id=referral.id, details=f"{member.member_number} registered via referral code {referral.referral_code}",
        )

    record_audit(
        db, actor_user_id=current_user.id, action="member.create", entity_type="Member",
        entity_id=member.id, details=f"Created member {member.member_number} ({member.first_name} {member.last_name})",
    )
    notify_new_member(db, member)
    db.commit()
    db.refresh(member)
    return member


@router.get("", response_model=Page[MemberRead])
def list_members(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    q: str | None = Query(None, description="Search by name, member number, or national ID"),
    status_filter: MemberStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
):
    stmt = select(Member)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Member.first_name.ilike(like),
                Member.last_name.ilike(like),
                Member.member_number.ilike(like),
                Member.national_id.ilike(like),
            )
        )
    if status_filter:
        stmt = stmt.where(Member.status == status_filter)

    total = len(db.scalars(stmt).all())
    items = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{member_id}", response_model=MemberDetailRead)
def get_member(member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    member = db.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    return member


@router.patch("/{member_id}", response_model=MemberDetailRead)
def update_member(
    member_id: str,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    member = db.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(member, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="member.update", entity_type="Member",
        entity_id=member.id, details=f"Updated fields: {', '.join(changes.keys())}",
    )
    if "status" in changes and changes["status"]:
        new_st = str(changes["status"].value if hasattr(changes["status"], "value") else changes["status"])
        notify_member_status_change(db, member, new_st)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def exit_member(
    member_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Soft-delete: marks the member as EXITED rather than removing records (audit trail)."""
    member = db.get(Member, member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    member.status = MemberStatus.EXITED
    notify_member_status_change(db, member, "EXITED")
    record_audit(
        db, actor_user_id=current_user.id, action="member.exit", entity_type="Member",
        entity_id=member.id, details=f"Exited member {member.member_number}",
    )
    db.commit()
