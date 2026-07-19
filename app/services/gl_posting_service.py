"""
Automatic double-entry GL posting for savings and loan transactions.

Design: rather than asking tellers to pick GL accounts on every transaction
(error-prone for non-accountants), each *product* is configured once with
the GL account it posts against:

- SavingsProduct.gl_liability_account_id - "what the SACCO owes this
  product's savers" (a liability account, e.g. "2000 - Member Savings")
- LoanProduct.gl_asset_account_id - "what members owe the SACCO on this
  product" (an asset account, e.g. "1100 - Loans Receivable: Development")

The *other* side of every entry is one of a small set of shared "system"
accounts configured once in GLSettings (cash, mobile money clearing,
interest income) - see app/models/gl_settings.py.

Soft-skip behavior: if a product or the relevant system account hasn't
been configured yet, these functions log a warning and return None rather
than raising. This is deliberate - a SACCO should be able to run day-to-day
teller operations (deposits, withdrawals, disbursements) before finance
has finished setting up the chart of accounts, without every transaction
failing. The tradeoff is that the ledger won't balance for anything posted
before setup is complete, which is visible immediately on the trial balance
- there's no silent data loss, just a ledger gap until configured.

Known simplification: BANK and CASH disbursement/repayment channels both
post against the same "cash" system account, and loan penalties (when the
system starts calculating them) would post to the same account as interest
income rather than a separate penalty-income account. Both are reasonable
starting points for a single-till SACCO, not a multi-branch treasury setup.
"""
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import DisbursementChannel, SavingsTxnType
from app.models.accounting import JournalEntry
from app.models.gl_settings import DEFAULT_SETTINGS_ID, GLSettings
from app.models.loan import LoanApplication
from app.models.savings import SavingsAccount, SavingsTransaction
from app.services.accounting_service import post_journal_entry

logger = logging.getLogger("sacco.gl_posting")


def get_or_create_gl_settings(db: Session) -> GLSettings:
    settings_row = db.get(GLSettings, DEFAULT_SETTINGS_ID)
    if not settings_row:
        settings_row = GLSettings(id=DEFAULT_SETTINGS_ID)
        db.add(settings_row)
        db.flush()
    return settings_row


def _settlement_account_id(db: Session, channel: str) -> Optional[str]:
    settings_row = get_or_create_gl_settings(db)
    if channel == "mobile_money":
        return settings_row.mobile_money_account_id
    return settings_row.cash_account_id  # "cash" and "bank" both land here for now


def post_savings_transaction_gl(
    db: Session,
    account: SavingsAccount,
    txn: SavingsTransaction,
    channel: str = "cash",
    performed_by_user_id: Optional[str] = None,
) -> Optional[JournalEntry]:
    """
    Posts a deposit, withdrawal, or interest posting as a balanced entry.
    Deposits/withdrawals post against the product's liability account and
    the channel's settlement account. Interest postings debit the shared
    interest-expense account and credit the product's liability account
    (the SACCO owes the member more, funded by an expense, not new cash).
    """
    if txn.txn_type == SavingsTxnType.INTEREST_POSTING:
        return _post_interest_gl(db, account, txn, performed_by_user_id)

    if txn.txn_type not in (SavingsTxnType.DEPOSIT, SavingsTxnType.WITHDRAWAL):
        return None

    liability_account_id = account.product.gl_liability_account_id
    if not liability_account_id:
        logger.warning(
            "Skipping GL posting for savings txn %s: product '%s' has no gl_liability_account_id configured.",
            txn.id, account.product.name,
        )
        return None

    settlement_account_id = _settlement_account_id(db, channel)
    if not settlement_account_id:
        logger.warning(
            "Skipping GL posting for savings txn %s: no '%s' account configured in GL settings.", txn.id, channel
        )
        return None

    is_deposit = txn.txn_type == SavingsTxnType.DEPOSIT
    lines = [
        {"account_id": settlement_account_id, "debit": txn.amount if is_deposit else 0, "credit": 0 if is_deposit else txn.amount},
        {"account_id": liability_account_id, "debit": 0 if is_deposit else txn.amount, "credit": txn.amount if is_deposit else 0},
    ]
    entry = post_journal_entry(
        db,
        lines=lines,
        narrative=f"Savings {txn.txn_type.value} - {account.account_number}",
        source_module="savings",
        source_reference_id=txn.id,
        created_by_user_id=performed_by_user_id,
    )
    return entry


