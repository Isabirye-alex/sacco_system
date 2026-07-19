"""
SACCO Management System - FastAPI application entrypoint.

Wires together all module routers (Member Management, Savings, Credit &
Loans, Accounting, HR & Payroll, Shares, Notifications, Group Management,
Risk & Compliance, System Administration), global exception handling, CORS,
and a background scheduler for the dormancy sweep job.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.routers import (
    accounting,
    admin,
    auth,
    groups,
    hr_payroll,
    loans,
    members,
    mobile_money,
    notifications,
    payroll,
    referrals,
    risk_compliance,
    savings,
    shares,
)
from app.services.loan_penalty_service import apply_overdue_penalties
from app.services.risk_service import sweep_dormant_members
from app.services.savings_interest_service import post_savings_interest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sacco")

app = FastAPI(
    title="SACCO Management System API",
    description=(
        "Production-grade backend for a comprehensive SACCO Management "
        "System, covering member management, savings, credit & loans, "
        "accounting, HR & payroll deductions, shares management, group "
        "management, notifications, and risk & compliance."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(members.router)
app.include_router(savings.router)
app.include_router(loans.router)
app.include_router(mobile_money.router)
app.include_router(accounting.router)
app.include_router(payroll.router)
app.include_router(shares.router)
app.include_router(notifications.router)
app.include_router(groups.router)
app.include_router(risk_compliance.router)
app.include_router(referrals.router)
app.include_router(hr_payroll.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Global exception handling: consistent error envelope for the frontend
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "message": "Validation failed."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again or contact support."},
    )


# ---------------------------------------------------------------------------
# Startup / shutdown: schema bootstrap (dev convenience) + scheduled jobs
# ---------------------------------------------------------------------------
scheduler = BackgroundScheduler()


def _run_dormancy_sweep_job():
    db = SessionLocal()
    try:
        count = sweep_dormant_members(db)
        db.commit()
        if count:
            logger.info("Dormancy sweep flagged %d member(s) as dormant.", count)
    finally:
        db.close()


def _run_penalty_job():
    db = SessionLocal()
    try:
        result = apply_overdue_penalties(db)
        db.commit()
        if result["installments_penalized"]:
            logger.info(
                "Applied penalties to %d installment(s) across %d loan(s), total UGX %s.",
                result["installments_penalized"], result["loans_affected"], result["total_penalty"],
            )
    finally:
        db.close()


def _run_interest_posting_job():
    db = SessionLocal()
    try:
        result = post_savings_interest(db)
        db.commit()
        if result["accounts_posted"]:
            logger.info(
                "Posted interest to %d account(s), total UGX %s.", result["accounts_posted"], result["total_interest"]
            )
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    # NOTE: In production, schema changes should be applied via Alembic
    # migrations (see /alembic). create_all() is a convenience for local
    # development/demo environments only and is a no-op for tables that
    # already exist.
    if settings.ENVIRONMENT == "development":
        Base.metadata.create_all(bind=engine)

    scheduler.add_job(_run_dormancy_sweep_job, "interval", hours=24, id="dormancy_sweep", replace_existing=True)
    scheduler.add_job(_run_penalty_job, "interval", hours=24, id="loan_penalties", replace_existing=True)
    # Interest posting is idempotent per-calendar-month (see
    # savings_interest_service.py), so a simple daily check is safe - it
    # only actually posts anything on accounts that haven't been posted
    # yet this month, regardless of which day of the month this runs.
    scheduler.add_job(_run_interest_posting_job, "interval", hours=24, id="savings_interest", replace_existing=True)
    scheduler.start()
    logger.info("SACCO API started in '%s' environment.", settings.ENVIRONMENT)


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown(wait=False)
