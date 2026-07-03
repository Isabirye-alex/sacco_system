"""
Accounting service: enforces double-entry bookkeeping rules (debits must
equal credits) and posts journal entries originating from other modules
(savings, loans, shares, payroll).
"""
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.accounting import ChartOfAccount, JournalEntry, JournalLine
from app.services.numbering import generate_journal_entry_number


def post_journal_entry(
    db: Session,
    lines: list[dict],
    narrative: Optional[str] = None,
    source_module: Optional[str] = None,
    source_reference_id: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> JournalEntry:
    """
    lines: list of {"account_id": str, "debit": Decimal, "credit": Decimal, "description": str|None}
    Raises HTTPException(422) if the entry does not balance.
    """
    total_debit = sum((Decimal(str(l.get("debit", 0))) for l in lines), Decimal("0"))
    total_credit = sum((Decimal(str(l.get("credit", 0))) for l in lines), Decimal("0"))
    if total_debit != total_credit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Journal entry does not balance: debit={total_debit} credit={total_credit}",
        )
    if total_debit == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Journal entry cannot be zero.")

    entry = JournalEntry(
        entry_number=generate_journal_entry_number(),
        narrative=narrative,
        source_module=source_module,
        source_reference_id=source_reference_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(entry)
    db.flush()  # obtain entry.id

    for line in lines:
        account = db.get(ChartOfAccount, line["account_id"])
        if account is None:
            raise HTTPException(status_code=404, detail=f"Chart of account {line['account_id']} not found.")
        db.add(
            JournalLine(
                entry_id=entry.id,
                account_id=line["account_id"],
                debit=Decimal(str(line.get("debit", 0))),
                credit=Decimal(str(line.get("credit", 0))),
                description=line.get("description"),
            )
        )
    return entry
