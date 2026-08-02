# SACCO Management & Operations System — Complete System Documentation

---

## 1. System Overview & Architecture

The **Digital SACCO Management System** is an enterprise-grade financial and operational platform designed for Savings and Credit Cooperative Organizations (SACCOs) and microfinance institutions. The platform automates member management, savings deposits and withdrawals, loan application workflows, automated double-entry General Ledger (GL) posting, automated Anti-Money Laundering (AML) deposit risk flagging, micro-payroll deductions, share subscriptions, and real-time executive dashboard analytics.

The system is designed with a decoupled architecture comprising three core subsystems:

```
                  ┌─────────────────────────────────────────┐
                  │        SACCO Admin Staff Portal         │
                  │        (sacco_admin: Port 5174)         │
                  └────────────────────┬────────────────────┘
                                       │ REST / HTTP (JSON + Bearer JWT)
                                       ▼
┌─────────────────────────┐   REST API ┌─────────────────────────────────────────┐
│  SACCO Member Web App   │───────────►│      SACCO FastAPI Backend API          │
│(sacco_member: Port 5173)│            │       (sacco_system: Port 8000)         │
└─────────────────────────┘            └────────────────────┬────────────────────┘
                                                            │
                                                            ▼
                                               ┌───────────────────────────┐
                                               │ Relational Database       │
                                               │ (PostgreSQL / SQLite)     │
                                               └───────────────────────────┘
```

### 1.1 Technology Stack

| Layer | Component | Description / Choice Rationale |
|---|---|---|
| **Backend API Framework** | Python 3.14 + FastAPI | High-performance, asynchronous REST API with automatic OpenAPI / Swagger documentation and Pydantic data validation. |
| **Database ORM** | SQLAlchemy 2.0 | Unified object-relational mapping supporting relational schema modeling, foreign key integrity, and atomicity across transactions. |
| **Database Engine** | PostgreSQL (Prod) / SQLite (Dev) | Enterprise relational persistence supporting ACID transactions, row-level locking, and indexed query performance. |
| **Database Migrations** | Alembic | Schema-as-code migration management tracking database structural changes across deployment environments. |
| **Async Task Engine** | APScheduler | Background scheduler executing daily automated membership dormancy sweeps and recurring tasks. |
| **Testing Framework** | Pytest + AnyIO | Automated testing suite executing 41 unit and integration tests across in-memory database instances. |
| **Staff Frontend Portal** | HTML5 / Vanilla JS / CSS3 | Zero-framework, lightweight SPA (`sacco_admin`) providing tellers, managers, accountants, and auditors with operational tools. |
| **Member Frontend App** | HTML5 / Vanilla JS / CSS3 | Responsive client portal (`sacco_member`) enabling SACCO members to check savings balances, apply for loans, and monitor repayments. |

---

## 2. Security & Authentication Architecture

### 2.1 OAuth2 & JWT Token Flow
* **Login Endpoint**: `POST /api/v1/auth/login` accepts `application/x-www-form-urlencoded` credentials (`username` and `password`).
* **Tokens Issued**:
  * **Access Token**: Short-lived JSON Web Token (JWT) valid for 60 minutes.
  * **Refresh Token**: Long-lived token valid for 7 days (`POST /api/v1/auth/refresh`).
* **Password Hashing**: Passlib with `bcrypt` encryption ensures secure password storage in the `users` table.

### 2.2 Role-Based Access Control (RBAC)
Every endpoint enforcing access control is guarded by the `require_roles(...)` dependency. System roles include:

| Role | Operational Scope & Permissions |
|---|---|
| `admin` | Full system administrative privileges; user management, audit logs, system configuration. |
| `manager` | Operational oversight; loan approval/rejection, risk flag resolution, product management. |
| `accountant` | Financial operations; manual journal entry posting, chart of accounts management, trial balance, financial reports. |
| `teller` | Front-office operations; member registration, opening savings accounts, processing cash deposits/withdrawals, recording loan repayments. |
| `loan_officer` | Credit management; reviewing loan applications, inspecting collateral/guarantors, performing credit checks. |
| `hr_officer` | Employer management; processing bulk payroll deduction files and exception reconciliation. |
| `auditor` | Read-only compliance access; audit log inspection, financial reports, risk portfolio analytics. |
| `member` | Restricted self-service access; viewing personal savings accounts, applying for loans, responding to guarantee requests. |

