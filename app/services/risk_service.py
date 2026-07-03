"""
Risk & Compliance service: dormancy detection sweep and portfolio-at-risk
(PAR) aggregation used by scheduled jobs and the risk router.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import LoanStatus, MemberStatus
from app.models.loan import LoanApplication, LoanRepaymentSchedule
from app.models.member import Member


def sweep_dormant_members(db: Session) -> int:
    """
    Flags members with no savings/loan activity within the configured
    dormancy threshold as DORMANT. Returns the count of members updated.
    """
    threshold_date = datetime.utcnow() - timedelta(days=settings.DORMANCY_THRESHOLD_MONTHS * 30)
    stmt = select(Member).where(
        Member.status == MemberStatus.ACTIVE,
        Member.last_activity_at.is_not(None),
        Member.last_activity_at < threshold_date,
    )
    members = db.scalars(stmt).all()
    for member in members:
        member.status = MemberStatus.DORMANT
    return len(members)


def calculate_portfolio_at_risk(db: Session, as_of: date | None = None) -> dict:
    """
    Computes PAR by summing outstanding principal on installments overdue
    as of `as_of` against total outstanding principal across active loans.
    """
    as_of = as_of or date.today()

    active_loan_ids = db.scalars(
        select(LoanApplication.id).where(LoanApplication.status == LoanStatus.ACTIVE)
    ).all()
    if not active_loan_ids:
        return {"portfolio_at_risk_pct": Decimal("0"), "overdue_outstanding": Decimal("0"), "total_outstanding": Decimal("0")}

    schedules = db.scalars(
        select(LoanRepaymentSchedule).where(LoanRepaymentSchedule.loan_id.in_(active_loan_ids))
    ).all()

    total_outstanding = Decimal("0")
    overdue_outstanding = Decimal("0")
    for s in schedules:
        outstanding = (s.principal_due - s.amount_paid) if not s.is_paid else Decimal("0")
        if outstanding <= 0:
            continue
        total_outstanding += outstanding
        if s.due_date < as_of:
            overdue_outstanding += outstanding

    pct = (overdue_outstanding / total_outstanding * 100) if total_outstanding else Decimal("0")
    return {
        "portfolio_at_risk_pct": pct.quantize(Decimal("0.01")),
        "overdue_outstanding": overdue_outstanding,
        "total_outstanding": total_outstanding,
    }
