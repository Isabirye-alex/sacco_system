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
    loans,
    members,
    notifications,
    payroll,
    risk_compliance,
    savings,
    shares,
)
from app.services.risk_service import sweep_dormant_members

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
app.include_router(accounting.router)
app.include_router(payroll.router)
app.include_router(shares.router)
app.include_router(notifications.router)
app.include_router(groups.router)
app.include_router(risk_compliance.router)


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


@app.on_event("startup")
def on_startup():
    # if settings.ENVIRONMENT == "development":
    #     Base.metadata.create_all(bind=engine)

    scheduler.add_job(_run_dormancy_sweep_job, "interval", hours=24, id="dormancy_sweep", replace_existing=True)
    scheduler.start()
    logger.info("SACCO API started in '%s' environment.", settings.ENVIRONMENT)
    
@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown(wait=False)
