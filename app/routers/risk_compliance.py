"""
Risk & Compliance Module endpoints: risk flag case management, portfolio-at-
risk (PAR) reporting, and manual dormancy sweep trigger.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import RiskFlagStatus, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.risk_compliance import RiskFlag
from app.models.user import User
from app.schemas.misc import RiskFlagCreate, RiskFlagRead, RiskFlagResolve
from app.services.audit_service import record_audit
from app.services.risk_service import calculate_portfolio_at_risk, sweep_dormant_members # type: ignore

router = APIRouter(prefix="/api/v1/risk", tags=["Risk & Compliance"])

RISK_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.AUDITOR)


@router.post("/flags", response_model=RiskFlagRead, status_code=status.HTTP_201_CREATED)
def raise_risk_flag(
    payload: RiskFlagCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    flag = RiskFlag(**payload.model_dump())
    db.add(flag)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="risk.flag_raise", entity_type="RiskFlag",
        entity_id=flag.id, details=f"Raised {flag.flag_type.value}: {flag.description}",
    )
    db.commit()
    db.refresh(flag)
    return flag


@router.get("/flags", response_model=list[RiskFlagRead])
def list_risk_flags(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RISK_ROLES)), # type: ignore
    flag_status: RiskFlagStatus | None = None,
):
    query = db.query(RiskFlag)
    if flag_status:
        query = query.filter(RiskFlag.status == flag_status)
    return query.order_by(RiskFlag.created_at.desc()).all()


@router.post("/flags/{flag_id}/resolve", response_model=RiskFlagRead)
def resolve_risk_flag(
    flag_id: str,
    payload: RiskFlagResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RISK_ROLES)), # type: ignore
):
    flag = db.get(RiskFlag, flag_id)
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk flag not found.")
    flag.status = RiskFlagStatus.RESOLVED
    flag.resolution_notes = payload.resolution_notes
    flag.resolved_by_user_id = current_user.id
    flag.resolved_at = datetime.utcnow() # type: ignore
    record_audit(
        db, actor_user_id=current_user.id, action="risk.flag_resolve", entity_type="RiskFlag",
        entity_id=flag.id, details=f"Resolved: {payload.resolution_notes}",
    )
    db.commit()
    db.refresh(flag)
    return flag


@router.get("/portfolio-at-risk")
def portfolio_at_risk(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*RISK_ROLES))): # type: ignore
    return calculate_portfolio_at_risk(db) # type: ignore


@router.post("/dormancy-sweep")
def trigger_dormancy_sweep(
    db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)) # type: ignore
):
    """Manually triggers the dormancy sweep (also runs automatically on a schedule, see app/main.py)."""
    count = sweep_dormant_members(db)
    record_audit(
        db, actor_user_id=current_user.id, action="risk.dormancy_sweep_manual", entity_type="Member",
        details=f"Manually triggered dormancy sweep: {count} member(s) flagged",
    )
    db.commit()
    return {"members_flagged_dormant": count}
