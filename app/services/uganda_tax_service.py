"""
Uganda resident-individual PAYE and NSSF calculations.

============================================================================
IMPORTANT - VERIFY BEFORE RELYING ON THIS FOR REAL PAYROLL
============================================================================
The PAYE bands and NSSF rates below reflect Uganda's tax structure as
understood at the time this was written. Ugandan tax law is reviewed
annually via the Finance Act, and bands/rates DO change. Getting employee
tax withholding wrong is a real compliance/legal exposure for the SACCO as
an employer - before running actual payroll:

1. Check the current PAYE guide at ura.go.ug (Uganda Revenue Authority)
2. Check the current NSSF Act rates at nssfug.org
3. Update PAYE_BANDS / NSSF_EMPLOYEE_RATE / NSSF_EMPLOYER_RATE below if
   anything has changed - they're isolated here specifically so that's a
   one-place fix, not a hunt through the codebase.
============================================================================

Assumptions made (flag if any of these don't match your situation):
- Resident individual, monthly PAYE bands (not annual, not non-resident).
- PAYE is calculated on gross pay directly - NSSF employee contribution is
  NOT deducted before calculating PAYE. This matches Uganda's standard
  treatment as I understand it, but double-check this specific point since
  it's the kind of detail that's easy to get backwards.
- No other statutory deductions modeled (e.g. Local Service Tax, which
  varies by district and isn't universally applied) - not included here.
"""
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")

# Monthly PAYE bands for resident individuals: (lower_bound, upper_bound_or_None, base_tax, marginal_rate)
# upper_bound=None means "and above". VERIFY AGAINST CURRENT URA GUIDE.
PAYE_BANDS = [
    (Decimal("0"), Decimal("235000"), Decimal("0"), Decimal("0.00")),
    (Decimal("235000"), Decimal("335000"), Decimal("0"), Decimal("0.10")),
    (Decimal("335000"), Decimal("410000"), Decimal("10000"), Decimal("0.20")),
    (Decimal("410000"), Decimal("10000000"), Decimal("25000"), Decimal("0.30")),
    (Decimal("10000000"), None, Decimal("2902000"), Decimal("0.40")),
]

NSSF_EMPLOYEE_RATE = Decimal("0.05")  # 5% of gross pay, deducted from the employee
NSSF_EMPLOYER_RATE = Decimal("0.10")  # 10% of gross pay, an employer cost - NOT deducted from the employee


def calculate_paye(gross_pay: Decimal) -> Decimal:
    """Monthly PAYE for a resident individual. See module docstring for assumptions/verification notice."""
    gross_pay = Decimal(gross_pay)
    for lower, upper, base_tax, rate in PAYE_BANDS:
        if upper is None or gross_pay <= upper:
            taxable_in_band = gross_pay - lower
            tax = base_tax + (taxable_in_band * rate)
            return tax.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    # Unreachable given the last band has upper=None, but keeps type-checkers happy.
    return Decimal("0.00")


def calculate_nssf(gross_pay: Decimal) -> dict:
    gross_pay = Decimal(gross_pay)
    employee = (gross_pay * NSSF_EMPLOYEE_RATE).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    employer = (gross_pay * NSSF_EMPLOYER_RATE).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return {"employee": employee, "employer": employer}
