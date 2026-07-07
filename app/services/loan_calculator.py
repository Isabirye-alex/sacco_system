"""
Loan amortization logic: reducing-balance repayment schedule generation
and simple portfolio-at-risk (PAR) helpers.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Tuple

from dateutil.relativedelta import relativedelta  # type: ignore

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def build_reducing_balance_schedule(
    principal: Decimal,
    annual_interest_rate_pct: Decimal,
    months: int,
    start_date: date,
) -> List[Tuple[int, date, Decimal, Decimal]]:
    """
    Returns a list of (installment_number, due_date, principal_due, interest_due)
    using the reducing-balance (declining balance) method with equal total
    installments (annuity-style), which is standard for SACCO loan products.
    """
    monthly_rate = (annual_interest_rate_pct / Decimal("100")) / Decimal("12")
    if monthly_rate == 0:
        installment = principal / months
    else:
        factor = (1 + monthly_rate) ** months
        installment = principal * (monthly_rate * factor) / (factor - 1)

    schedule = []
    balance = principal
    for i in range(1, months + 1):
        interest_due = _round(balance * monthly_rate)
        if i == months:
            principal_due = _round(balance)  # clear any rounding residue on final installment
        else:
            principal_due = _round(Decimal(installment) - interest_due)
        due_date = start_date + relativedelta(months=i)
        schedule.append((i, due_date, principal_due, interest_due)) # type: ignore
        balance -= principal_due
    return schedule # type: ignore


def calculate_par(overdue_outstanding: Decimal, total_outstanding: Decimal) -> Decimal:
    """Portfolio-at-Risk ratio, expressed as a percentage."""
    if total_outstanding == 0:
        return Decimal("0")
    return _round((overdue_outstanding / total_outstanding) * Decimal("100"))
