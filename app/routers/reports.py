"""
Financial & regulatory reports endpoints - real data, replacing the admin
portal's hardcoded dummy report numbers. See
app/services/financial_reports_service.py for the calculations and an
important caveat about which two of these are approximations rather than
exact regulatory formulas.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.dependencies import get_current_user, require_roles
from app.models.user import User
from app.services.financial_reports_service import (
    get_balance_sheet,
    get_capital_adequacy,
    get_dashboard_trends,
    get_income_statement,
    get_liquidity_ratio,
    get_loan_disbursement_vs_recovery,
    get_member_growth,
)

router = APIRouter(prefix="/api/v1/reports", tags=["Financial Reports"])

REPORT_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT, UserRole.AUDITOR)


@router.get("/balance-sheet")
def balance_sheet(
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_balance_sheet(db, as_of)


@router.get("/income-statement")
def income_statement(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_income_statement(db, start_date, end_date)


@router.get("/liquidity-ratio")
def liquidity_ratio(
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_liquidity_ratio(db, as_of)


@router.get("/capital-adequacy")
def capital_adequacy(
    as_of: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_capital_adequacy(db, as_of)


@router.get("/member-growth")
def member_growth(
    months: int = Query(12, ge=1, le=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_member_growth(db, months)


@router.get("/dashboard-trends")
def dashboard_trends(
    months: int = Query(7, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_dashboard_trends(db, months)
def loan_disbursement_recovery(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*REPORT_ROLES)),
):
    return get_loan_disbursement_vs_recovery(db, start_date, end_date)
