"""
Shared enumerations used across multiple modules.
"""
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    LOAN_OFFICER = "loan_officer"
    ACCOUNTANT = "accountant"
    HR_OFFICER = "hr_officer"
    TELLER = "teller"
    MEMBER = "member"
    AUDITOR = "auditor"


class MemberStatus(str, enum.Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    SUSPENDED = "suspended"
    EXITED = "exited"


class SavingsTxnType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST_POSTING = "interest_posting"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    PENALTY = "penalty"


class LoanStatus(str, enum.Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISBURSED = "disbursed"
    ACTIVE = "active"
    CLOSED = "closed"
    DEFAULTED = "defaulted"
    RESCHEDULED = "rescheduled"


class GuarantorStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    RELEASED = "released"


class DisbursementChannel(str, enum.Enum):
    SAVINGS_ACCOUNT = "savings_account"
    MOBILE_MONEY = "mobile_money"
    BANK = "bank"
    CASH = "cash"


class JournalEntryStatus(str, enum.Enum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class DeductionStatus(str, enum.Enum):
    PENDING = "pending"
    MATCHED = "matched"
    RECONCILED = "reconciled"
    EXCEPTION = "exception"


class ShareTxnType(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    TRANSFER = "transfer"
    REDEMPTION = "redemption"
    DIVIDEND = "dividend"


class NotificationChannel(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class NotificationStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class GroupRole(str, enum.Enum):
    CHAIR = "chair"
    SECRETARY = "secretary"
    TREASURER = "treasurer"
    MEMBER = "member"


class RiskFlagType(str, enum.Enum):
    AML_SUSPICIOUS_DEPOSIT = "aml_suspicious_deposit"
    DUPLICATE_ID = "duplicate_id"
    MULTIPLE_LOANS = "multiple_loans"
    GHOST_MEMBER = "ghost_member"
    LOAN_DEFAULT_RISK = "loan_default_risk"


class RiskFlagStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