def _post_interest_gl(
    db: Session, account: SavingsAccount, txn: SavingsTransaction, performed_by_user_id: Optional[str]
) -> Optional[JournalEntry]:
    liability_account_id = account.product.gl_liability_account_id
    if not liability_account_id:
        logger.warning(
            "Skipping GL posting for interest txn %s: product '%s' has no gl_liability_account_id configured.",
            txn.id, account.product.name,
        )
        return None

    expense_account_id = get_or_create_gl_settings(db).interest_expense_account_id
    if not expense_account_id:
        logger.warning(
            "Skipping GL posting for interest txn %s: interest_expense_account_id not configured in GL settings.",
            txn.id,
        )
        return None

    lines = [
        {"account_id": expense_account_id, "debit": txn.amount, "credit": 0},
        {"account_id": liability_account_id, "debit": 0, "credit": txn.amount},
    ]
    return post_journal_entry(
        db,
        lines=lines,
        narrative=f"Interest posting - {account.account_number}",
        source_module="savings",
        source_reference_id=txn.id,
        created_by_user_id=performed_by_user_id,
    )


def post_loan_disbursement_gl(
    db: Session,
    loan: LoanApplication,
    channel: DisbursementChannel,
    disbursement_savings_account: Optional[SavingsAccount] = None,
    performed_by_user_id: Optional[str] = None,
) -> Optional[JournalEntry]:
    """
    Debits the loan product's asset account (loans receivable increases) and
    credits either: the disbursement savings account's own product liability
    account (money never left the SACCO, it just moved to a different
    internal bucket), or a settlement account for cash/mobile money/bank.
    """
    asset_account_id = loan.product.gl_asset_account_id
    if not asset_account_id:
        logger.warning(
            "Skipping GL posting for loan disbursement %s: product '%s' has no gl_asset_account_id configured.",
            loan.id, loan.product.name,
        )
        return None

    if channel == DisbursementChannel.SAVINGS_ACCOUNT:
        if not disbursement_savings_account:
            logger.warning("Skipping GL posting for loan disbursement %s: no savings account provided.", loan.id)
            return None
        credit_account_id = disbursement_savings_account.product.gl_liability_account_id
        if not credit_account_id:
            logger.warning(
                "Skipping GL posting for loan disbursement %s: destination product '%s' has no gl_liability_account_id.",
                loan.id, disbursement_savings_account.product.name,
            )
            return None
    else:
        settlement_channel = "mobile_money" if channel == DisbursementChannel.MOBILE_MONEY else "cash"
        credit_account_id = _settlement_account_id(db, settlement_channel)
        if not credit_account_id:
            logger.warning(
                "Skipping GL posting for loan disbursement %s: no '%s' account configured in GL settings.",
                loan.id, settlement_channel,
            )
            return None

    amount = loan.amount_approved
    lines = [
        {"account_id": asset_account_id, "debit": amount, "credit": 0},
        {"account_id": credit_account_id, "debit": 0, "credit": amount},
    ]
    return post_journal_entry(
        db,
        lines=lines,
        narrative=f"Loan disbursement - {loan.loan_number}",
        source_module="loans",
        source_reference_id=loan.id,
        created_by_user_id=performed_by_user_id,
    )


