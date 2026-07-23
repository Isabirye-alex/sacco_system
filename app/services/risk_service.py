"""
Risk & Compliance service: dormancy detection sweep and portfolio-at-risk
(PAR) aggregation used by scheduled jobs and the risk router.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import LoanStatus, MemberStatus, NotificationChannel
from app.models.loan import LoanApplication, LoanRepaymentSchedule
from app.models.member import Member
from app.services.notification_service import dispatch, queue_notification


def sweep_dormant_members(db: Session) -> int:
    """
    Multilevel dormancy detection sweep:
    - Stage 1 (150 days / 5 months): Warning alert dispatched to Member.
    - Stage 2 (180 days / 6 months): Member status updated to DORMANT; alert dispatched to Next-of-Kin.
    - Stage 3 (210 days / 7 months): Escalation alert dispatched to Trusted Contacts.
    Returns the count of members transitioned to DORMANT.
    """
    now = datetime.utcnow()
    t_stage1 = now - timedelta(days=150)
    t_stage2 = now - timedelta(days=180)
    t_stage3 = now - timedelta(days=210)

    dormant_count = 0

    # Stage 1: 5 months (150 days) - Alert Account Holder
    stage1_stmt = select(Member).where(
        Member.status == MemberStatus.ACTIVE,
        Member.last_activity_at.is_not(None),
        Member.last_activity_at <= t_stage1,
        Member.dormancy_notified_stage < 1,
    )
    for member in db.scalars(stage1_stmt).all():
        member.dormancy_notified_stage = 1
        notif = queue_notification(
            db,
            channel=NotificationChannel.SMS,
            body=f"Dear {member.first_name}, your account {member.member_number} has been inactive for 5 months. Please initiate a transaction to keep it active.",
            member_id=member.id,
            event_type="dormancy_warning_stage1",
        )
        try:
            dispatch(notif)
        except Exception:
            pass

    # Stage 2: 6 months (180 days) - Set DORMANT and Alert Next-of-Kin
    stage2_stmt = select(Member).where(
        Member.status == MemberStatus.ACTIVE,
        Member.last_activity_at.is_not(None),
        Member.last_activity_at <= t_stage2,
        Member.dormancy_notified_stage < 2,
    )
    for member in db.scalars(stage2_stmt).all():
        member.status = MemberStatus.DORMANT
        member.dormancy_notified_stage = 2
        dormant_count += 1
        nok_names = ", ".join([nok.full_name for nok in member.next_of_kin]) or "Next-of-Kin"
        notif = queue_notification(
            db,
            channel=NotificationChannel.SMS,
            body=f"DORMANCY NOTICE: Account {member.member_number} ({member.full_name}) is now DORMANT. Alert sent to registered NOK: {nok_names}.",
            member_id=member.id,
            event_type="dormancy_alert_stage2_nok",
        )
        try:
            dispatch(notif)
        except Exception:
            pass

    # Stage 3: 7 months (210 days) - Alert Trusted Contacts
    stage3_stmt = select(Member).where(
        Member.status == MemberStatus.DORMANT,
        Member.last_activity_at.is_not(None),
        Member.last_activity_at <= t_stage3,
        Member.dormancy_notified_stage < 3,
    )
    for member in db.scalars(stage3_stmt).all():
        member.dormancy_notified_stage = 3
        tc_names = ", ".join([tc.full_name for tc in member.trusted_contacts]) or "Trusted Contacts"
        notif = queue_notification(
            db,
            channel=NotificationChannel.SMS,
            body=f"URGENT DORMANCY ESCALATION: Account {member.member_number} ({member.full_name}) inactive for 7 months. Trusted Contacts ({tc_names}) have been notified.",
            member_id=member.id,
            event_type="dormancy_alert_stage3_trusted_contact",
        )
        try:
            dispatch(notif)
        except Exception:
            pass

    db.commit()
    return dormant_count


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
