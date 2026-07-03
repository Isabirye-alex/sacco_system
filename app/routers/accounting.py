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
from app.schemas.misc import (
    ChartOfAccountCreate,
    ChartOfAccountRead,
    JournalEntryCreate,
    JournalEntryRead,
    TrialBalanceLine,
)
from app.services.accounting_service import post_journal_entry

router = APIRouter(prefix="/api/v1/accounting", tags=["Accounting"])

ACCOUNTANT_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT)


@router.post("/accounts", response_model=ChartOfAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: ChartOfAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*ACCOUNTANT_ROLES)),
):
    if db.query(ChartOfAccount).filter(ChartOfAccount.code == payload.code).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account code already exists.")
    account = ChartOfAccount(**payload.model_dump())
    db.add(account)
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
