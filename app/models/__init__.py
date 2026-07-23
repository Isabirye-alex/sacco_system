"""
Import every model module here so that Base.metadata is fully populated
before Alembic autogenerate or create_all() is invoked.
"""
from app.models.user import User, AuditLog  # noqa: F401
from app.models.member import Member, NextOfKin, TrustedContact  # noqa: F401
from app.models.savings import SavingsProduct, SavingsAccount, SavingsTransaction  # noqa: F401
from app.models.loan import (  # noqa: F401
    LoanProduct,
    LoanApplication,
    Guarantor,
    LoanRepaymentSchedule,
    LoanTransaction,
    Collateral,
)
from app.models.accounting import ChartOfAccount, JournalEntry, JournalLine  # noqa: F401
from app.models.gl_settings import GLSettings  # noqa: F401
from app.models.payroll import Employer, PayrollFile, PayrollDeduction  # noqa: F401
from app.models.shares import (  # noqa: F401
    ShareProduct,
    ShareHolding,
    ShareTransaction,
    DividendDeclaration,
    DividendPayout,
)
from app.models.notification import Notification  # noqa: F401
from app.models.mobile_money import MobileMoneyTransaction  # noqa: F401
from app.models.group import MemberGroup, GroupMembership, GroupContribution, GroupLoanGuarantee  # noqa: F401
from app.models.risk_compliance import RiskFlag, ComplianceReport  # noqa: F401
from app.models.referral import Referral  # noqa: F401
from app.models.system_settings_model import SystemSettings  # noqa: F401
from app.models.hr_payroll import Employee, PayrollRun, Payslip  # noqa: F401
from app.models.branch import Branch  # noqa: F401

