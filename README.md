# Petrol Bunk Manager API

FastAPI backend for the pump manager UI (`../ui`), backed by PostgreSQL,
organized as controller → service → repository → model layers.

## Database

- Database: **`Ga_Petrol_Bunk`**
- 23 tables, matching the supplied schema with the naming convention applied
  (each space-separated word capitalized, joined with `_` — e.g.
  `commission_rate_history` → `Commission_Rate_History`). Column names are
  left as given (snake_case, e.g. `password_hash`, `join_date`).
- 3 additions beyond the supplied DDL (flagged during the UI-vs-schema
  review, see comments in the model files for each):
  - **`Stations`** — the dealership profile (name, brand, GSTIN, address,
    mobiles, logo, `audit_contact_email`) wasn't in the supplied schema, but
    the UI reads/writes it across Landing, Login, Layout, Offers, and Credit
    Bills, and actively edits `audit_contact_email` from the Fuel Entry audit
    modal. In practice a single row — enforced at the service layer, not the
    schema.
  - **`Credit_Customer_Bills`** — general documents uploaded onto a credit
    customer's record (the "Bills & Documents" section), mirroring
    `Fuel_Entry_Bills` but for a customer rather than a fuel entry.
  - **`Credit_Ledger_Entries.bill_file_name` / `bill_file_url`** — two
    nullable columns (not a separate table) for the single optional bill a
    manager can attach directly to one credit-ledger row.
  - **`Refresh_Tokens`** — not part of the supplied schema; backs rotating,
    revocable JWT sessions (see Security below). `Users` carries no
    session-lockout columns (no `failed_login_attempts` / `locked_until`) —
    brute-force defense is IP-rate-limiting only (`slowapi` on
    `/auth/login`), matching the supplied schema's `users` table exactly.
- The retail fuel rate (₹/L for petrol/diesel/oil) has **no table** — every
  sale already snapshots its own rate on `Fuel_Readings.rate`, so the
  pre-fill default for a new entry is derived from the latest reading rather
  than a master-rate table. `Commission_Rate_History` (the dealer's OMC
  margin, separate from the retail rate) is unaffected and implemented as given.

## Layout

```
app/
  core/            config, JWT/password security, DB engine, middleware, rate limiting
  models/          SQLAlchemy ORM models (async) — one file per domain area
  schemas/         Pydantic request/response models (validation lives here)
  repositories/    data access — only place that writes SQLAlchemy queries
  services/        business logic — auth flows, RBAC-adjacent rules, orchestration
  controllers/     FastAPI routers — thin, just wiring HTTP to services
  api/
    deps.py        shared dependencies: DB session, current-user, role guards
    v1/router.py   aggregates all controllers under /api/v1
  main.py          app factory: middleware, exception handlers, router mount
alembic/           DB migrations (schema is managed via migrations, not create_all)
scripts/           one-off ops scripts (e.g. bootstrapping the first admin)
```

Implemented end-to-end as the reference pattern, **verified against a live
Postgres instance**: **Auth**, **Users**, **Station**, **Employees** (+
salary history), **Attendance**. The remaining tables (Commission Rate
History, Lubricants, Credit Customers, Fuel Entry family, Expenses, Offers,
Employee Credits) have models in place so `alembic upgrade head` creates
every table now — their service/controller/schema layers (the "page-wise
API" + business logic) come next, following the same pattern.

## Security measures baked in

- Passwords hashed with **argon2** (via passlib), never bcrypt's truncated-72-byte scheme.
- **JWT access tokens** (short-lived, 15 min default) + **rotating refresh tokens**
  stored server-side as a SHA-256 hash (never the raw token), so a leaked DB
  can't be replayed and a refresh token is single-use.
- Login error responses don't distinguish "no such user" from "wrong
  password", and a dummy hash comparison runs even when the account doesn't
  exist, so timing can't be used to enumerate accounts.
- **Role-based access control** (`admin` / `manager` / `staff`, matching the
  `Users.role` CHECK constraint) enforced via FastAPI dependencies
  (`require_admin`, `require_manager_or_admin`) at the router level.
- Global exception handler returns a generic 500 body and logs the real
  error server-side — stack traces and SQL errors never reach the client.
- `CORSMiddleware` restricted to an explicit origin allowlist,
  `TrustedHostMiddleware`, and a security-headers middleware
  (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, etc.).
- All queries go through SQLAlchemy's parameter binding (repositories never
  interpolate raw strings into SQL), so standard ORM usage is SQL-injection safe.
