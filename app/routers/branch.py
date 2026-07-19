"""
Branch Module endpoints: minimal CRUD for real branches, replacing the
frontend's fake hash-based branch assignment (see app/models/branch.py
docstring for why that was a real problem, not just a placeholder).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.dependencies import get_current_user, require_roles
from app.models.branch import Branch
from app.models.user import User
from app.schemas.branch import BranchCreate, BranchRead, BranchUpdate
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/branches", tags=["Branches"])

MANAGER_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


@router.post("", response_model=BranchRead, status_code=status.HTTP_201_CREATED)
def create_branch(
    payload: BranchCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*MANAGER_ROLES))
):
    if db.query(Branch).filter(Branch.code == payload.code).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A branch with this code already exists.")
    branch = Branch(**payload.model_dump())
    db.add(branch)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="branch.create", entity_type="Branch",
        entity_id=branch.id, details=f"Created branch {branch.code} - {branch.name}",
    )
    db.commit()
    db.refresh(branch)
    return branch


@router.get("", response_model=list[BranchRead])
def list_branches(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Branch).filter(Branch.is_active.is_(True)).all()


@router.patch("/{branch_id}", response_model=BranchRead)
def update_branch(
    branch_id: str,
    payload: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGER_ROLES)),
):
    branch = db.get(Branch, branch_id)
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="branch.update", entity_type="Branch",
        entity_id=branch.id, details=f"Updated {branch.code}: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(branch)
    return branch