---

## 3. Core Module & API Endpoint Reference

### 3.1 Authentication & System Administration (`/api/v1/auth`, `/api/v1/users`, `/api/v1/admin`)
* `POST /api/v1/auth/login`: Authenticates staff/members and issues JWT access and refresh tokens.
* `POST /api/v1/auth/refresh`: Obtains a new access token using a valid refresh token.
* `GET /api/v1/auth/me`: Retrieves current authenticated user profile, assigned role, and linked `member_id`.
* `POST /api/v1/users`: Creates a new system user account.
* `GET /api/v1/admin/audit-logs`: Retrieves immutable system audit logs tracking actor, action, entity type, entity ID, and timestamp.

### 3.2 Member Management (`/api/v1/members`)
* `POST /api/v1/members`: Registers a new member (generates a sequential `member_number` e.g., `MB26080001`).
* `GET /api/v1/members`: Lists and filters members by name, national ID, branch, or status (`active`, `dormant`, `suspended`, `exited`).
* `GET /api/v1/members/{member_id}`: Fetches 360-degree member profile details including savings accounts, active loans, and share holdings.
* `PATCH /api/v1/members/{member_id}`: Updates member contact information or status.

### 3.3 Savings & Deposit Management (`/api/v1/savings`)
* `POST /api/v1/savings/products`: Configures a savings product (interest rate p.a., minimum balance, interest frequency, lock-in period, GL liability account).
* `POST /api/v1/savings/accounts`: Opens a new savings account for a member (generates account number e.g., `SV2608000001`).
* `GET /api/v1/savings/accounts`: Lists all active savings accounts across the SACCO.
* `GET /api/v1/savings/members/{member_id}/accounts`: Lists savings accounts belonging to a specific member.
* `POST /api/v1/savings/accounts/{account_id}/transactions`: Processes an atomic deposit, withdrawal, or transfer transaction.
* `POST /api/v1/savings/post-interest`: Triggers automated monthly interest calculation and posting to all eligible accounts.
* `GET /api/v1/savings/accounts/{account_id}/statement/pdf`: Generates an official printable HTML/PDF savings account statement.

### 3.4 Credit & Loan Management (`/api/v1/loans`)
* `POST /api/v1/loans/products`: Configures loan products (interest rate, interest calculation method, min/max amount, repayment period, GL asset account).
* `POST /api/v1/loans/applications`: Submits a loan application with specified principal, term, guarantors, and collateral items.
* `POST /api/v1/loans/applications/{id}/approve`: Approves a loan application (requires `manager` or `admin` role).
* `POST /api/v1/loans/applications/{id}/disburse`: Disburses loan principal via savings account, mobile money, bank transfer, or cash.
* `POST /api/v1/loans/applications/{id}/repay`: Records a loan principal/interest repayment, updating schedule balances and GL accounts.
* `GET /api/v1/loans/applications/{id}/schedule`: Generates the reducing-balance (declining balance) loan amortization schedule.

### 3.5 Accounting & General Ledger (`/api/v1/accounting`)
* `GET /api/v1/accounting/accounts`: Lists active Chart of Accounts (`asset`, `liability`, `equity`, `income`, `expense`).
* `POST /api/v1/accounting/accounts`: Creates a new Chart of Account (e.g., Code `2000 - Member Savings Liability`).
* `POST /api/v1/accounting/journal-entries`: Posts a manual double-entry journal voucher. Asserts `sum(debits) == sum(credits)`.
* `GET /api/v1/accounting/trial-balance`: Compiles real-time trial balance line totals for all general ledger accounts.
* `GET /api/v1/accounting/gl-settings` / `PATCH`: Configures default system GL accounts (Cash, Mobile Money clearing, Interest Income, Interest Expense).

