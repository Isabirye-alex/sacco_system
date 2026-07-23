"""
Accounting Module endpoints: chart of accounts, manual journal entries,
and trial balance reporting.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.dependencies import get_current_user, require_roles
from app.models.accounting import ChartOfAccount, JournalLine
from app.models.user import User
from app.schemas.gl_settings import GLSettingsRead, GLSettingsUpdate
from app.schemas.misc import (
    ChartOfAccountCreate,
    ChartOfAccountRead,
    JournalEntryCreate,
    JournalEntryRead,
    TrialBalanceLine,
)
from app.services.accounting_service import post_journal_entry # type: ignore
from app.services.audit_service import record_audit
from app.services.gl_posting_service import get_or_create_gl_settings # type: ignore

router = APIRouter(prefix="/api/v1/accounting", tags=["Accounting"])

ACCOUNTANT_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT)


@router.post("/accounts", response_model=ChartOfAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: ChartOfAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)), # type: ignore
):
    if db.query(ChartOfAccount).filter(ChartOfAccount.code == payload.code).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account code already exists.")
    account = ChartOfAccount(**payload.model_dump())
    db.add(account)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="accounting.account_create", entity_type="ChartOfAccount",
        entity_id=account.id, details=f"Created account {account.code} - {account.name} ({account.account_type})",
    )
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts", response_model=list[ChartOfAccountRead])
def list_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ChartOfAccount).filter(ChartOfAccount.is_active.is_(True)).all()


@router.post("/journal-entries", response_model=JournalEntryRead, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    payload: JournalEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)),
):
    entry = post_journal_entry(
        db=db,
        lines=[line.model_dump() for line in payload.lines],
        narrative=payload.narrative,
        source_module="manual",
        created_by_user_id=current_user.id,
    )
    db.flush()
    total = sum((line.debit for line in entry.lines), Decimal("0"))
    record_audit(
        db, actor_user_id=current_user.id, action="accounting.journal_entry_post", entity_type="JournalEntry",
        entity_id=entry.id, details=f"Posted {entry.entry_number}: {payload.narrative or 'no narrative'} (UGX {total})",
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/trial-balance", response_model=list[TrialBalanceLine])
def trial_balance(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES))):
    accounts = db.query(ChartOfAccount).all()
    result = []
    for account in accounts:
        debit_total = sum((l.debit for l in account.lines), Decimal("0"))
        credit_total = sum((l.credit for l in account.lines), Decimal("0"))
        if debit_total == 0 and credit_total == 0:
            continue
        result.append(
            TrialBalanceLine(
                account_code=account.code,
                account_name=account.name,
                debit=debit_total,
                credit=credit_total,
            )
        )
    return result


# ---------- GL Settings (the shared "other side" accounts - see gl_posting_service.py) ----------
@router.get("/gl-settings", response_model=GLSettingsRead)
def get_gl_settings(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES))):
    settings_row = get_or_create_gl_settings(db)
    db.commit()  # persists the row if get_or_create_gl_settings just created a blank one
    return settings_row


@router.patch("/gl-settings", response_model=GLSettingsRead)
def update_gl_settings(
    payload: GLSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    settings_row = get_or_create_gl_settings(db)
    for account_id in payload.model_dump(exclude_unset=True).values():
        if account_id and not db.get(ChartOfAccount, account_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chart of account {account_id} not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings_row, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="accounting.gl_settings_update", entity_type="GLSettings",
        entity_id=settings_row.id, details=f"Updated GL settings: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(settings_row)
    return settings_row


# ---------- Bank Reconciliation ----------
from datetime import date
from pydantic import BaseModel

class BankStatementItemCreate(BaseModel):
    txn_date: date
    description: str
    amount: Decimal
    reference: Optional[str] = None

class BankStatementUploadRequest(BaseModel):
    bank_name: str
    account_number: str
    statement_date: date
    items: list[BankStatementItemCreate]


@router.post("/bank-reconciliation/upload", status_code=status.HTTP_201_CREATED)
def upload_bank_statement(
    payload: BankStatementUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)),
):
    """
    Uploads a bank statement and saves items for reconciliation matching.
    """
    from app.models.bank_reconciliation import BankStatement, BankStatementTransaction

    stmt = BankStatement(
        bank_name=payload.bank_name,
        account_number=payload.account_number,
        statement_date=payload.statement_date,
        uploaded_by_user_id=current_user.id,
    )
    db.add(stmt)
    db.flush()

    for item in payload.items:
        db.add(
            BankStatementTransaction(
                statement_id=stmt.id,
                txn_date=item.txn_date,
                description=item.description,
                reference=item.reference,
                amount=item.amount,
            )
        )

    record_audit(
        db, actor_user_id=current_user.id, action="accounting.bank_statement_upload",
        entity_type="BankStatement", entity_id=stmt.id,
        details=f"Uploaded statement for {payload.bank_name} ({payload.account_number}) with {len(payload.items)} item(s)",
    )
    db.commit()
    return {"statement_id": stmt.id, "total_items": len(payload.items)}


@router.get("/bank-reconciliation/statements")
def list_bank_statements(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)),
):
    from app.models.bank_reconciliation import BankStatement
    statements = db.query(BankStatement).all()
    return [
        {
            "id": s.id,
            "bank_name": s.bank_name,
            "account_number": s.account_number,
            "statement_date": s.statement_date,
            "total_items": len(s.transactions),
            "matched_items": len([t for t in s.transactions if t.is_matched]),
        }
        for s in statements
    ]


class BankReconcileMatchRequest(BaseModel):
    statement_txn_id: str
    journal_entry_id: str


@router.post("/bank-reconciliation/match")
def match_bank_transaction(
    payload: BankReconcileMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)),
):
    """
    Matches a bank statement transaction against a GL Journal Entry.
    """
    from datetime import datetime
    from app.models.bank_reconciliation import BankStatementTransaction
    from app.models.accounting import JournalEntry

    txn = db.get(BankStatementTransaction, payload.statement_txn_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank statement transaction not found.")

    entry = db.get(JournalEntry, payload.journal_entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found.")

    txn.is_matched = True
    txn.matched_journal_entry_id = entry.id
    txn.matched_at = datetime.utcnow()

    record_audit(
        db, actor_user_id=current_user.id, action="accounting.bank_reconcile_match",
        entity_type="BankStatementTransaction", entity_id=txn.id,
        details=f"Matched bank line {txn.description} ({txn.amount}) with GL Entry {entry.entry_number}",
    )
    db.commit()
    return {"status": "matched", "statement_txn_id": txn.id, "journal_entry_id": entry.id}
