import asyncio
import logging
import warnings
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.services.risk_service import sweep_dormant_members
from app.routers import (
    accounting,
    admin,
    auth,
    branch,
    groups,
    hr_payroll,
    loans,
    members,
    mobile_money,
    notifications,
    payroll,
    referrals,
    reports,
    risk_compliance,
    savings,
    shares,
)

from app.services.loan_penalty_service import apply_overdue_penalties
from app.services.risk_service import sweep_dormant_members
from app.services.savings_interest_service import post_savings_interest

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sacco")

# ---------------------------------------------------------------------------
# Background Scheduler Setup & Jobs
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
                result["installments_penalized"],
                result["loans_affected"],
                result["total_penalty"],
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
                "Posted interest to %d account(s), total UGX %s.",
                result["accounts_posted"],
                result["total_interest"],
            )
    finally:
        db.close()


def _sync_schema_columns():
    from sqlalchemy import text
    statements = [
        "ALTER TABLE members ADD COLUMN IF NOT EXISTS dormancy_notified_stage INT DEFAULT 0;",
        "ALTER TABLE collaterals ADD COLUMN IF NOT EXISTS is_released BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE collaterals ADD COLUMN IF NOT EXISTS released_at TIMESTAMP;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referrer_id VARCHAR(36);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referred_user_id VARCHAR(36);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS tier INT DEFAULT 1;",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
                logger.info("Successfully executed schema DDL: %s", stmt)
            except Exception as exc:
                logger.error("Error executing schema DDL '%s': %s", stmt, exc)


# ---------------------------------------------------------------------------
# Modern Lifespan Handler (Replaces @app.on_event)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    if settings.ENVIRONMENT != "testing":
        try:
            Base.metadata.create_all(bind=engine)
            _sync_schema_columns()
        except Exception as ex:
            logger.error("Database table initialization error: %s", ex)

        try:
            from alembic.config import Config
            from alembic import command
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic database migrations applied to head successfully.")
        except Exception as e:
            logger.warning("Alembic auto-upgrade fallback notice: %s", e)

    try:
        scheduler.add_job(  # type: ignore[arg-type]
            _run_dormancy_sweep_job,
            "interval",
            hours=24,
            id="dormancy_sweep",
            replace_existing=True,
        )
        scheduler.add_job(
            _run_penalty_job,
            "interval",
            hours=24,
            id="loan_penalties",
            replace_existing=True,
        )
        # Interest posting is idempotent per-calendar-month (see
        # savings_interest_service.py), so a simple daily check is safe - it
        # only actually posts anything on accounts that haven't been posted
        # yet this month, regardless of which day of the month this runs.
        scheduler.add_job(
            _run_interest_posting_job,
            "interval",
            hours=24,
            id="savings_interest",
            replace_existing=True,
        )
        scheduler.start()  # type: ignore[union-attr]
    except Exception:
        logger.exception("Failed to start background scheduler")

    logger.info("SACCO API started in '%s' environment.", settings.ENVIRONMENT)

    try:
        yield  # The application runs here while yielding control
    finally:
        # --- SHUTDOWN LOGIC ---
        logger.info("Shutting down SACCO API...")
        try:
            if scheduler.running:
                scheduler.shutdown(wait=False)  # type: ignore[union-attr]
        except (RuntimeError, KeyError, asyncio.CancelledError):
            logger.debug("Scheduler shutdown interrupted")


# ---------------------------------------------------------------------------
# FastAPI App Initialization
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SACCO Management System API",
    description=(
        "Production-grade backend for a comprehensive SACCO Management "
        "System, covering member management, savings, credit & loans, "
        "accounting, HR & payroll deductions, shares management, group "
        "management, notifications, and risk & compliance."
    ),
    version="1.0.0",
    lifespan=lifespan,  # <-- Register the lifespan here
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list if "*" not in settings.cors_origins_list else ["*"],
    allow_origin_regex=r"https?://.*" if "*" in settings.cors_origins_list else None,
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/dashboard", tags=["Dashboard"])
def referral_dashboard():
    return FileResponse("static/dashboard.html")


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
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": str(exc) if settings.ENVIRONMENT != "production" else "An unexpected error occurred. Please try again or contact support."
        },
    )
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response
