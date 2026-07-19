"""
Staff Payroll Module endpoints: employee records, payroll runs, PAYE/NSSF
calculation, and payslips. See app/services/uganda_tax_service.py for the
tax calculation itself (and its verification warning), and
app/services/gl_posting_service.post_payroll_gl for the ledger posting.

Workflow: create employees once -> create a DRAFT run for a period listing
which employees to include -> process it (calculates every payslip,
becomes immutable) -> mark individual payslips paid as salaries actually
go out. Payslip payment here is manual (cash/bank) only - mobile money
salary disbursement isn't wired up yet, unlike the async, webhook-confirmed
flow used for member loan disbursements (see app/routers/mobile_money.py);
that's a reasonable next step if you want it, but is a materially bigger
piece of work to do safely (idempotent retries, confirmation before
marking paid, etc) than this pass covers.
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import LoanStatus, UserRole
from app.dependencies import get_current_user, require_roles
from app.models.hr_payroll import Employee, PayrollRun, PayrollRunStatus, Payslip, PayslipPaymentStatus
from app.models.loan import LoanApplication
from app.models.user import User
from app.schemas.hr_payroll import (
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    PayrollRunCreate,
    PayrollRunDetailRead,
    PayrollRunRead,
    PayslipRead,
    ProcessPayrollRequest,
)
from app.services.audit_service import record_audit
from app.services.gl_posting_service import post_payroll_gl
from app.services.uganda_tax_service import calculate_nssf, calculate_paye

router = APIRouter(prefix="/api/v1/hr-payroll", tags=["HR & Staff Payroll"])

HR_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.HR_OFFICER)


def _generate_employee_number() -> str:
    import random

    return f"EMP{datetime.utcnow().strftime('%y%m')}{random.randint(1000, 9999)}"


# ---------- Employees ----------
@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))
):
    employee = Employee(employee_number=_generate_employee_number(), **payload.model_dump())
    db.add(employee)
    db.flush()
    record_audit(
        db, actor_user_id=current_user.id, action="hr.employee_create", entity_type="Employee",
        entity_id=employee.id, details=f"Created employee {employee.employee_number} ({employee.full_name})",
    )
    db.commit()
    db.refresh(employee)
    return employee


@router.get("/employees", response_model=list[EmployeeRead])
def list_employees(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))):
    return db.query(Employee).filter(Employee.is_active.is_(True)).all()


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*HR_ROLES)),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)
    record_audit(
        db, actor_user_id=current_user.id, action="hr.employee_update", entity_type="Employee",
        entity_id=employee.id, details=f"Updated {employee.employee_number}: {payload.model_dump(exclude_unset=True)}",
    )
    db.commit()
    db.refresh(employee)
    return employee


# ---------- Payroll Runs ----------
@router.post("/runs", response_model=PayrollRunDetailRead, status_code=status.HTTP_201_CREATED)
def create_payroll_run(
    payload: PayrollRunCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))
):
    if db.query(PayrollRun).filter(PayrollRun.period == payload.period).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A payroll run for {payload.period} already exists.")
    if not payload.employee_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Include at least one employee.")

    run = PayrollRun(period=payload.period)
    db.add(run)
    db.flush()

    # Draft payslips (unprocessed placeholders) so the run "contains" these
    # employees before /process fills in the actual calculated amounts.
    for employee_id in payload.employee_ids:
        employee = db.get(Employee, employee_id)
        if not employee:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Employee {employee_id} not found.")
        db.add(Payslip(
            payroll_run_id=run.id, employee_id=employee_id, basic_salary=employee.basic_salary,
            allowances=employee.allowances, gross_pay=employee.gross_pay, net_pay=employee.gross_pay,
        ))

    record_audit(
        db, actor_user_id=current_user.id, action="hr.payroll_run_create", entity_type="PayrollRun",
        entity_id=run.id, details=f"Created draft run for {run.period} with {len(payload.employee_ids)} employee(s)",
    )
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs", response_model=list[PayrollRunRead])
def list_payroll_runs(db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))):
    return db.query(PayrollRun).order_by(PayrollRun.created_at.desc()).all()


@router.get("/runs/{run_id}", response_model=PayrollRunDetailRead)
def get_payroll_run(run_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))):
    run = db.get(PayrollRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll run not found.")
    return run


def _suggested_loan_deduction(db: Session, employee: Employee):
    """Looks up the employee's own active SACCO loan (if linked as a member) and
    suggests the next unpaid installment's outstanding total as the deduction."""
    if not employee.member_id:
        return Decimal("0"), None
    loan = (
        db.query(LoanApplication)
        .filter(LoanApplication.member_id == employee.member_id, LoanApplication.status == LoanStatus.ACTIVE)
        .first()
    )
    if not loan:
        return Decimal("0"), None
    next_installment = next((i for i in loan.schedule if not i.is_paid), None)
    if not next_installment:
        return Decimal("0"), None
    due = next_installment.principal_due + next_installment.interest_due + next_installment.penalty_due
    outstanding = due - next_installment.amount_paid
    return max(outstanding, Decimal("0")), loan.id