- `/docs`, `/redoc`, `/openapi.json` are disabled when `ENVIRONMENT=production`.
- Secrets (DB password, JWT signing key) only ever come from environment
  variables / `.env`, never hardcoded; `SECRET_KEY` is validated to reject
  the example placeholder, and a password containing URL-special characters
  (`@`, `:`, `/`, ...) is safe — credentials are URL-encoded when building
  the connection string (`app/core/config.py`).
- Passwords require length + upper/lower/digit complexity (`app/schemas/user.py`).

## Backups

`scripts/backup_db.sh` dumps the live DB via `pg_dump` directly at
`POSTGRES_HOST:POSTGRES_PORT` from `.env` — works whether Postgres is a
local native install or the bundled `docker compose` container, since both
are reachable the same way over that host/port. Falls back to
`/Library/PostgreSQL/*/bin` if `pg_dump`/`psql` aren't on `PATH` (the default
for the macOS EDB installer). Output is gzipped into `backups/`
(git-ignored), integrity-checked, and anything older than `RETENTION_DAYS`
(default 14) is pruned. Run it on a schedule so a corrupted DB or a
compromised host never costs you more than a day of data:

```bash
./scripts/backup_db.sh
```

**Automate it** — cron (Linux) or `launchd` (macOS), once a night:

```cron
0 2 * * * cd /path/to/api && ./scripts/backup_db.sh >> /var/log/petrol_bunk_backup.log 2>&1
```

**Test restores regularly** — an untested backup is a hope, not a plan.
`scripts/restore_db.sh` defaults to restoring into a throwaway
`<db>_restore_test` database, verifies the table count, then drops it —
live data is never touched:

```bash
./scripts/restore_db.sh backups/Ga_Petrol_Bunk_20260830_020000.sql.gz
```

For an actual disaster-recovery restore (overwrites the live DB, requires
typing the DB name to confirm):

```bash
./scripts/restore_db.sh --force-live backups/Ga_Petrol_Bunk_20260830_020000.sql.gz
```

Because these are local-disk backups, they protect against corruption and
routine accidents but **not** against a compromised host or physical loss —
copy `backups/` to a second disk, NAS, or offsite location periodically if
that risk matters to you.

## Setup

1. **PostgreSQL.** Point at a server you already have, or run the bundled
   dev one (`docker compose up -d`).
2. **Configure env:**
   ```bash
   cp .env.example .env
   # then edit .env — set SECRET_KEY and postgres_* to match your server
   python -c "import secrets; print(secrets.token_urlsafe(64))"  # for SECRET_KEY
   ```
3. **Install deps** (Python 3.11+; a `greenlet` install is required — it's
   what lets SQLAlchemy's async engine bridge to `asyncpg`, easy to miss
   since nothing imports it directly):
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Create the database** (once) and **run migrations**:
   ```bash
   # createdb Ga_Petrol_Bunk   -- or let alembic's target DB already exist
   alembic upgrade head
   ```
5. **Bootstrap the first admin** (every other user is created via the
   authenticated `/users` endpoint, so this seed step is required once):
   ```bash
   python -m scripts.create_admin --email you@example.com --name "Your Name"
   ```
6. **Run the API:**
   ```bash
   uvicorn app.main:app --reload
   ```
   Docs at `http://localhost:8000/docs` (development only).

## Adding a new module (e.g. Fuel Entry)

Follow the Employees module as a template:
1. Model already exists in `app/models/<domain>.py` (see the file for the exact table).
2. `app/schemas/<name>.py` — Create/Update/Out Pydantic schemas.
3. `app/repositories/<name>_repository.py` — extend `BaseRepository`.
4. `app/services/<name>_service.py` — business rules, raises `app.core.exceptions` types.
5. `app/controllers/<name>_controller.py` — thin router, RBAC via `dependencies=[Depends(require_...)]`.
6. Register the router in `app/api/v1/router.py`.
