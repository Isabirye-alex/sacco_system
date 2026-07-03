# SACCO Management System — FastAPI Backend

A production-grade REST API backend implementing the modules described in the
SACCO Management System proposal: Member Management, Savings, Credit &
Loans, Accounting, HR & Payroll Deductions, Shares Management, Group
Management, Notifications, and Risk & Compliance, plus a System
Administration layer for users, roles, and audit logging.

## Architecture at a glance

```
app/
  core/            settings, DB engine/session, JWT + password hashing, enums
  models/          SQLAlchemy ORM models, one file per module
  schemas/         Pydantic request/response schemas
  routers/         FastAPI routers, one file per module (all business rules live here or in services/)
  services/        Reusable business logic: loan amortization, double-entry
                    posting, numbering, notifications, dormancy/PAR
  dependencies.py  Auth (get_current_user) and RBAC (require_roles) dependencies
  main.py          App wiring: routers, CORS, exception handlers, scheduler
alembic/           Database migrations (schema-as-code, see below)
tests/             Pytest suite (in-memory SQLite, no external DB needed)
```

### Design choices worth knowing about

- **Auth**: OAuth2 password flow issuing short-lived JWT access tokens
  (60 min default) plus longer-lived refresh tokens (7 days default).
  `POST /api/v1/auth/login` expects `application/x-www-form-urlencoded`
  (`username`/`password`) per the OAuth2 spec — that's what powers the
  "Authorize" button in the interactive docs.
- **RBAC**: every mutating endpoint is guarded by `require_roles(...)`.
  Roles: `admin`, `manager`, `loan_officer`, `accountant`, `hr_officer`,
  `teller`, `auditor`, `member`.
- **Double-entry accounting**: `services/accounting_service.post_journal_entry`
  refuses to post any entry where total debits ≠ total credits (HTTP 422).
  Manual entries go through `POST /api/v1/accounting/journal-entries`;
  wiring automatic postings from savings/loan transactions into the GL is
  flagged in "Known gaps" below.
- **Loan amortization**: reducing-balance (declining balance) schedule
  generation in `services/loan_calculator.py`, matching standard SACCO loan
  product design.
- **Payroll reconciliation**: each uploaded deduction line is matched
  against a loan or savings account and applied immediately; unmatched
  lines are flagged `EXCEPTION` rather than failing the whole batch.
- **Dormancy sweep**: runs automatically every 24h via APScheduler
  (`app/main.py`) and can be triggered manually via
  `POST /api/v1/risk/dormancy-sweep`.
- **IDs**: UUID (string) primary keys everywhere, business-friendly
  sequential numbers (`member_number`, `account_number`, `loan_number`) are
  generated separately for humans/statements.

## Getting started (local, SQLite, fastest path)

```bash
cd sacco_system
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set:
#   DATABASE_URL=sqlite:///./sacco.db
#   ENVIRONMENT=development   (auto-creates tables on startup; skip Alembic for a quick spin)

uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for interactive Swagger UI, or
http://127.0.0.1:8000/redoc for ReDoc.

## Getting started (PostgreSQL, Docker Compose — recommended for anything beyond a quick spin)

```bash
cp .env.example .env     # adjust SECRET_KEY at minimum
docker compose up --build
```

This starts Postgres, runs `alembic upgrade head`, then starts the API on
`http://localhost:8000`.

## Database migrations (Alembic)

The project ships with Alembic wired to `app.core.database.Base.metadata`
(`alembic/env.py`) but **no migration files are committed**, since
generating an accurate autogenerate diff requires connecting to a live,
empty database — which wasn't available while building this in a sandboxed
environment. Generate the initial migration once, locally:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

For local SQLite dev only, you can skip Alembic entirely by setting
`ENVIRONMENT=development` in `.env`, which triggers `Base.metadata.create_all()`
on startup as a convenience. **Never rely on that in production** — always
use Alembic there, since `create_all()` cannot apply schema changes to
existing tables.

## Running the tests

```bash
pip install -r requirements.txt
pytest
```

The suite uses an isolated in-memory SQLite database per test (see
`tests/conftest.py`) and exercises full workflows: registration/login,
member CRUD + search, savings deposits/withdrawals with minimum-balance
enforcement, the complete loan lifecycle (apply -> guarantor acceptance ->
approval -> disbursement -> repayment), and double-entry journal validation.

## Authentication quick reference

```bash
# Register (see the note below about locking this down in production)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@sacco.example","full_name":"Admin","password":"ChangeMe123!","role":"admin"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=admin@sacco.example&password=ChangeMe123!"

# Authenticated request
curl http://localhost:8000/api/v1/members \
  -H "Authorization: Bearer <access_token>"
```

> The `role` field is accepted on `/auth/register` for convenience in this
> reference implementation. In a real deployment, lock this down — e.g.
> only admins can create staff accounts, or self-registration is
> restricted to the `member` role and everything else requires an
> admin-only user-creation endpoint.

## Endpoint map (high level)

| Module | Prefix | Highlights |
|---|---|---|
| Auth | `/api/v1/auth` | register, login, refresh, me, change-password |
| System Administration | `/api/v1/admin` | list/update users, audit logs |
| Member Management | `/api/v1/members` | CRUD, search + pagination, soft-delete (exit) |
| Savings | `/api/v1/savings` | products, accounts, deposits/withdrawals |
| Credit & Loans | `/api/v1/loans` | products, applications, guarantor workflow, approval, disbursement, repayment, schedule |
| Accounting | `/api/v1/accounting` | chart of accounts, journal entries (double-entry enforced), trial balance |
| HR & Payroll | `/api/v1/payroll` | employers, payroll deduction file upload + auto-reconciliation |
| Shares | `/api/v1/shares` | products, holdings, subscribe/transfer/redeem, dividend declaration |
| Notifications | `/api/v1/notifications` | queue + background dispatch (email/SMS/push stub) |
| Group Management | `/api/v1/groups` | groups, membership, contributions |
| Risk & Compliance | `/api/v1/risk` | risk flags, portfolio-at-risk (PAR), dormancy sweep |

Full request/response schemas are always available live at `/docs`.

## Known gaps / next steps (being upfront about scope)

This is a strong, testable foundation — not a claim that every line item in
the original proposal (mobile money integration, SASRA regulatory report
templates, biometric KYC, SMS/USSD channels, etc.) is fully implemented.
Specifically:

- **GL auto-posting**: savings/loan transactions update balances directly
  but don't yet auto-post to the general ledger; `accounting_service.post_journal_entry`
  is ready to be called from those routers once your chart of accounts is finalized.
- **Real notification providers**: `services/notification_service.dispatch()`
  is a logging stub — swap in real SMTP/Africa's Talking/FCM calls where marked.
  Environment variables for all three are already in `.env.example`.
- **Interest posting job**: no scheduled job compounds/posts savings interest
  yet (only the dormancy sweep is scheduled) — `SavingsTxnType.INTEREST_POSTING`
  exists on the model for when you add it, following the same `apscheduler`
  pattern used for the dormancy sweep in `app/main.py`.
- **Migrations**: initial Alembic migration isn't committed (see above) —
  generate it against your target DB before first deploy.
- **Rate limiting / brute-force protection** on `/auth/login` isn't included;
  add `slowapi` or an API-gateway-level limiter before exposing this publicly.