@router.post("/runs/{run_id}/process", response_model=PayrollRunDetailRead)
def process_payroll_run(
    run_id: str,
    payload: ProcessPayrollRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*HR_ROLES)),
):
    """
    Calculates PAYE, NSSF, and net pay for every payslip in the run, posts
    the GL entry per payslip, and marks the run PROCESSED. A processed run
    is immutable - can't be re-processed. See app/services/uganda_tax_service.py
    for the tax calculation and its verification notice.
    """
    run = db.get(PayrollRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll run not found.")
    if run.status == PayrollRunStatus.PROCESSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This payroll run has already been processed.")

    overrides = {o.employee_id: o.loan_deduction_amount for o in payload.overrides}

    totals = {
        "gross": Decimal("0"), "paye": Decimal("0"), "nssf_employee": Decimal("0"),
        "nssf_employer": Decimal("0"), "loan": Decimal("0"), "net": Decimal("0"),
    }

    for payslip in run.payslips:
        employee = payslip.employee
        gross_pay = employee.gross_pay
        paye = calculate_paye(gross_pay)
        nssf = calculate_nssf(gross_pay)

        suggested_deduction, loan_id = _suggested_loan_deduction(db, employee)
        override_value = overrides.get(employee.id)
        loan_deduction = override_value if override_value is not None else suggested_deduction
        max_deduction = gross_pay - paye - nssf["employee"]
        loan_deduction = min(max(loan_deduction, Decimal("0")), max_deduction)

        net_pay = gross_pay - paye - nssf["employee"] - loan_deduction

        payslip.basic_salary = employee.basic_salary
        payslip.allowances = employee.allowances
        payslip.gross_pay = gross_pay
        payslip.paye_amount = paye
        payslip.nssf_employee_amount = nssf["employee"]
        payslip.nssf_employer_amount = nssf["employer"]
        payslip.loan_deduction_amount = loan_deduction
        payslip.loan_id = loan_id if loan_deduction > 0 else None
        payslip.net_pay = net_pay

        loan_asset_account_id = None
        if loan_deduction > 0 and loan_id:
            loan = db.get(LoanApplication, loan_id)
            loan_asset_account_id = loan.product.gl_asset_account_id if loan else None

        post_payroll_gl(
            db,
            gross_pay=gross_pay, paye_amount=paye, nssf_employee_amount=nssf["employee"],
            nssf_employer_amount=nssf["employer"], net_pay=net_pay, loan_deduction_amount=loan_deduction,
            loan_asset_account_id=loan_asset_account_id, narrative=f"Payroll {run.period} - {employee.full_name}",
            performed_by_user_id=current_user.id,
        )

        totals["gross"] += gross_pay
        totals["paye"] += paye
        totals["nssf_employee"] += nssf["employee"]
        totals["nssf_employer"] += nssf["employer"]
        totals["loan"] += loan_deduction
        totals["net"] += net_pay

    run.total_gross = totals["gross"]
    run.total_paye = totals["paye"]
    run.total_nssf_employee = totals["nssf_employee"]
    run.total_nssf_employer = totals["nssf_employer"]
    run.total_loan_deductions = totals["loan"]
    run.total_net = totals["net"]
    run.status = PayrollRunStatus.PROCESSED
    run.processed_at = datetime.utcnow()
    run.processed_by_user_id = current_user.id

    record_audit(
        db, actor_user_id=current_user.id, action="hr.payroll_run_process", entity_type="PayrollRun",
        entity_id=run.id, details=f"Processed {run.period}: UGX {totals['net']} net across {len(run.payslips)} payslip(s)",
    )
    db.commit()
    db.refresh(run)
    return run


# ---------- Payslips ----------
@router.get("/payslips/{payslip_id}", response_model=PayslipRead)
def get_payslip(payslip_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))):
    payslip = db.get(Payslip, payslip_id)
    if not payslip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payslip not found.")
    return payslip


@router.post("/payslips/{payslip_id}/pay", response_model=PayslipRead)
def mark_payslip_paid(
    payslip_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_roles(*HR_ROLES))
):
    payslip = db.get(Payslip, payslip_id)
    if not payslip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payslip not found.")
    if payslip.payment_status == PayslipPaymentStatus.PAID:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This payslip is already marked paid.")
    payslip.payment_status = PayslipPaymentStatus.PAID
    payslip.paid_at = datetime.utcnow()
    payslip.paid_by_user_id = current_user.id
    record_audit(
        db, actor_user_id=current_user.id, action="hr.payslip_paid", entity_type="Payslip",
        entity_id=payslip.id, details=f"Marked paid: UGX {payslip.net_pay} net for {payslip.employee.full_name}",
    )
    db.commit()
    db.refresh(payslip)
    return payslip
