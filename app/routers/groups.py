"""
Group Management Module endpoints: table-banking style member groups,
membership, and contribution tracking.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import GroupRole, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.group import GroupContribution, GroupMembership, MemberGroup
from app.models.member import Member
from app.models.user import User
from app.schemas.misc import (
    GroupContributionCreate,
    GroupContributionRead,
    GroupCreate,
    GroupMembershipCreate,
    GroupRead,
    MyGroupMembershipRead,
)

router = APIRouter(prefix="/api/v1/groups", tags=["Group Management"])

MANAGER_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


@router.get("/members/{member_id}/memberships", response_model=list[MyGroupMembershipRead])
def list_member_group_memberships(
    member_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    memberships = db.query(GroupMembership).filter(GroupMembership.member_id == member_id).all()
    return [
        MyGroupMembershipRead(
            group_id=m.group_id,
            group_name=m.group.name,
            role=m.role.value,
            joined_date=m.joined_date,
        )
        for m in memberships
    ]


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*MANAGER_ROLES))):
    group = MemberGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("", response_model=list[GroupRead])
def list_groups(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(MemberGroup).filter(MemberGroup.is_active.is_(True)).all()


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
def add_group_member(
    group_id: str,
    payload: GroupMembershipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
):
    group = db.get(MemberGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    member = db.get(Member, payload.member_id)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    try:
        role = GroupRole(payload.role)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid group role.")

    membership = GroupMembership(group_id=group_id, member_id=payload.member_id, role=role)
    db.add(membership)
    db.commit()
    return {"id": membership.id, "group_id": group_id, "member_id": payload.member_id, "role": role.value}


@router.post("/{group_id}/contributions", response_model=GroupContributionRead, status_code=status.HTTP_201_CREATED)
def record_contribution(
    group_id: str,
    payload: GroupContributionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES, UserRole.TELLER)),
):
    group = db.get(MemberGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    contribution = GroupContribution(group_id=group_id, **payload.model_dump())
    db.add(contribution)
    db.commit()
    db.refresh(contribution)
    return contribution


@router.get("/{group_id}/contributions", response_model=list[GroupContributionRead])
def list_contributions(group_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(GroupContribution).filter(GroupContribution.group_id == group_id).all()