### 3.6 Risk & Compliance (`/api/v1/risk`)
* `GET /api/v1/risk/flags`: Lists open and resolved risk compliance flags.
* `POST /api/v1/risk/flags/{flag_id}/resolve`: Resolves a risk flag with resolution notes and staff user ID.
* `GET /api/v1/risk/portfolio-at-risk`: Computes real-time Portfolio at Risk (PAR 30, PAR 60, PAR 90) and overdue loan totals.
* `POST /api/v1/risk/dormancy-sweep`: Manually triggers the automated membership dormancy check.

### 3.7 Financial Reports & Analytics (`/api/v1/reports`)
* `GET /api/v1/reports/balance-sheet`: Generates standard Balance Sheet statement (Assets = Liabilities + Equity).
* `GET /api/v1/reports/income-statement`: Generates Income Statement for a date range (Revenue - Expenses = Net Income).
* `GET /api/v1/reports/cash-flow`: Computes Cash Flow Statement across Operating, Financing, and Investing activities.
* `GET /api/v1/reports/dashboard-trends`: Returns monthly trend data for savings deposits vs. withdrawals and disbursements vs. repayments.

---

## 4. Financial Engine & Accounting Integrity

### 4.1 Automated Double-Entry GL Posting
The system strictly enforces double-entry bookkeeping rules via `app.services.gl_posting_service`. Every financial transaction automatically generates a balanced journal entry:

#### 1. Savings Deposit (Amount = $X$)
* **Debit**: Cash / Mobile Money Settlement Account (Asset) $\rightarrow +X$
* **Credit**: Savings Product GL Liability Account (Liability) $\rightarrow +X$

#### 2. Savings Withdrawal (Amount = $Y$)
* **Debit**: Savings Product GL Liability Account (Liability) $\rightarrow -Y$
* **Credit**: Cash / Mobile Money Settlement Account (Asset) $\rightarrow -Y$

#### 3. Loan Disbursement (Principal = $P$)
* **Debit**: Loan Product GL Asset Account (Asset - Loans Receivable) $\rightarrow +P$
* **Credit**: Settlement Account / Member Savings Account $\rightarrow +P$

#### 4. Loan Repayment (Principal = $P_{rep}$, Interest = $I_{rep}$)
* **Debit**: Cash / Member Savings Account $\rightarrow +(P_{rep} + I_{rep})$
* **Credit**: Loan Product GL Asset Account $\rightarrow -P_{rep}$
* **Credit**: Interest Income Account (Income) $\rightarrow +I_{rep}$

### 4.2 Automated Anti-Money Laundering (AML) Risk Flagging
When a savings deposit transaction is processed in `app/routers/savings.py`:
1. The transaction updates `account.balance` and creates a `SavingsTransaction` record.
2. The transaction triggers `post_savings_transaction_gl()` to generate double-entry GL journal lines.
3. **AML Evaluation**: If `payload.amount >= Decimal("5000000")` (UGX 5,000,000):
   * An automated `RiskFlag` record is instantiated with `flag_type=RiskFlagType.AML_SUSPICIOUS_DEPOSIT` and `member_id=account.member_id`.
   * The risk flag is added to the database session.
4. **Notification**: Transaction alert notification is generated.
5. **Commit**: `db.commit()` commits the savings account balance, transaction record, GL entry, AML risk flag, and notification records atomically.

If any failure occurs prior to `db.commit()`, the entire database session rolls back, ensuring that no orphaned notifications or incorrect balances are persisted.

---

## 5. Frontend Portals Overview

### 5.1 Staff Admin Portal (`sacco_admin`)
* **Technology**: Vanilla JavaScript ES Modules, HTML5, CSS3 with custom variables, Hash Router (`#/dashboard`, `#/savings`, `#/loans`, `#/accounting`).
* **Key Components**:
  * `js/views/dashboard.js`: Renders executive KPI cards (Total Members, Total Deposits, Loan Portfolio, PAR %, Liquidity), API latency chart, and trend lines.
  * `js/views/savings.js`: Manages savings product catalogs, opens member savings accounts, processes deposits/withdrawals, and posts interest.
  * `js/views/loans.js`: Interactive loan application processing, guarantor inspection, disbursement channel execution, and amortization table rendering.
  * `js/views/accounting.js`: Interactive journal entry builder with client-side and server-side balance validation, trial balance view, and chart of accounts management.
  * `js/views/members.js`: 360-degree member profile view, status management (active, dormant, suspended, exited), and statement printing.

