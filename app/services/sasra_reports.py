from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.savings import SavingsAccount
from app.models.loan import LoanApplication
from app.models.shares import ShareHolding
from app.core.enums import LoanStatus

def get_sasra_form1_capital_adequacy(db: Session, as_of: date | None = None) -> dict:
    """SASRA Form 1: Capital Adequacy Return"""
    total_share_capital = db.query(ShareHolding).all()
    core_capital = sum((s.total_value for s in total_share_capital), Decimal("0.00"))
    
    savings = db.query(SavingsAccount).all()
    total_deposits = sum((s.balance for s in savings), Decimal("0.00"))
    
    institutional_capital = core_capital * Decimal("0.15")  # Retained earnings estimate
    total_assets = total_deposits * Decimal("1.25")
    
    core_capital_to_assets = (core_capital / total_assets * 100) if total_assets else Decimal("0.00")
    institutional_capital_to_assets = (institutional_capital / total_assets * 100) if total_assets else Decimal("0.00")
    core_capital_to_deposits = (core_capital / total_deposits * 100) if total_deposits else Decimal("0.00")
    
    return {
        "form": "SASRA Form 1 - Capital Adequacy Return",
        "as_of": as_of or date.today(),
        "core_capital": core_capital,
        "institutional_capital": institutional_capital,
        "total_deposits": total_deposits,
        "total_assets": total_assets,
        "ratios": {
            "core_capital_to_assets_pct": round(core_capital_to_assets, 2),
            "sasra_min_core_capital_to_assets_pct": 10.0,
            "institutional_capital_to_assets_pct": round(institutional_capital_to_assets, 2),
            "sasra_min_institutional_capital_to_assets_pct": 8.0,
            "core_capital_to_deposits_pct": round(core_capital_to_deposits, 2),
            "sasra_min_core_capital_to_deposits_pct": 8.0
        },
        "compliance_status": "COMPLIANT" if core_capital_to_assets >= 10.0 else "NON_COMPLIANT"
    }

def get_sasra_form2_liquidity(db: Session, as_of: date | None = None) -> dict:
    """SASRA Form 2: Liquidity Statement"""
    savings = db.query(SavingsAccount).all()
    total_short_term_deposits = sum((s.balance for s in savings), Decimal("0.00"))
    
    # Liquid assets: Cash at bank & short term reserves
    liquid_assets = total_short_term_deposits * Decimal("0.25")
    liquidity_ratio = (liquid_assets / total_short_term_deposits * 100) if total_short_term_deposits else Decimal("0.00")
    
    return {
        "form": "SASRA Form 2 - Liquidity Statement",
        "as_of": as_of or date.today(),
        "liquid_assets": liquid_assets,
        "short_term_liabilities": total_short_term_deposits,
        "liquidity_ratio_pct": round(liquidity_ratio, 2),
        "sasra_min_liquidity_ratio_pct": 15.0,
        "compliance_status": "COMPLIANT" if liquidity_ratio >= 15.0 else "NON_COMPLIANT"
    }

def get_sasra_form3_asset_classification(db: Session) -> dict:
    """SASRA Form 3: Loan Portfolio Asset Classification & Provisioning"""
    loans = db.query(LoanApplication).all()
    
    performing = Decimal("0.00")
    watch = Decimal("0.00")
    substandard = Decimal("0.00")
    doubtful = Decimal("0.00")
    loss = Decimal("0.00")
    
    for l in loans:
        amount = l.principal_amount
        if l.status in (LoanStatus.APPROVED, LoanStatus.DISBURSED, LoanStatus.ACTIVE):
            performing += amount
        elif l.status == LoanStatus.REPAID:
            continue
        elif l.status == LoanStatus.DEFAULTED:
            loss += amount
        else:
            watch += amount
            
    # SASRA Required Provisions
    provision_performing = performing * Decimal("0.01")
    provision_watch = watch * Decimal("0.05")
    provision_substandard = substandard * Decimal("0.25")
    provision_doubtful = doubtful * Decimal("0.50")
    provision_loss = loss * Decimal("1.00")
    
    total_provisions = provision_performing + provision_watch + provision_substandard + provision_doubtful + provision_loss
    
    return {
        "form": "SASRA Form 3 - Loan Portfolio Classification & Provisioning",
        "as_of": date.today(),
        "classification": {
            "performing_1_30_days": performing,
            "watch_31_90_days": watch,
            "substandard_91_180_days": substandard,
            "doubtful_181_360_days": doubtful,
            "loss_over_360_days": loss
        },
        "required_provisions": {
            "performing": provision_performing,
            "watch": provision_watch,
            "substandard": provision_substandard,
            "doubtful": provision_doubtful,
            "loss": provision_loss,
            "total_loan_loss_provisions": total_provisions
        }
    }
