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
from app.services.audit_service import record_audit

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
def create_group(payload: GroupCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*MANAGER_ROLES))): # type: ignore
    group = MemberGroup(**payload.model_dump())
    db.add(group)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="group.create", entity_type="MemberGroup",
        entity_id=group.id, details=f"Created group {group.name}",
    )
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
    current_user: User = Depends(require_roles(*MANAGER_ROLES)), # type: ignore
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
    record_audit(
        db, actor_user_id=current_user.id, action="group.member_add", entity_type="MemberGroup",
        entity_id=group_id, details=f"Added {member.member_number} to {group.name} as {role.value}",
    )
    db.commit()
    return {"id": membership.id, "group_id": group_id, "member_id": payload.member_id, "role": role.value}


@router.post("/{group_id}/contributions", response_model=GroupContributionRead, status_code=status.HTTP_201_CREATED)
def record_contribution(
    group_id: str,
    payload: GroupContributionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES, UserRole.TELLER)), # type: ignore
):
    group = db.get(MemberGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    contribution = GroupContribution(group_id=group_id, **payload.model_dump())
    db.add(contribution)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="group.contribution_record", entity_type="MemberGroup",
        entity_id=group_id, details=f"Recorded contribution of {payload.amount} in {group.name}",
    )
    db.commit()
    db.refresh(contribution)
    return contribution


@router.get("/{group_id}/contributions", response_model=list[GroupContributionRead])
def list_contributions(group_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(GroupContribution).filter(GroupContribution.group_id == group_id).all()


# ---------- Group Meetings & Attendance ----------
from datetime import date
from typing import Optional
from pydantic import BaseModel

class AttendanceItemCreate(BaseModel):
    member_id: str
    is_present: bool = True
    notes: Optional[str] = None

class GroupMeetingCreate(BaseModel):
    meeting_date: date
    location: Optional[str] = None
    minutes: Optional[str] = None
    attendance: list[AttendanceItemCreate] = []


@router.post("/{group_id}/meetings", status_code=status.HTTP_201_CREATED)
def record_group_meeting(
    group_id: str,
    payload: GroupMeetingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES, UserRole.LOAN_OFFICER)),
):
    """
    Records a group meeting with minutes and member attendance logs.
    """
    from app.models.group import GroupAttendance, GroupMeeting

    group = db.get(MemberGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")

    meeting = GroupMeeting(
        group_id=group_id,
        meeting_date=payload.meeting_date,
        location=payload.location,
        minutes=payload.minutes,
    )
    db.add(meeting)
    db.flush()

    for item in payload.attendance:
        db.add(
            GroupAttendance(
                meeting_id=meeting.id,
                member_id=item.member_id,
                is_present=item.is_present,
                notes=item.notes,
            )
        )

    record_audit(
        db, actor_user_id=current_user.id, action="group.meeting_record", entity_type="GroupMeeting",
        entity_id=meeting.id, details=f"Recorded meeting on {payload.meeting_date} for group {group.name}",
    )
    db.commit()
    return {"meeting_id": meeting.id, "group_id": group_id, "attendance_count": len(payload.attendance)}


@router.get("/{group_id}/meetings")
def list_group_meetings(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.group import GroupMeeting

    group = db.get(MemberGroup, group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")

    meetings = db.query(GroupMeeting).filter(GroupMeeting.group_id == group_id).all()
    return [
        {
            "meeting_id": m.id,
            "meeting_date": m.meeting_date,
            "location": m.location,
            "minutes": m.minutes,
            "attendance": [
                {
                    "member_id": a.member_id,
                    "is_present": a.is_present,
                    "notes": a.notes,
                }
                for a in m.attendance
            ],
        }
        for m in meetings
    ]