### 5.2 Member Web Application (`sacco_member`)
* **Technology**: Single-page web application (`sacco_member`) with native browser ES modules.
* **Key Components**:
  * `js/views/dashboard.js`: Displays member total savings, active loan summary, share value, and recent activity timeline.
  * `js/views/savings.js`: Member view of savings accounts, balance updates, transaction history, and mobile money deposit/withdrawal simulation.
  * `js/views/loans.js`: Member loan application workflow with guarantor selection and repayment schedules.
  * `js/views/profile.js`: Member contact details, next of kin, and security password update.

---

## 6. Installation & Deployment Guide

### 6.1 Backend API Setup (`sacco_system`)

```bash
# 1. Clone repository & navigate to backend directory
cd d:\Dev\project\sacco_system

# 2. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate      # Linux/macOS: source venv/bin/activate

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Configure environment settings (.env)
# Create .env file with the following variables:
DATABASE_URL=sqlite:///./sacco.db
ENVIRONMENT=development
SECRET_KEY=your-secure-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# 5. Launch the FastAPI development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Access Interactive API Documentation:
* **Swagger UI**: `http://127.0.0.1:8000/docs`
* **ReDoc UI**: `http://127.0.0.1:8000/redoc`

### 6.2 Frontend Web Clients Setup

#### Staff Admin Portal (`sacco_admin`):
```bash
cd d:\Dev\project\sacco_admin
python -m http.server 5174
# Open http://localhost:5174 in web browser
```

#### Member Web Portal (`sacco_member`):
```bash
cd d:\Dev\project\sacco_member
python -m http.server 5173
# Open http://localhost:5173 in web browser
```

### 6.3 Docker Compose Deployment (Production)

```bash
cd d:\Dev\project\sacco_system
docker compose up --build -d
```
This containerizes the FastAPI backend, launches a PostgreSQL database, runs Alembic migrations (`alembic upgrade head`), and starts the Uvicorn production ASGI server.

---

## 7. Automated Testing & Verification

The project includes an extensive test suite in `sacco_system/tests` powered by Pytest:

```bash
cd d:\Dev\project\sacco_system
.\venv\Scripts\python.exe -m pytest
```

### 7.1 Test Coverage Summary

| Test Module | Focus Area | Executed Tests | Status |
|---|---|---|---|
| `test_auth.py` & `test_2fa.py` | OAuth2 password flow, JWT tokens, 2FA lifecycle | 5 | PASSED |
| `test_members.py` | Member creation, duplicate NID checks, soft deletion | 3 | PASSED |
| `test_savings.py` | Savings deposits, minimum balance check, AML flags | 5 | PASSED |
| `test_loans.py` | Loan applications, guarantor approval, repayments | 5 | PASSED |
| `test_health_and_accounting.py` | Health endpoint, GL unbalanced entry rejection | 2 | PASSED |
| `test_vaults.py` & misc | Vault transfers, news, branch reports, SMTP alerts | 21 | PASSED |
| **Total Test Execution** | **Comprehensive system verification** | **41 / 41** | **PASSED (100%)** |

---

## 8. Summary of Recent System Enhancements

1. **Fixed AML Deposit Flagging Bug**: Corrected `RiskFlag` model instantiation in `app/routers/savings.py` to use `RiskFlagType.AML_SUSPICIOUS_DEPOSIT` without invalid `severity` attributes, ensuring large deposit transactions (≥ UGX 5M) execute atomically and flag risk without failing or rolling back.
2. **Fixed Negative Dashboard Total Deposits**: Added `GET /api/v1/savings/accounts` endpoint and updated admin dashboard calculation (`js/views/dashboard.js`) to compute Total Deposits directly from active member savings account balances (`sa.balance`) with non-negative display formatting.
3. **Comprehensive Verification**: Executed Pytest automated test suite across all 41 test suites with 100% pass rate.