def post_payroll_gl(
    db: Session,
    gross_pay: Decimal,
    paye_amount: Decimal,
    nssf_employee_amount: Decimal,
    nssf_employer_amount: Decimal,
    net_pay: Decimal,
    loan_deduction_amount: Decimal = Decimal("0"),
    loan_asset_account_id: Optional[str] = None,
    narrative: str = "Payroll",
    performed_by_user_id: Optional[str] = None,
) -> Optional[JournalEntry]:
    """
    Posts a single payslip's payroll cost:
      Debit  Salaries Expense         = gross_pay
      Debit  NSSF Employer Expense    = nssf_employer_amount
      Credit PAYE Payable             = paye_amount
      Credit NSSF Payable             = nssf_employee_amount + nssf_employer_amount
      Credit Loans Receivable         = loan_deduction_amount (if any - reduces what the
                                         employee/member owes on their own SACCO loan)
      Credit Cash                     = net_pay

    Balances by construction: gross_pay + nssf_employer_amount (debits) always
    equals paye + nssf_employee + nssf_employer + loan_deduction + net_pay
    (credits), since net_pay = gross_pay - paye - nssf_employee - loan_deduction.
    """
    gl = get_or_create_gl_settings(db)
    required = [gl.salaries_expense_account_id, gl.nssf_expense_account_id, gl.paye_payable_account_id, gl.nssf_payable_account_id, gl.cash_account_id]
    if not all(required):
        logger.warning("Skipping GL posting for payroll (%s): payroll GL accounts are not fully configured.", narrative)
        return None
    if loan_deduction_amount > 0 and not loan_asset_account_id:
        logger.warning("Skipping GL posting for payroll (%s): loan deduction present but no loan asset account resolved.", narrative)
        return None

    lines = [
        {"account_id": gl.salaries_expense_account_id, "debit": gross_pay, "credit": 0},
        {"account_id": gl.nssf_expense_account_id, "debit": nssf_employer_amount, "credit": 0},
        {"account_id": gl.paye_payable_account_id, "debit": 0, "credit": paye_amount},
        {"account_id": gl.nssf_payable_account_id, "debit": 0, "credit": nssf_employee_amount + nssf_employer_amount},
        {"account_id": gl.cash_account_id, "debit": 0, "credit": net_pay},
    ]
    if loan_deduction_amount > 0:
        lines.append({"account_id": loan_asset_account_id, "debit": 0, "credit": loan_deduction_amount})

    return post_journal_entry(db, lines=lines, narrative=narrative, source_module="hr_payroll", created_by_user_id=performed_by_user_id)


def post_loan_repayment_gl(
    db: Session,
    loan: LoanApplication,
    principal_paid: Decimal,
    interest_paid: Decimal,
    penalty_paid: Decimal = Decimal("0"),
    channel: str = "cash",
    performed_by_user_id: Optional[str] = None,
) -> Optional[JournalEntry]:
    """
    Debits the settlement account for the full amount received, credits the
    loan product's asset account for the principal portion (loans
    receivable decreases) and the interest income account for the
    interest+penalty portion (penalty is lumped into interest income for
    now - see module docstring).
    """
    total = principal_paid + interest_paid + penalty_paid
    if total <= 0:
        return None

    asset_account_id = loan.product.gl_asset_account_id
    if not asset_account_id:
        logger.warning(
            "Skipping GL posting for loan repayment on %s: product '%s' has no gl_asset_account_id configured.",
            loan.id, loan.product.name,
        )
        return None

    settlement_account_id = _settlement_account_id(db, channel)
    if not settlement_account_id:
        logger.warning(
            "Skipping GL posting for loan repayment on %s: no '%s' account configured in GL settings.", loan.id, channel
        )
        return None

    income_portion = interest_paid + penalty_paid
    interest_income_account_id = get_or_create_gl_settings(db).interest_income_account_id
    if income_portion > 0 and not interest_income_account_id:
        logger.warning(
            "Skipping GL posting for loan repayment on %s: interest_income_account_id not configured in GL settings.",
            loan.id,
        )
        return None

    lines = [{"account_id": settlement_account_id, "debit": total, "credit": 0}]
    if principal_paid > 0:
        lines.append({"account_id": asset_account_id, "debit": 0, "credit": principal_paid})
    if income_portion > 0:
        lines.append({"account_id": interest_income_account_id, "debit": 0, "credit": income_portion})

    return post_journal_entry(
        db,
        lines=lines,
        narrative=f"Loan repayment - {loan.loan_number}",
        source_module="loans",
        source_reference_id=loan.id,
        created_by_user_id=performed_by_user_id,
    )
