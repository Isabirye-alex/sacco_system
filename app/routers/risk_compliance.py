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
from app.models.risk_compliance import ComplianceReport, RiskFlag
from app.models.user import User
from app.schemas.misc import (
    ComplianceReportCreate,
    ComplianceReportRead,
    RiskFlagCreate,
    RiskFlagRead,
    RiskFlagResolve,
)
from app.services.audit_service import record_audit
from app.services.loan_penalty_service import apply_overdue_penalties
from app.services.risk_service import calculate_portfolio_at_risk, sweep_dormant_members

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
    current_user: User = Depends(require_roles(*RISK_ROLES)),
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
    current_user: User = Depends(require_roles(*RISK_ROLES)),
):
    flag = db.get(RiskFlag, flag_id)
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk flag not found.")
    flag.status = RiskFlagStatus.RESOLVED
    flag.resolution_notes = payload.resolution_notes
    flag.resolved_by_user_id = current_user.id
    flag.resolved_at = datetime.utcnow()
    record_audit(
        db, actor_user_id=current_user.id, action="risk.flag_resolve", entity_type="RiskFlag",
        entity_id=flag.id, details=f"Resolved: {payload.resolution_notes}",
    )
    db.commit()
    db.refresh(flag)
    return flag


@router.get("/portfolio-at-risk")
def portfolio_at_risk(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*RISK_ROLES))):
    return calculate_portfolio_at_risk(db)


@router.post("/dormancy-sweep")
def trigger_dormancy_sweep(
    db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))
):
    """Manually triggers the dormancy sweep (also runs automatically on a schedule, see app/main.py)."""
    count = sweep_dormant_members(db)
    record_audit(
        db, actor_user_id=current_user.id, action="risk.dormancy_sweep_manual", entity_type="Member",
        details=f"Manually triggered dormancy sweep: {count} member(s) flagged",
    )
    db.commit()
    return {"members_flagged_dormant": count}


@router.post("/apply-penalties")
def trigger_penalty_application(
    db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))
):
    """
    Manually triggers overdue-installment penalty calculation (also runs
    automatically on a schedule, see app/main.py). Idempotent - installments
    that already have a penalty applied are skipped, so running this twice
    in a row on the same day won't double-charge anyone.
    """
    result = apply_overdue_penalties(db)
    record_audit(
        db, actor_user_id=current_user.id, action="risk.penalties_applied_manual", entity_type="LoanApplication",
        details=f"Applied penalties to {result['installments_penalized']} installment(s) across {result['loans_affected']} loan(s)",
    )
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Compliance Reports
# ---------------------------------------------------------------------------
@router.post("/compliance-reports", response_model=ComplianceReportRead, status_code=status.HTTP_201_CREATED)
def create_compliance_report(
    payload: ComplianceReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RISK_ROLES)),
):
    """
    Logs a regulatory report as prepared (e.g. a SASRA quarterly return or
    an AML suspicious-transaction report). This module tracks the report's
    metadata and submission status; it doesn't generate the report document
    itself - `file_reference` is expected to point at wherever that file
    lives (uploaded elsewhere, a shared drive link, etc).
    """
    report = ComplianceReport(**payload.model_dump(), generated_by_user_id=current_user.id)
    db.add(report)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="risk.compliance_report_create", entity_type="ComplianceReport",
        entity_id=report.id, details=f"Logged {report.report_type} report for {report.period}",
    )
    db.commit()
    db.refresh(report)
    return report


@router.get("/compliance-reports", response_model=list[ComplianceReportRead])
def list_compliance_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*RISK_ROLES)),
    report_type: str | None = None,
    submitted: bool | None = None,
):
    query = db.query(ComplianceReport)
    if report_type:
        query = query.filter(ComplianceReport.report_type == report_type)
    if submitted is not None:
        query = query.filter(ComplianceReport.submitted == submitted)
    return query.order_by(ComplianceReport.created_at.desc()).all()


@router.post("/compliance-reports/{report_id}/submit", response_model=ComplianceReportRead)
def submit_compliance_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Marks a report as submitted to the regulator - a one-way action, not reversible here by design."""
    report = db.get(ComplianceReport, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compliance report not found.")
    if report.submitted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This report is already marked submitted.")
    report.submitted = True
    report.submitted_at = datetime.utcnow()
    record_audit(
        db, actor_user_id=current_user.id, action="risk.compliance_report_submit", entity_type="ComplianceReport",
        entity_id=report.id, details=f"Submitted {report.report_type} for {report.period}",
    )
    db.commit()
    db.refresh(report)
    return report
