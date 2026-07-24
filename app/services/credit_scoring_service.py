from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.member import Member
from app.models.savings import SavingsAccount
from app.models.loan import LoanApplication
from app.models.shares import ShareHolding
from app.core.enums import LoanStatus

def compute_member_credit_score(db: Session, member_id: str) -> dict:
    member = db.get(Member, member_id)
    if not member:
        return {
            "score": 300,
            "rating": "POOR",
            "max_eligible_loan": Decimal("0.00"),
            "risk_level": "HIGH",
            "breakdown": {}
        }

    # 1. Savings Score (35% weight -> max 192.5 pts out of 550 base)
    savings_accounts = db.query(SavingsAccount).filter(SavingsAccount.member_id == member_id).all()
    total_savings = sum((acc.balance for acc in savings_accounts), Decimal("0.00"))
    
    savings_score = min(200, int(float(total_savings) / 500000.0 * 50))

    # 2. Loan Repayment Punctuality (35% weight -> max 200 pts)
    loans = db.query(LoanApplication).filter(LoanApplication.member_id == member_id).all()
    total_loans = len(loans)
    repayment_score = 150  # Default starting score
    
    if total_loans > 0:
        completed_loans = sum(1 for l in loans if l.status == LoanStatus.REPAID)
        defaulted_loans = sum(1 for l in loans if l.status == LoanStatus.DEFAULTED)
        
        repayment_score += (completed_loans * 25)
        repayment_score -= (defaulted_loans * 50)
        repayment_score = max(0, min(200, repayment_score))

    # 3. Share Capital Score (15% weight -> max 85 pts)
    holdings = db.query(ShareHolding).filter(ShareHolding.member_id == member_id).all()
    total_shares_val = sum((h.total_value for h in holdings), Decimal("0.00"))
    shares_score = min(85, int(float(total_shares_val) / 200000.0 * 20))

    # 4. Guarantor Exposure Score (15% weight -> max 65 pts)
    # Less active exposure = higher score
    guarantor_score = 65

    # Total Score (Base 300 + calculated points up to 850)
    total_score = min(850, 300 + savings_score + repayment_score + shares_score + guarantor_score)

    if total_score >= 750:
        rating = "EXCELLENT"
        multiplier = Decimal("4.0")
        risk_level = "VERY_LOW"
    elif total_score >= 670:
        rating = "GOOD"
        multiplier = Decimal("3.0")
        risk_level = "LOW"
    elif total_score >= 580:
        rating = "FAIR"
        multiplier = Decimal("2.0")
        risk_level = "MODERATE"
    else:
        rating = "POOR"
        multiplier = Decimal("1.0")
        risk_level = "HIGH"

    max_eligible_loan = total_savings * multiplier

    return {
        "member_id": member_id,
        "score": total_score,
        "rating": rating,
        "risk_level": risk_level,
        "total_savings": total_savings,
        "max_eligible_loan": max_eligible_loan,
        "breakdown": {
            "savings_score": savings_score,
            "repayment_score": repayment_score,
            "shares_score": shares_score,
            "guarantor_score": guarantor_score
        }
    }
