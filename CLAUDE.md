# PIE Manager — Technical Guide

## Absolute rule: update documentation with code changes

**After every code change that impacts user-facing behaviour, installation, or architecture:**
1. Update `docs/INSTALLATION.md` and `docs/SAUVEGARDE.md` if installation or backup steps change
2. Update `README.md` if prerequisites, commands, or features change
3. Update `CLAUDE.md` if architecture, key rules, or technical patterns change

Failing to update docs creates drift between code and documentation, which misleads future users and developers.

**Never hardcode a snapshot count** (test case count, function count, "N tests pass in Xs")
in this file. These numbers drift the moment more code is added and nobody reliably comes
back to update them. Distinguish:
- **Fixed policy/threshold values** (100% coverage rule, 94% branch threshold, port numbers,
  interval configs) — targets/config, not measurements of current state. Fine to hardcode.
- **Snapshot counts of current codebase size** (how many tests exist, how long a suite takes) —
  will drift. Point to a command instead (`pytest --collect-only -q`, `npx vitest list`,
  `go test ./... -cover`), or state the qualitative fact only.
- **Immutable historical facts** ("all 10 occurrences were fixed in this bug fix") — describe a
  one-time past event, not an ongoing metric. Fine to hardcode.

## Absolute rule: 100% test coverage

**Absolute rule**: every code change or new feature must be accompanied by tests ensuring 100% coverage of the modified/added code. Never commit code without its tests.

- Backend: `cd backend && python -m pytest tests/ --cov=app --cov-report=term-missing --cov-branch -q`
- Frontend: `cd frontend && npm test` (must exit 0)
- Installer (Go): `cd installer && go test ./... -cover` — covers all pure utility functions
- Use `db_session.flush()` (never `commit()`) in test fixtures
- For Celery tasks: call the function directly (not `.delay()`), mock DB calls

### Installer test coverage policy

The Go installer (`installer/`) has two categories of functions:

**Fully testable (must be 100% covered):** `findAvailablePort`, `readAppPort`,
`readInstalledVersion`, `updateEnvPort`, `detectComposeCmd`, `copyFile`,
`githubLatestAssetURL`, `downloadFile`, `extractZipEntryBySuffix`.
These pure utility functions live in `common.go` (shared Linux/Windows) and
`install.go`/`start.go` (Linux only), tested in `install_test.go`/`common_test.go`.
The last three have no actual Windows dependency (plain HTTP + zip) despite existing
to support a Windows-only fallback — see "Store-independent WSL2/winget install" below —
so they're written as real testable functions instead of being dumped into the
untestable bucket just because their caller lives in `main_windows.go`.

**Intentionally untestable:** `runInstall`, `runStartWithCompose`, `forceRecreate`,
`notify`, `podmanImageExists`, `focusExistingWindow`, `openBrowser`,
all functions in `main_windows.go`. These exec external programs (Podman, browser,
OS notifications, Windows API) and require integration-level testing. They are covered
by the CI smoke test (`go build + ./pie-manager version`). Overall installer coverage is
necessarily low (check `go test ./... -cover` for the current figure) — expected and
acceptable for a system-interaction binary.

**Installer structure:**
- `common.go` — shared code (no build constraint): `Version`, `defaultPort`, `findAvailablePort`, `readAppPort`
- `main.go` — Linux CLI dispatcher (`//go:build linux`)
- `main_windows.go` — Windows full installer (`//go:build windows`)
- `install.go`, `start.go`, `install_test.go` — Linux only (`//go:build linux`)
- `launcher/` — separate Go module, builds `launcher.exe` (Windows WebView2 native launcher)
- `testing/` — reproducible scripts to recreate the win11 libvirt/QEMU test VM from scratch on
  a fresh Fedora host (not part of the shipped product; see its own `README.md`)

## Absolute rule: refactor after every change

**After every code change** — bug fix, feature, or refactor — scan both the modified code and its tests for improvement opportunities before committing:

1. **Code**: duplicated logic? extract a helper. Long function? split it. Magic constant? name it.
2. **Tests**: duplicated setup? share a fixture. Identical assertions? parameterise. Obscure name? rename.
3. **Coverage**: re-run coverage after refactor — must still be 100% statements, branches, functions, lines.

The goal is a codebase where every commit leaves the code *cleaner* than before the change, not just correct. Small refactors done continuously prevent large debt from accumulating.

## Overview

Multi-account investment portfolio tracking app (Portfolio 1 + Portfolio 2).
All data entry goes through the UI — no import mechanism exists.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + PatternFly 5 + TanStack Query v5 + Vite |
| Backend | Python FastAPI + SQLAlchemy 2.0 async + Celery + Redis |
| Database | PostgreSQL 16 |
| Deployment | **Podman** Compose (never Docker) |
| Containerfiles | `Containerfile` (never `Dockerfile`) |

## Mandatory conventions

- **Code in English** — all source code, variable names, function names, comments, commit messages, and PR descriptions MUST be in English. Exception: README.md and user-facing documentation files may be in French. The UI itself is translated via i18n (fr/en).
- **Podman only** — never use `docker` or `docker-compose`
- **Containerfile** — never Dockerfile
- Volumes with `:z` flag for SELinux (Fedora) — silently ignored on macOS/Windows
- Frontend port: 5173 (Vite dev) / proxied through HAProxy in prod
- Backend port: **8000** (internal only in prod — not exposed, accessed via HAProxy)
- HAProxy internal port: **8080** (not 80 — rootless Podman cannot bind privileged ports < 1024)
- **Library/framework APIs**: when searching for solutions involving a library or framework component, always check the official component documentation website first — never guess API signatures or behavior from memory.
- **Destructive action confirmation**: never use `window.confirm()` — use the reusable `<ConfirmModal>` component (`frontend/src/components/ConfirmModal.tsx`) so confirmation dialogs match the PatternFly design system.

## Container architecture

**`backend/Containerfile` runs Python 3.14** (matches CI's `integration-tests` job — see
"Backend tests" below). Bumping the Python version here is not risk-free just because CI's
test job already passes on that version: CI's job does a bare `pip install` on the GitHub
runner (which ships a lot of build tooling already), it never builds this Containerfile.
When `psycopg2-binary` was pinned to a version with no prebuilt wheel for 3.14, CI stayed
green while `podman build` failed outright trying to compile it from source. Always verify a
Python-version bump by actually running `podman build -f backend/Containerfile backend/`,
not just by trusting CI.

### Development (compose.yaml)

```
compose.yaml
├── postgres (PostgreSQL 16)
├── redis
├── backend (FastAPI + Celery Beat)
├── worker (Celery worker)
└── frontend (Vite dev server, port 5173)
```

### Production (compose-prod.yaml)

```
compose-prod.yaml
├── postgres (PostgreSQL 16)          restart: unless-stopped
├── redis                             restart: unless-stopped
├── backend (FastAPI + Celery Beat)   restart: unless-stopped, no exposed ports
├── worker (Celery worker)            restart: unless-stopped
├── frontend (Vite dev server)        restart: unless-stopped, no exposed ports
└── haproxy (reverse proxy)           restart: unless-stopped, port APP_PORT:8080
```

In production, **HAProxy** is the single public entry point. It routes:
- `/api/*` → `backend:8000` (FastAPI) — active health check on `/api/admin/health`
- `/*` → `frontend:5173` (Vite dev server)

Backend and frontend containers have no exposed ports — all traffic flows through HAProxy.
HAProxy uses `parse-resolv-conf` + `resolve-prefer ipv4` to handle Podman's DNS correctly
on both Docker (127.0.0.11) and Podman (gateway IP) environments.

### Port selection (production)

Default port: **14943** (constant `defaultPort` in `installer/install.go`).

At install time, `findAvailablePort(14943)` scans from 14943 upward for the first free TCP port. The chosen port is written to `~/.local/share/pie-manager/.env` as `APP_PORT=<n>`. At subsequent starts, `runStart()` reads `APP_PORT` from `.env` and checks whether it is still free; if not, it picks a new port and rewrites `.env`.

The `.env` file also holds `APP_VERSION=<n>`. Both variables are consumed by `compose-prod.yaml` via `${APP_PORT:-14943}` and `${APP_VERSION:-dev}`.

## Key commands

```bash
# Development — start all services
podman compose up -d

# Rebuild backend after code change
podman compose up -d --build backend

# Logs
podman logs pie-manager_backend_1

# Access DB
podman exec pie-manager_postgres_1 psql -U pie -d pie_db
```

**`pie-manager_postgres_1` holds real personal portfolio data — never experiment against it.**
Beyond a read-only `SELECT`, use an isolated throwaway container instead (see "Testing a
data-migrating Alembic revision" below). Exception: a one-time manual correction after the
user has explicitly confirmed the target value (e.g. fixing one wrong `cash_balance_eur` row).

### Removing a single container fails with "has dependent containers"

When swapping one container for a locally-built image (e.g. testing a fixed `backend`/`worker`
image before publishing it), `podman rm` on that one container can fail:
```
Error: container ... has dependent containers which must be removed before it: ...
```
This happens because `frontend`/`haproxy` share `backend`'s network namespace under
`podman-compose`'s default networking — removing `backend` alone is blocked by its dependents.

**Fix:** remove all related containers together (dependents first: `frontend`, `haproxy`, then
`backend`/`worker`), then recreate each individually with an explicit
`--network pie-manager_default` (and `--network-alias <service-name>` for containers other
services reach by name) instead of relying on `podman-compose`'s implicit shared-netns behavior.

## Key data model

### Broker / Account distinction (critical)

- **`brokers`** — global entity per financial institution (Degiro, IBKR, Revolut…)
  - Holds shared config: commissions, allowed_tickers, FX params, color, `is_cto`
  - One record per real broker (e.g. a single "Degiro" row for both Portfolio 1 AND Portfolio 2)
  - API: `GET/POST/PUT/DELETE /api/brokers/`
  - Python model: `app.models.broker.Broker`

- **`portfolio_accounts`** — join table Broker × Portfolio = the "Account"
  - Holds `cash_balance_eur` **per (broker, portfolio)** — key: `(portfolio_id, broker_id)`
  - Single source of truth for cash. Never sum LIQUIDITE.EURO transactions.
  - `_update_account_cash_balance(db, account_id, portfolio_id, delta)` → writes here
  - `_get_liquidity_eur()` → `SUM(portfolio_accounts.cash_balance_eur) WHERE portfolio_id=X`

- `portfolios` — portfolios (Portfolio 1 / Portfolio 2, separate tax households)
- `transactions` — all transactions (Actif/Frais/Revenu)
  - `account_id` FK → `brokers.id` (column name kept for compatibility)
  - `linked_transaction_id`: nullable self-referencing FK
  - `operation`: nullable, `Achat`/`Vente`/`Attribution` — sub-classification for `type='Actif'`
    (see "Product/Transaction typology" below)
- `products` — financial instruments — see "Product/Transaction typology" below for the
  `category`/`instrument_type`/`fee_type` fields
- `pools` — investment strategies (Offensive/Defensive)
- `pool_products` — pool ↔ ticker association
- `asset_prices` — historical prices (yfinance + manual)
- `daily_snapshots` — daily valuation snapshot
- `monthly_snapshots` — monthly snapshot with performance/index

## Product/Transaction typology

`Product.category` is deliberately coarse: exactly `Actif` (any financial instrument,
including cash) or `Frais` (fee line item). It is **not** an instrument-type field — do not
add checks like `category == "Cash"` or `category == "Manuel"` anywhere; those values no
longer exist. Two dedicated sub-classification fields carry that detail instead:

- `Product.instrument_type` (nullable, meaningful when `category='Actif'`): `ETF` /
  `SICAV/FCP` / `Action` / `Obligation` / `Or physique` / `Cash`. This is what all
  business logic now checks — `product.instrument_type == "Cash"`,
  `product.instrument_type == "Or physique"` — never `category` for this purpose.
- `Product.fee_type` (nullable, meaningful when `category='Frais'`): `Courtage` /
  `Tenue de compte` / `Intérêts négatifs` / `Bourse` / `TTF` / `Impôts` / `Conversion`.
  `TTF` is specifically the French Financial Transaction Tax (`FRAIS.TTF.EUR`); generic
  tax/duty tickers (`FRAIS.TAXE.EUR`/`FRAIS.TAXE.GBP`) are `Impôts`, a distinct value — do
  not conflate the two. This **supersedes, for Products, the old "typed tickers"
  convention** below — `fee_type` is now the queryable classification; the ticker itself no
  longer needs to encode the fee nature for reporting purposes (though existing fee tickers
  like `FRAIS.TAXE.EUR` / `FRAIS.COURTAGE.EUR` are kept as-is and just got a matching
  `fee_type`).
- `Transaction.operation` (nullable, meaningful when `type='Actif'`): `Achat` / `Vente` /
  `Attribution`. `Attribution` is a share grant — `unit_price` defaults to 0 but stays
  editable (some grants carry a fair-value price worth recording), while courtage/TTF are
  always forced to 0 and locked (a grant never incurs a brokerage commission). In
  `TransactionsPage.tsx`, `recomputeFees` must skip its auto-commission calculation
  entirely for `operationType==='grant'`, not just disable the courtage/TTF inputs — it
  used to compute courtage from the trade amount regardless of operation type, so typing a
  non-zero grant price produced a spurious commission estimate. The existing WACOP formula
  in `pv_service.py` already dilutes CUMP correctly whether the recorded cost is zero or
  not, so `operation` itself is purely descriptive/UI-facing; no business logic reads it.

**Cash is a financial asset in this app** — `LIQUIDITE.EURO`, `LIQUIDITE.USD`, `JPYEUR=X`
etc. all have `category='Actif', instrument_type='Cash'`. There is no separate "Cash"
category value.

**Auto-linked fee transactions use dedicated `FRAIS.*` tickers, not the parent's ticker.**
`create_transaction`/`update_transaction` in `transactions.py` create linked courtage/TTF
`Frais` rows with `ticker='FRAIS.COURTAGE.EUR'` / `ticker='FRAIS.TTF.EUR'` (not
`ticker=tx.ticker`). This was a regression at some point (git history predates the public
squash, exact commit unknown) — 2024 production data already used dedicated tickers; a
window of transactions created after the regression reused the parent asset's ticker.
Migration `mm66nn77oo88` retargets the affected historical rows (verified: exactly 9 rows,
8 parent transactions — 7 single-fee = courtage only, 1 two-fee = courtage then TTF, in
that creation order). **If you ever touch that retargeting SQL again**: compute all target
`(id, new_ticker)` pairs from a single snapshot of the *original* unmutated rows (e.g. a
temp table) before issuing any UPDATE — three sequential UPDATEs against the live table is
wrong, because the 2nd UPDATE's `ticker NOT LIKE 'FRAIS.%'` filter changes what the 3rd
UPDATE's `GROUP BY ... HAVING COUNT(*) = 2` sees, silently dropping the 2-fee group down to
1 match and skipping the TTF leg — see "Testing a data-migrating Alembic revision" below for
how this was caught and how to verify any future migration like it.

## Transaction conventions

- **Buy**: `quantity < 0`, `total_amount < 0`
- **Sell**: `quantity > 0`, `total_amount > 0`
- **Cash instrument_type** (`LIQUIDITE.EURO`, `JPYEUR=X`, any `instrument_type='Cash'`
  product): **inverted** — deposit/acquire = `quantity > 0`, withdrawal/reduce =
  `quantity < 0`. Covers both a direct account balance (LIQUIDITE.EURO) and a forex
  position (JPYEUR=X) — the sign convention is the same for both, only the UI differs
  (see below).
  - UI toggle "Deposit/Withdrawal" when `product.currency === account.currency` (direct Cash
    product on an account of the same currency, e.g. LIQUIDITE.EURO on a EUR account)
  - For a forex position where currencies differ (e.g. JPYEUR=X on a EUR account), the same
    Deposit/Withdrawal toggle still applies via `isCashDirectDeposit` in practice, since
    `Product.currency` for these tickers is stored as `EUR` (the reference currency), not the
    held foreign currency — see `TransactionsPage.tsx`'s `handleTickerChange`.
- **Or physique instrument_type** (OR.PHYSIQUE, SICAV BNP): `price` = total value (not unit
  price)
- **Fees**: typed tickers — `FRAIS.TAXE.EUR`, `FRAIS.COURTAGE.EUR`, etc., now paired with a
  `fee_type` on the Product (see "Product/Transaction typology" above). Do not add a
  `subcategory` field on `Transaction` — that was tried and reverted (see "Fee subcategory"
  design decision below); the typing lives on `Product`, not `Transaction`.

## Forex fee adjustment — critical business rule

Fees denominated in a foreign currency (e.g. `FRAIS.COURTAGE.JPY`, type=Fee, currency=JPY)
must be deducted from the forex position held in that currency (e.g. `JPYEUR=X`).

In fee transactions the `quantity` field holds the number of fee events (not currency units);
`total_amount` holds the actual fee amount in the foreign currency.

`dashboard_service._get_positions()` applies this adjustment: for each held forex ticker it
sums `total_amount` of all fee transactions whose currency matches the forex currency, then
subtracts that amount from the held quantity. This keeps the displayed JPY (or USD, etc.)
position accurate after paying broker commissions in that currency.

The same logic is mirrored in `brokers.py` for broker-level position display.

## Transaction running-balance display — `balance_eur` vs `balance_currency` (do not confuse)

Each `Transaction` row carries two running-balance columns computed at create/update time:
- `balance_eur` — a naive cumulative sum, `prev_balance_eur + total_amount_eur`, scoped per
  `(portfolio_id, account_id)` **across all currencies mixed together**. This is *not* a
  reliable "EUR cash on hand" figure once an account trades both EUR assets and a foreign
  currency (JPYEUR=X): buying/selling the forex position also feeds into this same additive
  chain, so treating it as a checkbook balance is misleading.
- `balance_currency` — the same running sum but scoped per `(portfolio_id, account_id,
  currency)`, i.e. one chain per native currency (e.g. a pure JPY ledger for JPYEUR=X trades).

**Critical: the frontend does NOT always display `balance_eur`.** In
`TransactionsPage.tsx`, the "Contrevaleur solde EUR" column uses this logic:
```
tx.currency !== 'EUR' && tx.balance_currency != null
  ? formatEUR(tx.balance_currency * tx.exchange_rate)   // non-EUR rows
  : formatEUR(tx.balance_eur)                            // EUR rows only
```
So for any non-EUR-currency transaction (JPYEUR=X, etc.), the displayed value is
`balance_currency × exchange_rate` — the raw `balance_eur` column is computed and stored but
**never shown on screen** for those rows. Do not use `balance_eur` to judge correctness on a
non-EUR row; recompute `balance_currency × exchange_rate` instead.

**Also critical: only one row per day is ever displayed.** `endOfDayCurrencyIds` in
`TransactionsPage.tsx` shows a balance only on the transaction with the **highest id** for a
given `(date, currency)` group (assumed to be the day's closing state) — every other
same-day-same-currency row shows "—" regardless of what its own `balance_eur`/
`balance_currency` columns actually contain. A raw-data "chain consistency" check
(`balance == prev + amount`) will flag many rows that are never rendered at all.

**`portfolio_accounts.cash_balance_eur` was NOT a safe ground truth either, for the same reason
— root cause now identified and fixed going forward (see below).** `_update_account_cash_balance()`
used to add `total_amount_eur` to this field for *every* transaction type/currency uniformly
(JPYEUR=X buys/sells included) — so on any broker that mixes EUR activity with a forex position
(Revolut, IBKR), `cash_balance_eur` got contaminated the same way `balance_eur` is, and diverged
from the real EUR cash position.

**Fix (in `_update_account_cash_balance`, `transactions.py`): forex-position transactions
(`ticker` ending in `EUR=X`, e.g. `JPYEUR=X`) no longer touch `cash_balance_eur` at all**, except
fee transactions (`type='Frais'`) sharing that ticker for product-linkage, which still do (a
EUR-denominated Revolut FX commission is a real cash cost). Rationale: a forex buy/sell tracks a
*currency conversion* (EUR wallet → JPY holding, valued for WACOP/PV via
`pv_service.py`'s `instrument_type='Cash' AND ticker not LIKE 'LIQUIDITE.%'` distinction), not a real EUR
cash flow — the EUR side of that conversion is already captured by the separate, manually-entered
`LIQUIDITE.EUR` deposit/withdrawal pair. See `_is_forex_position()` next to
`_update_account_cash_balance` for the exact rule.

**This is a going-forward fix only — it does not retroactively recompute history.**
`cash_balance_eur` is a stateful running total shaped by years of now-deleted/edited
transactions; it cannot be safely reconstructed from today's transaction snapshot (confirmed:
`SUM(total_amount_eur) WHERE currency='EUR'` today ≠ either broker's real, confirmed balance —
see the two contradictory examples below, still valid). A currently-wrong account must be
corrected with a one-time, targeted `UPDATE portfolio_accounts SET cash_balance_eur = <verified
value>` for that specific `(broker_id, portfolio_id)` row — never a formula, never a bulk
rewrite. Revolut/Portfolio 1 was corrected this way (confirmed real balance: 0,00€).

**There is no single derived SQL formula that reliably reconstructs the true EUR cash balance
across brokers — do not assume one, and do not invent one under pressure to "fix" a reported
gap.** Two formulas were each individually confirmed correct for *different* brokers in the same
investigation, and each was *wrong* for the other:
- Revolut/Portfolio 1: real EUR wallet = 0€ (user-confirmed). `cash_balance_eur` said -108.20€
  (wrong). `SUM(total_amount_eur) WHERE currency='EUR'` gave exactly 0.00€ (right, by luck of
  Revolut's fully-segregated EUR/JPY wallet architecture).
- IBKR/Portfolio 1: real EUR balance = 1.74€ (user-confirmed) = `cash_balance_eur` exactly
  (right, this time). `SUM(total_amount_eur) WHERE currency='EUR'` gave -18.25€ (wrong here).

This means the two brokers settle currency activity differently in ways this app's data model
doesn't cleanly capture, and no single query safely tells you which broker behaves which way.
**When a "wrong balance" is reported: verify the specific number against the user's actual
brokerage app/bank statement before proposing *any* fix** — including a "corrected" ground-truth
formula. Degiro's historical bulk-correction (anchored on `cash_balance_eur`) was safe only
because Degiro is 100% EUR with no forex activity at all, eliminating the ambiguity entirely —
do not generalize that approach to any broker with foreign-currency transactions.

**Known historical bug (fixed but not retroactively corrected everywhere):** several
`balance_eur`/`balance_currency` lookup queries in `transactions.py` filtered only by
`account_id`, not `(account_id, portfolio_id)` — since a broker (e.g. Degiro, Revolut, IBKR)
can be shared by multiple portfolios, this let one portfolio's running balance leak into
another's "previous balance" lookup. All 10 occurrences were fixed to filter on both columns.
Degiro's historical data was bulk-corrected (anchored to `cash_balance_eur`, safe because its
transactions are 100% EUR). Revolut/IBKR's *transaction-level* `balance_eur`/`balance_currency`
history was **left uncorrected** (a bulk correction there requires computing across mixed
EUR+JPY activity, which is not a simple sum — see above — do not attempt a blind bulk fix
without re-deriving the exact intended formula first). This is separate from
`portfolio_accounts.cash_balance_eur`, which IBKR's has always been accurate and Revolut's is
now individually corrected (see the forex-position fix above).

**Gap noticed while implementing the forex-position fix — now fixed:** `update_transaction`'s
`date_changed` branch used to never call `_update_account_cash_balance` at all, so if a
transaction's date AND amount changed in the same edit, the amount delta's cash impact was
silently dropped. Fixed: the `date_changed` branch now computes
`cash_delta = tx.total_amount_eur - old_total_eur` and calls `_update_account_cash_balance`
when non-zero, exactly like the non-date-move branch below it does.

## Bulk transaction import (Excel)

`POST/GET /api/transactions/import/{template,validate,commit}`
(`backend/app/api/routers/transaction_import.py`,
`backend/app/services/import_service.py`) — a recurring-use import for reloading a broker
statement without re-keying every row in the UI. This is a deliberate, narrow exception to
"all data entry goes through the UI": the import **always** funnels through
`create_transaction_core` (see below), never a parallel write path, so every existing
sign/fee/balance rule and its 72+ tests apply unchanged.

**Frontend entry points**: `TransactionImportPage.tsx`, routed at
`/portfolio/:portfolioId/import`, reachable via the "Importer" sidebar nav item (between
Transactions and Performance) **and** a shortcut button directly on each portfolio's card on
`PortfolioSelectPage.tsx` (next to Ouvrir/Renommer/Supprimer) — added since new users landing
on the portfolio-selection screen otherwise had no visible path to bulk import without first
opening a portfolio and finding the nav item.

**`create_transaction_core` extraction.** `create_transaction` (the `POST /api/transactions/`
route) used to `await db.commit()` at the end of its own body. Importing N rows by calling
that route function N times would commit each row individually, making an all-or-nothing
rollback impossible once row N+1 fails. Everything up to (not including) commit/refresh/
snapshot-trigger was extracted into `create_transaction_core(body, db) -> Transaction`; the
route is now a 3-line wrapper around it. The import commit endpoint calls this core function
once per row inside a single DB transaction, and only commits/triggers-snapshot once at the
end if every row succeeded.

**`_trigger_snapshot_recompute(portfolio_id, from_date)` ignores its `portfolio_id`
parameter** — it only calls `compute_daily_snapshots_all_users.delay(from_date.isoformat())`,
which recomputes every portfolio from that date forward regardless of which one is passed.
The import commit endpoint exploits this: it calls this once after the batch commit, with
`from_date = min(date across all imported rows)`, regardless of how many portfolios/accounts
the batch touched — no need to trigger once per portfolio.

**The "Sens" column is the whole design** — the Excel template never asks the user to type a
signed quantity or pick an internal `type`/`operation`; a single human-friendly "Sens" column
drives all three, per `SENS_RULES` in `import_service.py`:

| Sens | `type` | `operation` | Ticker requis | Quantité | Prix unitaire | Courtage | TTF |
|---|---|---|---|---|---|---|---|
| Achat | Actif | Achat | ETF/SICAV-FCP/Action/Obligation | signe `-` | tel quel | ✓ | ✓ (achat seul) |
| Vente | Actif | Vente | idem | signe `+` | tel quel | ✓ | ✗ |
| Achat/Vente Or physique | Actif | Achat/Vente | Or physique | forcé `∓1` | **valeur totale**, pas un prix unitaire | ✓ | achat seul |
| Attribution | Actif | Attribution | idem Achat | signe `-` | optionnel (0 par défaut) | ✗ (rejet si >0) | ✗ |
| Dépôt/Retrait | Actif | `None` | Cash (`LIQUIDITE.*`, `*EUR=X`) | signe `+`/`-` | forcé `1.0` | Retrait seul (frais de retrait broker réel) | ✗ |
| Revenu | Revenu | `None` | idem Achat | signe `+` | tel quel | ✗ | ✗ |
| Frais | Frais | `None` | `category='Frais'` | forcé `-1` | montant du frais | n/a | n/a |

Confirmed against real code/tests before writing this table (not assumed): Attribution's
`quantity` sign matches Achat's (`test_transactions.py:884-926`, `quantity=-3.0`); Revenu's
`quantity`/`unit_price` are positive (`test_transactions.py:1153-1160`,
`test_pv_service.py:255-264`); Or physique's `quantity` is always `±1` with `unit_price`
holding the total transaction value, never a per-unit price (`test_accounts_router.py:
209-217`, `holdings.py:122`'s `value_eur = price if instrument_type == "Or physique" else
qty * price`). Retrait allows a non-zero Courtage (a real broker withdrawal fee, already
supported by the manual UI via `TransactionsPage.tsx`'s `withdrawalFee` — excluding it from
import would silently drop real relevé data) while every other non-Achat/Vente Sens forces
Courtage/TTF to 0.

**Forex-ticker Devise special case**: for a ticker matching `^[A-Z]{3}[A-Z]{3}=X$` (e.g.
`JPYEUR=X`), the expected Devise is the ticker's own 3-letter prefix (`JPY`), never
`Product.currency` (stored as `EUR`, the reference currency, for these tickers) — a naive
"Devise must equal Product.currency" rule would reject every legitimate Dépôt/Retrait row on
a forex position.

**Duplicate detection key** (both in-DB and in-file):
`(portfolio_id, account_id, date, ticker, operation, quantity, unit_price, currency)`
with a `0.005` float tolerance, deliberately excluding `courtage_eur`/`ttf_eur`/
`exchange_rate` — the question is "does this exact trade already exist", not "with identical
fees", so re-importing the same trade with a corrected fee still flags as a duplicate for the
user to review rather than silently creating a second transaction.

**Validate/commit are two independent HTTP calls, not a stateful session.** `/validate`
parses+checks the uploaded file and returns a full per-row preview (`status: "ok"|"error"|
"duplicate"`) without ever writing to the DB. `/commit` takes the **same file re-uploaded**
(never trusts client-echoed resolved data) plus an explicit `include_rows` array of row
numbers to actually import — this is also how a flagged duplicate gets force-included:
put its row number in `include_rows`. Commit re-validates from scratch against the fresh
upload; if any included row comes back `"error"` on this second pass (e.g. a broker was
deleted between the two calls), the whole commit is rejected before a single row is
inserted. If a row fails mid-loop for any other reason, the whole batch is rolled back —
verified with a test that mocks `create_transaction_core` to fail on the second of two rows
and asserts zero transactions exist afterward.

**Rows are always reordered chronologically before commit** (`(portfolio_id, account_id,
date, original_row_number)`) — the file is never required to be pre-sorted, and an unsorted
file is never rejected. This matters because `create_transaction_core`'s running-balance
chain (`balance_eur`) is computed incrementally from the previous row's balance at insertion
time; inserting out of date order would corrupt that chain.

**The downloadable template is generated from live DB data, not fake placeholders** — this
is a personal, local single-user app, so the file never leaves the machine. Example rows are
built by querying real portfolios/brokers/products (`_build_example_rows` in
`import_service.py`), one row per Sens value that has a matching product available; a Sens
with no matching product in the current DB (e.g. a fresh install with no Or physique
holding) is simply skipped, never a crash. The single highest-value test for this feature
(`test_template_example_rows_pass_self_consistency_validation`) generates the template and
immediately re-submits its own example rows through `/validate`, asserting every one comes
back `status="ok"` — a structural guard against the template ever drifting out of sync with
the validation rules in `resolve_row`.

**Bugs found only by live QA testing against real cloned data, not by the unit test suite**
(each fixed, each now has a regression test):
- A non-`.xlsx` upload (wrong file, corrupted file) raises `zipfile.BadZipFile`/
  `openpyxl.utils.exceptions.InvalidFileException` — neither is a `ValueError` subclass, so a
  bare `except ValueError` around the parse call let it escape as a raw 500.
  `parse_uploaded_workbook` now catches these explicitly and re-raises `ValueError` with a
  clean message.
- A blank Portefeuille/Compte/Devise cell reads as Python `None`; interpolating it directly
  into an error message produced the literal text `Portefeuille 'None' introuvable`. Fixed
  with a `_display()` helper rendering `(vide)` instead.
- Text cells (Portefeuille, Compte, Ticker, Devise, Sens, **and the header row itself**) were
  never `.strip()`'d — a trailing space from copy-pasting a broker statement into Excel
  (`"Portfolio 1 "`) or from manually retyping a column header (`"Portefeuille "`) silently failed
  the exact-match dict lookup, rejecting a row that referenced a perfectly real entity. Fixed
  with a `_clean_str()` helper applied to every text field read from a row **and** to the
  header row read in `parse_uploaded_workbook`.
- The "Télécharger le modèle" download could be saved under a random UUID filename instead of
  `modele_import_transactions.xlsx` — some WebKit-based browsers (Epiphany, this app's
  fallback native-window mode on Linux, see "Native window integration" below) ignore
  `Content-Disposition` for a download triggered via a synthetic `<a download>` click. Fixed
  by putting the filename in the URL path itself (`GET /template/{filename}`, the segment is
  otherwise unused) — the one download-naming signal virtually every browser/webview respects.

Deliberately-injected garbage (SQL-injection-style strings in Sens/Portefeuille, 300-character
tickers, emoji/unicode portfolio names, unevaluated Excel formula cells, rows with fewer cells
than the header, quantities of 1,000,000+) all degrade to a clean per-row validation error with
zero crashes — confirmed live, not just by reasoning about the code. No new handling was needed
for these; they're listed here as evidence the existing validation/error-accumulation design
already covers them, in case a future change is tempted to add defensive code that isn't needed.

## Rebalancing — "après %" denominator depends on simulation mode

`RebalancingPage.tsx` has 3 simulation modes: `contribution` (injection only), `hybrid`
(injection + sells if needed), `hard` (Rééquilibrage complet — sells overweight pools and
reinvests into underweight ones, **no external injection**). The displayed post-trade
percentage for a pool (`afterPct = afterValue / afterTotal * 100`) must use a
**mode-dependent denominator**:
- `contribution`/`hybrid`: `rebalData.total_after` (current + available liquidity + external
  injection) — correct, since these modes actually grow the portfolio total.
- `hard`: `total_current` — the backend's `rebalance_amount` for this mode is computed
  against `total_current` alone (no injection), so dividing by `total_after` instead (which
  still includes any leftover uninvested cash) inflates the denominator and makes every pool
  appear to land below its target even when the underlying trade amounts are correct (e.g.
  displaying 24.2% instead of 25.0% with a spurious "-0.8%" gap, for trades that were
  actually exactly on target).

Guard `afterTotal > 0 ? afterValue / afterTotal * 100 : 0` — a zero denominator (empty
portfolio with a pending injection) must fall back to 0%, not NaN/Infinity.

## Daily snapshot logic

- Auto-generated at **app startup** (via Celery task `fill_missing_snapshots`)
- Triggered at **midnight** when the app is open (frontend detection, `useAutoRefresh`)
- Excludes **weekends** (filter `EXTRACT(DOW) NOT IN (0, 6)`)
- Based on prices from `asset_prices` (yfinance + manual)
- The **Admin** page allows forced regeneration over a custom date range

## Yahoo Finance price sync

- Every 15 min via Celery Beat (`refresh_prices_live`), plus once at **backend startup**
  (`main.py` lifespan calls `refresh_prices_live.delay()` alongside `fill_missing_snapshots.delay()`,
  in its own independent try/except so one failing doesn't block the other)
- Source: `query1.finance.yahoo.com/v8/finance/chart/{ticker}` — returns `regularMarketPrice`
- **Glitch guard**: if the new price deviates by more than ×10 from the previous day, it is rejected
  and the ticker is added to `failed_tickers`. Protects against Yahoo scale errors (e.g. JPYEUR=X
  returned as 0.5418 instead of 0.005418). Implemented in `app/tasks/prices.py`.
- `Manuel` and `Fee` categories excluded from refresh

### Frontend auto-refresh — dual mechanism

`useAutoRefresh` (`frontend/src/hooks/useAutoRefresh.ts`) invalidates `REFRESH_KEYS`
(dashboard/positions queries) through two independent triggers:
- A blind 15-minute `setInterval` — a fallback safety net.
- A precise `useEffect` watching `useSyncStatus().data?.finished_at`: invalidates as soon as
  that timestamp changes (skips the very first observed value on mount, to avoid an
  unnecessary refresh right after the page loads).

This makes Dashboard/Rebalancing refresh right when a price sync actually completes, instead
of waiting for the next blind interval tick.

## ETF look-through holdings — sector/company allocation

Two new tables — `etf_holdings` (top-10 underlying holdings) and `etf_sector_weightings`
(sector breakdown) — keyed by `parent_ticker`. A directly held stock (`instrument_type='Action'`)
gets a **synthetic self-row** in both (`holding_ticker=parent_ticker`, `weight_pct=1.0`), so
`compute_pool_lookthrough()` in `app/services/etf_holdings_service.py` never special-cases
"ETF vs direct stock" — every position in a pool feeds the same `by_company`/`by_sector`
accumulators keyed by underlying ticker/sector, which is what merges a stock held directly
with the same stock found inside one or more ETFs in the pool (e.g. TotalEnergies held
directly as `TTE.PA` and inside `STN.PA` at 18.63% — confirmed on real portfolio data).

**Data source**: Yahoo Finance's unofficial `quoteSummary` endpoint (`query2.finance.yahoo.com`,
module `topHoldings` for funds, `assetProfile` for a direct stock's `sectorKey`) — a
**different, more fragile mechanism** than the price-sync `chart` endpoint above. It requires
a session cookie + CSRF "crumb" token (`app/tasks/etf_holdings.py`, `_get_yahoo_session_crumb`)
fetched fresh each run; if that fails, the whole task aborts cleanly (old data stays in place,
`products.holdings_updated_at` just doesn't advance).

**Crumb endpoint gotcha, confirmed empirically**: `query2.finance.yahoo.com/v1/test/getcrumb`
returns `406 Not Acceptable` when the request sends `Accept: application/json` — it's the
`Accept` header specifically, not the `User-Agent` (isolated both independently; swapping only
the `Accept` header to `*/*` flips 406→200, a real crumb, and a working `quoteSummary` fetch).
`YAHOO_HEADERS`'s `Accept` is `*/*` for exactly this reason — `quoteSummary` itself returns
JSON regardless of the `Accept` header sent, so this is safe for every request the module
makes. This had silently never worked in production since the feature was introduced
(`products.holdings_updated_at` was `NULL` for all 21 eligible products) until this fix.

Only the top 10 holdings are ever
available (never full composition — coverage varies 19-97% of fund assets depending on the
ETF), so `by_company` always carries an explicit `"__OTHER__"` bucket for the untracked
remainder rather than implying completeness. `products.bond_duration`/`bond_maturity` are also
captured for bond funds — present in Yahoo's API but never shown on Yahoo's own site.

Runs weekly (`crontab(hour=6, minute=0, day_of_week="0")`) plus once at backend startup,
mirroring the price-sync task's structure.

**Frontend**: `TickerLink` (`frontend/src/components/TickerLink.tsx`) renders a ticker as
clickable only for `instrument_type` ETF/SICAV-FCP/Action (never Cash/Or physique/Obligation/
Frais — no composition data exists for those), opening `EtfCompositionModal`. Both are shared
components wired into every page that displays a ticker (Comptes, Produits et frais, Positions,
Transactions, Performance, Dashboard) — a single reusable pair rather than one-off modals per
page. `PoolAllocationSection` (on the Positions page, per pool) shows the merged sector/company
breakdown via `GET /api/pools/{pool_id}/allocation`.

## Macro indicators — growth/inflation ratio page (portfolio-independent)

New global page `/indicators` (outside `/portfolio/:id/*`, uses `GlobalLayout` like `/config`)
showing two "base 100" ratio charts with a rolling moving average, for a selectable **region**:
**growth** (region equity index / WTI oil `CL=F`, oil shared across regions) and **inflation**
(region government bond ETF / gold `GC=F`, gold shared across regions). Ratio below its own
moving average = recession / inflationary regime, per the user's macro reading — this is a
display convention, not something the backend interprets. Each chart's legend spells out the
real "X / Y (base 100)" ratio using **human-readable descriptive names** (e.g. "CAC 40 /
Pétrole (WTI)"), never the raw Yahoo ticker (e.g. "^FCHI / CL=F" means nothing to a
non-technical reader) — see `equity_label`/`bond_label` below. Falls back to the raw ticker
only if a label is ever empty (defensive, shouldn't happen since the fields are required in
the UI). Also shows a one-line interpretation of what "above"/"below" means for that pair
(gold vs. bonds, equities vs. energy) — sourced from i18n, not hardcoded per region.

**Inflation deliberately uses bond ETF *prices*, never a yield**, uniformly across all
regions — a yield and a bond price move inversely, so mixing a yield-based region with
price-based ones would flip the "ratio below MA" reading's direction between regions.

**Regions are a user-managed CRUD list, not a hardcoded set.** `MacroRegion` model
(`code` PK, `label`, `equity_ticker`, `bond_ticker`, `equity_label`, `bond_label`) is managed
entirely from **Configuration générale** (`GlobalConfigPage.tsx`'s `RegionManager`, mirroring
`ProductManager`'s table + modal + `ConfirmModal`-delete shape) — the user adds/edits/removes
regions themselves, no code change needed. `code` is immutable once created (it doubles as the
`macro_series_prices` series-key prefix: `f"{code}_equity"`/`f"{code}_bond"` — renaming it
would orphan history). `equity_label`/`bond_label` (e.g. "CAC 40", "Obligations zone euro
10-15 ans") are required fields in the add/edit form — the whole point of the feature is a
human-readable legend, so leaving them optional would silently regress to raw tickers for any
region the user forgets to fill in. Deleting the last remaining region is rejected (the page
must always have at least one). Seeded regions (migration `pp99qq00rr11`, labels backfilled by
`qq00rr11ss22`):

| Region | Growth (equity) | Inflation (bond ETF) |
|---|---|---|
| US | `^SPXEW` "S&P 500 Equal Weight" | `GOVT` "Obligations Trésor américain" (iShares U.S. Treasury Bond ETF) |
| France | `^FCHI` "CAC 40" (see data-gap gotcha below) | `MTE.PA` "Obligations zone euro 10-15 ans" (Amundi Euro Government Bond 10-15Y — **Eurozone, not pure France OAT**) |
| Monde | `MWEQ.L` "Actions Monde (Equal Weight)" (Invesco MSCI World Equal Weight UCITS ETF) | `BNDW` "Obligations Monde" (Vanguard Total World Bond ETF) |

The shared oil/gold tickers get the same treatment: `macro.ticker.oil.label`/
`macro.ticker.gold.label` SystemSetting keys (default "Pétrole (WTI)"/"Or"), surfaced as two
more `SettingField`s next to the existing ticker fields in the same "Indicateurs macro" card —
`get_macro_settings(db)` returns them as `oil_label`/`gold_label` alongside the existing
`oil`/`gold` ticker keys.

**Two Yahoo tickers were confirmed dead via real QA testing, not caught by mocked unit
tests** — always empirically curl-verify a ticker's chart history depth before adopting it:
- The raw MSCI World Equal Weighted index code `^129857-USD-STRD` returns a live quote on
  Yahoo but **zero historical chart data** (confirmed via explicit `period1`/`period2` even
  over a 10-year window — only 1 point, today, ever comes back). Replaced by `MWEQ.L`, the
  equal-weight ETF tracking the same index (real daily history, ~470 points since Sept 2024).
- `^SBF120` (originally used for France) has **zero chart history from 2016 onward**
  (confirmed via narrow 2016-2018 and 2020-2021 windows, both 0 points) — visible on the
  frontend as the growth ratio line flattening to a constant value once the underlying series
  stops updating. Replaced by `^FCHI` (CAC 40), verified to have a continuous 26-year daily
  history with no gaps.

Single generic table `macro_series_prices` (`series`, `date`, `value`, unique on
`(series, date)`), decoupled from `products`/portfolios and from the region list itself —
`compute_ratio_indicator(db, numerator_series, denominator_series, ma_years)` only ever sees
plain series-key strings, with no notion of "region" at all. This is why generalizing from a
single hardcoded region to 3, then to a fully dynamic N-region CRUD system required **zero**
changes to this function — validating the payoff of keeping it series-key-based from the start.
The moving average is a time-based (not point-count) O(n) sliding window, since fixed-N-point
windows are imprecise once holidays/gaps exist in the series.

Oil/gold tickers + the moving-average duration (default 7 years, **one setting shared by every
region's charts**, not per-graph) are configurable via the generic `SystemSetting` key/value
store (`macro.ticker.oil`, `macro.ticker.gold`, `macro.ma_years`) — surfaced as `SettingField`
inputs (shared component, `frontend/src/components/SettingField.tsx`) under **Configuration
générale**'s "Indicateurs macro" card, alongside the region table. Nothing is hardcoded: adding
a region or changing a ticker/MA-duration never requires a code change.

`GET /api/indicators/growth|inflation` take a `region` query param, 404 on an unknown region
code (a real missing resource, not a fixed-enum check) — response includes both the resolved
`numerator_ticker`/`denominator_ticker` (raw tickers, kept for reference) and
`numerator_label`/`denominator_label` (the descriptive names the frontend actually renders in
the legend) so the frontend never needs to duplicate region/settings data to build either.
`GET/POST/PUT/DELETE /api/indicators/regions` mirror `products.py`'s CRUD shape.

**Critical data-source gotcha**: `app/tasks/macro_indicators.py` fetches full history every run
using **explicit `period1`/`period2` Unix-timestamp params**, never `range=max`. Confirmed
empirically: `range=max&interval=1d` gets silently downsampled by Yahoo to ~monthly granularity
for long spans (only ~168 points over 42 years for `^GSPC`), while explicit `period1`/`period2`
returns true uncapped daily data (6500+ points over 26 years). Re-fetching full history each run
(not just "today") is cheap and self-heals gaps/revisions, mirroring the ETF holdings task's
replace-on-fetch approach. Runs daily (`crontab(hour=7, minute=0)`) plus once at backend startup.
The task builds its fetch list from `list_regions(db)` at runtime plus oil/gold — it scales to
however many regions exist, no hardcoded ticker count anywhere.

Manual trigger (`POST /api/indicators/refresh`) + status polling
(`GET /api/indicators/sync-status`, Redis key `pie:macro:status`) mirror the ETF holdings task's
pattern rather than price-sync's fixed-4s-guess, since a full refetch's duration isn't a safe
constant to assume. There is no manual "Actualiser maintenant" button on the page itself
(removed — daily auto-sync makes a manual trigger low-value); the endpoint remains for ops/curl
use, and the page still shows "Dernière synchro" and auto-invalidates its queries when a sync
completes.

**Chart zoom** (`RatioIndicatorChart.tsx`) mirrors `IndexChart.tsx`'s characteristics
end-to-end: drag-to-select via raw mouse events with `e.preventDefault()` on mousedown, a
translucent brush overlay, a `MIN_ZOOM_MS` floor, a shared `ChartCrosshair` hover tooltip
(colored bullet + short series name + value, date header — see `frontend/src/components/
ChartCrosshair.tsx`, also used by `IndexChart.tsx`), and **both** a preset-period button row
(1M/3M/1Y/YTD/5Y/10Y/MAX, same set as `PerformancePage.tsx`'s time scale selector) **and** a
separate "↺ Réinitialiser zoom" button shown only while a manual drag is active (no preset
highlighted) — see the "Custom drag-to-zoom chart checklist" below for why these two controls
are not interchangeable. It deliberately has no `containerComponent`/`VictoryZoomContainer` at
all: the custom mouse handlers on the wrapping `<div>` do all the work (brush AND crosshair),
so Victory's own container is unnecessary. Clicking a preset anchors the range on the
**dataset's latest point** (`data.dates[last]`), not `new Date()`, since this data only updates
via the nightly Celery sync. A manual drag clears the active-preset highlight (it rarely lands
exactly on a preset boundary). See the "Custom drag-to-zoom chart checklist" below — every
item in it was found and fixed while responding to live user bug reports against this exact
chart, in the order: wrong zoom range → native text-selection during drag → duplicate axis
year labels → missing reset button → verbose Victory-default hover tooltip.

## Health check endpoint

- `GET /api/admin/health` — returns `{"status": "healthy"}` (200) or 503 if DB unreachable
- Used by HAProxy active health check (`option httpchk`, `http-check send meth GET uri /api/admin/health`)
- HAProxy probes every 2s (`inter 2s rise 2 fall 3`) independently of incoming requests
- HAProxy config: `parse-resolv-conf` reads DNS from `/etc/resolv.conf` (portable across Docker/Podman)
  + `resolve-prefer ipv4` prevents dual-stack IPv6 issue in rootless Podman
  + `init-addr libc,none` allows HAProxy to start before backend is up

## Frontend startup resilience

`usePortfolios()` is configured with `retry: 30, retryDelay: 2000` — shows spinner for up
to 60s while backend warms up after container restart. Without this, the portfolio selection
page shows "Erreur lors du chargement" if the backend is still starting when the user opens
the app.

## Distribution

### Architecture: static Go installer

A single statically compiled binary (`CGO_ENABLED=0`), with no prerequisites.

```bash
# Install
curl -LO https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-linux-amd64
chmod +x pie-manager-linux-amd64
./pie-manager-linux-amd64        # install (default subcommand)

# Launch (after install)
pie-manager start                 # or GNOME icon
```

| Subcommand | Role |
|---|---|
| `install` (default) | Pull quay.io images, write config files, create `.desktop`, start services |
| `start` | Read `.env` for port, start containers, open WebKitGTK window or browser |
| `version` | Print the installed version |

### Container images
- Published on **Quay.io** (`quay.io/ltourreau/pie-manager-*`) — **public**, no token required
- Images are version-tagged: `quay.io/ltourreau/pie-manager-backend:1.0.0` (pinned in `.env` via `APP_VERSION`)
- Build + push automated via `publish-images.yml` on tag `vX.X.X`

### Windows executable code signing

`build-installer.yml` Authenticode-signs `launcher.exe` and `pie-manager-windows-amd64*.exe`
using a self-signed `CN=PIEManager` certificate (`osslsigncode`, since the whole workflow runs
on `ubuntu-latest` with no Windows runner — the Windows binaries are cross-compiled, not built
natively). Signing includes an RFC-3161 timestamp (`timestamp.digicert.com`), so the signature
stays valid after the certificate expires (2031). The PFX and its password live only as the
GitHub secrets `WINDOWS_CODESIGN_PFX_BASE64`/`WINDOWS_CODESIGN_PFX_PASSWORD` — a personal
backup of the PFX exists outside the repo/VM, not tracked here.

**This does not remove the Windows SmartScreen "Unknown Publisher" warning** — only a
CA-issued certificate with accumulated reputation does that. It provides a valid, verifiable,
non-expiring signature (integrity/authenticity), nothing more.

**The UAC prompt and the Firewall "allow this app" prompt read the publisher from two
different, unrelated places.** UAC shows "Éditeur vérifié: PIEManager" because it validates
the Authenticode signature. The Firewall prompt shows "Éditeur: Inconnu" regardless of
signing, because it reads the `CompanyName`/`ProductName` fields from the binary's embedded
VERSIONINFO resource, separate from the manifest/icon. Fixed: `installer/winres/winres.json`
(go-winres, same tool/format as `installer/launcher/winres/winres.json`) regenerates
`installer/main_windows_amd64.syso` with those fields populated — regenerate via
`go run github.com/tc-hib/go-winres@latest make --in winres/winres.json --out main --arch amd64`
(the tool's default output naming, `main_windows_amd64.syso`, is exactly the file Go's build
expects — keep it, don't rename it to a bare `main.syso`). Avoid non-ASCII characters (em dash,
`—`) in any winres.json text field — one silently killed RT_VERSION generation entirely
(RT_MANIFEST still worked) with no error from the tool, confirmed by regenerating without it.

**Correction (2026-07):** the file was previously renamed to a bare `main.syso` in the mistaken
belief that Go wouldn't pick up the properly `_windows_amd64`-suffixed name — that belief was
never actually re-verified and turned out to be wrong. A bare, unsuffixed `.syso` has no
OS/ARCH scoping at all, so Go links it into **every** build target unconditionally, not just
Windows; this only surfaced as a real problem once a `darwin/arm64` build target was added
(`GOOS=darwin GOARCH=arm64 go build` failed with `unknown ARM64 relocation type 3`, since the
file is a Windows PE-COFF object). Verified empirically (byte-diffed the two resulting Windows
binaries, identical except Go's own build-ID cache string) that renaming back to
`main_windows_amd64.syso` produces the exact same signed Windows binary while fixing every
other platform. Never go back to a bare `main.syso`.

### Installed files (Linux)
```
~/.local/share/pie-manager/   compose-prod.yaml, haproxy.cfg, .env, pie-manager (binary), VERSION
~/.local/share/pie-manager/   wrapper.py (only if WebKitGTK is available)
~/.local/share/applications/  pie-manager.desktop
~/.local/share/icons/hicolor/ pie-manager.svg + .png
~/.local/bin/                 pie-manager (symlink)
```

### Installed files (Windows)
```
%APPDATA%\pie-manager\   compose-prod.yaml, haproxy.cfg, .env, VERSION
%APPDATA%\pie-manager\   launcher.exe, start-podman.vbs
Start Menu\Programs\     PIE Manager.lnk  (→ launcher.exe)
```

### Installed files (macOS)
```
~/Library/Application Support/PieManager/   compose-prod.yaml, haproxy.cfg, .env, pie-manager (binary), VERSION
~/Library/LaunchAgents/                     com.pie-manager.podman-start.plist
~/Applications/                             PIE Manager.app  (Contents/MacOS/pie-manager-launcher)
~/.local/bin/                               pie-manager (symlink)
```

### Windows installation architecture

On Windows, PIE Manager requires WSL2 + Podman Machine (a WSL2-backed Fedora CoreOS VM)
+ Docker Compose (installed via winget). The installer (`pie-manager-windows-amd64.exe`) is a
single statically compiled Go binary that handles the full setup.

**Compose provider:** `docker-compose.exe` (installed on the Windows host via winget). HAProxy
and all containers communicate over Podman's internal Docker-compatible network.

**Launcher:** `launcher.exe` is a native Go binary using WebView2 (pre-installed on Windows 11).
It replaces the old `launcher.ps1`/`open-app.vbs`/Edge `--app` chain. It:
- Shows the PIE Manager icon in the Windows taskbar (AUMI belongs to our .exe)
- Detects if a window is already open (single-instance via FindWindowW)
- Shows a native loading screen while polling `/api/admin/version`
- Navigates to the app in a WebView2 window once the backend is ready

**Window title bar icon** requires an explicit `IconId` — `jchv/go-webview2`'s `webview2.New()`
falls back to the generic Win32 stock icon (`IDI_APPLICATION`) whenever `WindowOptions.IconId`
is left at zero; it does not automatically pick up the exe's own embedded icon resource, even
though one is present via `winres/winres.json`. Fix: key the icon group by numeric ID in
`winres.json` (`"RT_GROUP_ICON": {"#1": {...}}`, not a string name like `"APP"` — the API only
accepts a numeric resource ID), then construct with
`webview2.NewWithOptions(webview2.WebViewOptions{WindowOptions: webview2.WindowOptions{IconId: 1}})`
instead of `webview2.New(false)`.

**Auto-start:** A Windows Task Scheduler task runs `start-podman.vbs` at login (wscript.exe,
completely invisible). This starts the Podman Machine. Containers restart automatically via
`podman-restart.service` inside the Fedora CoreOS VM.

**VmmemWSL memory:** ~3-4 GB is normal — the Podman Machine VM + all containers.

**Windows install sequence (fresh machine):**
1. Run `.exe` as Administrator → installs WSL2, Podman CLI, Docker Compose (may reboot)
2. After reboot, installer auto-resumes via RunOnce registry key
3. `podman machine init` + start (~650 MB download)
4. All 6 containers pulled and started via `podman compose up -d`
5. `launcher.exe` deployed, Start Menu shortcut created, Task Scheduler registered

The `.env` file written by the installer contains:
```
APP_VERSION=<version>
INSTALLER_VERSION=<version>
APP_PORT=<port>
```

### Windows gotchas (do not repeat these mistakes)

**Store-independent WSL2/winget install** — `wsl --install --no-distribution` fetches the
actual WSL2 engine as a Microsoft Store app, and `winget` itself is normally provisioned
through the Store too; both are silently absent on a fresh **local-account** Windows install
(Store provisioning never triggers without a Microsoft-account first login) — confirmed live
in a test VM. `main_windows.go` now enables the two required optional features directly via
DISM (`enableWindowsFeature`, bypassing `wsl --install`'s own flaky attempt at this), and
falls back to downloading the official `.msixbundle` packages straight from
[microsoft/WSL](https://github.com/microsoft/WSL/releases) and
[microsoft/winget-cli](https://github.com/microsoft/winget-cli/releases) releases
(`installWSLFromGitHub`/`installWingetFromGitHub`) when the Store-dependent path fails —
Microsoft's own documented offline/enterprise install method, not a hack.

**WSL2 readiness must check the actual engine, not just DISM feature flags.** `isWSL2Ready()`
used to check only whether `Microsoft-Windows-Subsystem-Linux`/`VirtualMachinePlatform`
report `State=Enabled`. Confirmed live: both can report `Enabled` (with `RestartNeeded=False`,
so not a pending-reboot issue either) while the WSL kernel/engine was never installed — e.g.
the features were toggled independently, or an earlier run enabled them via DISM but was
interrupted before `wsl --install` finished. The installer then logged "WSL2 déjà installé"
and skipped straight to Podman machine init, which failed with a confusing "WSL isn't
installed" error. Fixed: `isWSL2Ready()` now runs `wsl --status` directly — it exercises the
real engine and requires both features anyway, so it's a single, reliable signal instead of
two flags that can drift from actual system state.

**Cosmetic: `wsl.exe`'s own console chatter and the WSL Settings "welcome" popup are both
suppressed, not just tolerated.** `wsl --install`'s stdout/stderr is now captured
(`CombinedOutput()`), not streamed to the console — it prints confusing internal diagnostics
(e.g. "not installed, run wsl --install" as part of its own self-check) that read as a real
error; the raw text is still logged, replaced on screen with our own curated status lines.
Separately, the WSL Settings onboarding window (`wslsettings.exe`, launched by `wslservice.exe`
via `----ms-protocol:wsl-settings://oobe`) used to pop up mid-install — confirmed via
microsoft/WSL's own source (`LxssUserSession.cpp`'s `_LaunchOOBEIfNeeded`) that it fires the
first time ANY WSL distro is registered on the machine, including Podman Machine's own
`podman-machine-default` distro — nothing specific to our WSL2 install step. Its entire gate is
one registry DWORD, `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss\OOBEComplete` — the
exact value `wslservice.exe` itself writes after a real OOBE run. `disableWSLOOBEWelcome()` sets
it preemptively, early in `main()`, doing ahead of time what the OS does reactively.

`Add-AppxPackage` itself is confirmed live (real elevated non-SYSTEM user, test VM) to work
correctly for VCLibs/UI.Xaml/winget. The one real failure mode hit live is HRESULT
`0x80073D06` ("a higher version of this package is already installed") — some Windows 11
builds ship a newer in-box framework package than the version this installer pins, and AppX
dependency resolution only requires "at least this version," so it's harmless. `addAppxPackage`
treats this specific HRESULT as success (`isAppxAlreadyNewerError` in `common.go`).

**HAProxy port 80 forbidden in rootless Podman** — HAProxy must listen on port 8080 internally,
mapped to `APP_PORT:8080` in compose. Port 80 causes `Permission denied` at startup.

**`podman-restart.service` enable via SSH** — `systemctl --user enable` fails silently when
`~/.config/systemd/user/default.target.wants/` is owned by root (Podman Machine default).
Fix: create the symlink directly after fixing ownership, chaining the steps with `&&`.

**`podman machine ssh` mangles a compound `&&`-chained command passed as `"bash", "-c",
cmd`** — confirmed live and matches an independent upstream report
([containers/podman#13517](https://github.com/containers/podman/issues/13517)): it re-joins
multiple trailing arguments before forwarding them over SSH, so `bash`, `-c`, and the command
string arrive at the remote shell re-split on whitespace — only the first word after `-c`
survives as its actual script argument (observed live as a bare `sudo` invocation dumping its
usage text, silently no-op'ing the whole setup step). Fix: pass the full compound command as
the **sole** trailing argument after `--`, no separate `"bash", "-c"` — the remote SSH server
already wraps a single command string in a shell itself.

**Podman machine start at login** — the Task Scheduler VBS uses `True` (wait) + retry loop
(up to 5 attempts, 5s between) because WSL2 may not be ready immediately at login.

**Auto-resume after reboot uses a single Scheduled Task, not RunOnce — do not add RunOnce
back.** An earlier version registered both a `HKCU\...\RunOnce` entry AND a Scheduled Task
(`RunLevel Highest`, `-AtLogOn -User $env:USERNAME`) as redundant auto-resume mechanisms,
since RunOnce alone was intermittent on at least one test VM: a failed-to-fire RunOnce entry
survives completely **unconsumed** in the registry (Windows always deletes a RunOnce value
immediately before running it, success or failure, so a surviving value means it was never
attempted that boot at all — a documented class of quirk with RunOnce pointing at a
`requireAdministrator`-manifested executable). The Scheduled Task backup was added to cover
that flakiness. **This redundancy was then confirmed live to actively cause the worse bug it
was meant to guard against**: both mechanisms fired for the same logon, and — critically —
each one triggers its own elevation event *before* any of our code (including a
`CreateMutexW`-based single-instance lock, `acquireSingleInstanceLock` in
`main_windows.go`) ever runs, since Windows decides whether to elevate before the process
image executes. Confirmed live as one silent auto-elevation plus one visible UAC consent
dialog for the same logon — a mutex can only stop the *second* instance from doing duplicate
work once both have already elevated, it cannot suppress the extra prompt itself. The only
fix that actually prevents the double elevation event is registering a single mechanism.
RunOnce was dropped; the Scheduled Task was kept, since it is Microsoft's documented
mechanism for reliably resuming an elevated process at logon and doesn't share RunOnce's
silent-no-fire quirk. The single-instance mutex is kept anyway as a general defensive guard
(e.g. a manual double-launch of the resumed installer), just no longer covering this specific
race. Since the installer's own SKIP-logic makes every step idempotent regardless, a manual
re-launch of the `.exe` after reboot remains a safe fallback if the Scheduled Task ever fails
to fire.

**RESOLVED — the "intermittent" final popup was never failing to render, it was rendering
BEHIND the console window.** A `MessageBox.Show(msg, title, ...)` call with no owner window
has no z-order relationship to the installer's own console window — Windows is free to leave
it behind the (still-focused) console, silently, with no error. Confirmed live via screenshot:
the popup was present and fully functional, just hidden under the console the whole time.
Fixed by giving every popup an invisible, `TopMost`-set owner `Form` (`topmostOwnerPS` in
`main_windows.go`, prepended to both `popup()`'s and `popupYesNo()`'s script) — an owned
window is kept above its owner in z-order, and a `TopMost` owner keeps it above unrelated
windows too. Accessing `$owner` in `MessageBox.Show($owner, ...)` is what forces the form's
native handle into existence even though `.Show()` is never called on it — no visible extra
window appears.

**Final popup asks Yes/No to launch immediately, and both a Desktop and Start Menu shortcut
are created** — `popupYesNo()` (mirrors `popup()`, `MessageBoxButtons.YesNo` +
`MessageBoxIcon.Question`, matches on the literal `"Yes"` return string). Answering "Oui"
starts `launcher.exe` directly (fire-and-forget `exec.Command(...).Start()`, not `.Run()` —
it's a long-lived GUI process the installer must not wait on). The desktop shortcut resolves
its path via PowerShell's `[Environment]::GetFolderPath('Desktop')`, not a hardcoded
`%USERPROFILE%\Desktop`, since that breaks under Known Folder Move (OneDrive-redirected
Desktop). Before this, only a Start Menu shortcut was actually created despite the
surrounding log/comment text already claiming "desktop shortcut" — a real, silent gap now
fixed, not a rename.

**Image cleanup** — use targeted removal of old pie-manager versions only, never `podman image prune -af`
which would delete images from other projects on the machine.

**Fedora/RHEL short image names** — always use fully qualified names (`docker.io/library/postgres:16-alpine`)
to avoid "short-name resolution enforced" errors in non-interactive contexts.

### Native window integration (wrapper.py / WebKitGTK) — Linux only

At install time, `deployWrapper()` checks whether Python 3 + WebKitGTK 2 (`gi`, `WebKit2 4.1`)
are available. If yes, it writes `wrapper.py` to the install directory.

`openBrowser()` in `start.go` prefers `wrapper.py` (native WebKitGTK window, no browser chrome)
over Epiphany application mode, then falls back to the default browser via `xdg-open`.

`wrapper.py` behavior:
- Opens a GTK window sized 1400 × 900.
- If the backend already responds on first launch, navigates directly to the app.
- Otherwise shows an **animated loading screen** (dark background, progress bar) and polls
  `GET /api/admin/version` every 600 ms; navigates once the backend is ready.
- Intercepts navigation: external URLs are blocked, non-HTML responses trigger a file download
  (used for the database backup endpoint).

`focusExistingWindow()` in `start.go` prevents opening a second window when the user clicks
the GNOME icon while the app is already running. On Linux it tries `wmctrl`, then `xdotool`,
then falls back to checking whether `wrapper.py` is in the process list via `pgrep`.

The desktop entry (`Exec=<install-dir>/pie-manager start`) always invokes `pie-manager start`,
which handles the case where containers have stopped after a reboot.

## macOS installation architecture

**Apple Silicon (arm64) only — no Intel/amd64 build.** Apple Silicon is now the dominant Mac
architecture and the only one with a future: macOS 27 "Golden Gate" (Sept 2026) drops Intel
support entirely, and GitHub's own `macos-latest` Actions runner already defaults to arm64.
Building an amd64 binary too would cost nothing at compile time (Go cross-compiles both from
the same source) but there is no way to *test* it — see below — so it's simply not built.

**Target macOS version: 14 Sonoma minimum, 15 Sequoia recommended.** Podman's `applehv`
machine provider (default since Podman 5.x, the one this installer relies on) requires macOS
13 Ventura at minimum — but Ventura is already EOL (no security patches since Aug 2025), so
Sonoma (still patched) is the documented floor instead. No runtime OS-version check exists in
the installer itself; like Linux/Windows, it lets Podman fail with its own error on an
unsupported OS.

**No local test VM — testing happens exclusively on GitHub Actions' real Apple Silicon
runners (`macos-26`).** Unlike Windows (tested via a local libvirt/QEMU VM, see
`installer/testing/`), Apple Silicon macOS **cannot be virtualized on x86_64 hardware by any
known method** — KVM only accelerates matching host/guest architectures, and arm64 macOS is
hardware-locked to Apple Silicon SoC features (Secure Enclave, custom boot chain) with no
non-Apple equivalent. The OSX-KVM/Hackintosh community tooling only ever supports x86_64
macOS on x86_64 hosts, which is irrelevant now that amd64 is out of scope. `test-macos` in
`build-installer.yml` runs the release smoke test on genuine Apple Silicon hardware instead —
arguably better coverage than a VM would give anyway.

**No code signing or notarization — the binary is unsigned, exactly like the Windows
SmartScreen situation.** Real macOS code signing + notarization requires a paid Apple
Developer Program account ($99/year), which this project doesn't have. macOS Gatekeeper
blocks first launch of an unsigned/unnotarized binary ("cannot be opened" / "is damaged") —
the documented fix is `xattr -d com.apple.quarantine <binary>` (the GUI right-click bypass
does not apply to a plain CLI binary, and became unreliable on macOS Tahoe anyway). No
`osslsigncode`-equivalent tool exists for Apple's signing format, so unlike Windows there's
nothing to automate here — see README's "Sécurité et signature de code" for the user-facing
framing.

**Podman itself is auto-installed via its own official `.pkg`, not Homebrew.** Homebrew was
considered and rejected as the bootstrap mechanism: installing Homebrew itself requires Xcode
Command Line Tools, whose install pops up an interactive GUI dialog with no reliable silent
mode — unlike Windows's winget/DISM, which are fully scriptable. Instead,
`installPodmanFromGitHub()` in `install_darwin.go` reuses the exact same "official package
straight from GitHub, not a third-party package manager" pattern already used for WSL2/winget
on Windows (`githubLatestAssetURL`/`downloadFile` from `common.go`): downloads
`podman-installer-macos-arm64.pkg` from `containers/podman`'s latest release, then
`sudo installer -pkg ... -target /` (macOS's native package-install CLI, no GUI). Podman's own
docs recommend this `.pkg` over Homebrew anyway ("community-maintained, we cannot guarantee
stability"). `sudo`'s password prompt reads from the installer's own `Stdin`/`Stdout`/`Stderr`
(connected through, not discarded) since it's expected to run interactively from a Terminal —
exactly like Linux's `dnf install` message assumes a Terminal, just one step more automated.
Only handles a **fresh** install (`podman` absent from PATH) — re-running the `.pkg` to
*upgrade* an already-installed Podman is a documented fragile path upstream
(`podman-mac-helper` conflicts, requires manually uninstalling the old helper first), so
upgrades are left to the user/Homebrew, not this installer.

**Right after a fresh `.pkg` install, `podman` is still not on `PATH` for the current
process.** The `.pkg` registers its install directory via `/etc/paths.d/` for *future login
shells* only — confirmed live in CI: `podman machine init` failed with "executable file not
found in $PATH" immediately after "The install was successful." `refreshPathForPodman()`
reads that same `/etc/paths.d/` entry and prepends it to the current process's `PATH` before
continuing, rather than hardcoding the `.pkg`'s install directory. Also,
`githubLatestAssetURL` (`common.go`, used here and by Windows's WSL2/winget fallback) now
passes `GITHUB_TOKEN`/`GH_TOKEN` as a bearer token when present in the environment — shared
GitHub Actions runner IPs can already be near the unauthenticated GitHub API's 60/hour limit
(confirmed live: a real 403), while a real end user's install never has this env var set.

**Podman Machine setup itself does port over from Windows, since Podman Machine's own guest
OS (Fedora CoreOS) is identical on both platforms.** `ensurePodmanMachine()` in
`install_darwin.go`/`start_darwin.go` mirrors Windows's init/start logic (`podman machine
list --format json`, parse `Running`), and `configurePodmanRestartService()` reuses the exact
same `podman machine ssh` compound-command pattern as Windows (see Windows gotchas above for
why the whole `&&`-chained command must be the sole trailing argument, never split as
separate `"bash","-c",cmd` arguments — the same footgun applies identically here).

**Auto-start at login uses a `launchd` LaunchAgent, not Task Scheduler.**
`~/Library/LaunchAgents/com.pie-manager.podman-start.plist` (`RunAtLoad`) runs `podman machine
start` at login — the direct functional equivalent of Windows's Scheduled Task +
`start-podman.vbs`, loaded/unloaded via `launchctl load`/`unload`.

**No native WebView launcher for v1 — `open <url>` (default browser), matching Linux's own
fallback path.** Windows's `launcher.exe` uses `go-webview2`, a cgo-free binding to the
pre-installed WebView2 runtime. No equivalent cgo-free WebKit binding exists for Go on macOS;
the community `webview/webview` binding needs cgo, which would break `CGO_ENABLED=0`
cross-compilation from Linux CI (cgo cross-compiling to Darwin needs a macOS SDK/clang
cross-toolchain, not just `GOOS`/`GOARCH` env vars). Revisit only if a native window shell is
specifically wanted later — `open <url>` is a legitimate, low-maintenance v1 experience.

**The `/Applications` shortcut is a minimal hand-built `.app` bundle, not a compiled GUI.**
`installAppBundle()` writes `~/Applications/PIE Manager.app/Contents/{Info.plist,MacOS/
pie-manager-launcher}` — a static `Info.plist` (embedded from `packaging/
pie-manager-macos-info.plist`, `__VERSION__` substituted at install time, same pattern as
Linux's `.desktop` `Exec=` substitution) plus a one-line shell script that just runs
`pie-manager start`. No compiled Swift/ObjC, no icon (no `.icns` — Finder shows the generic
app icon; skipped to avoid needing macOS-only icon-conversion tooling `iconutil` in a
Linux-only CI pipeline), no code signing needed for it to be double-clickable. `LSUIElement:
true` in the plist intentionally suppresses the Dock bounce/menu bar flash, since the bundle's
process is fire-and-forget (starts services, opens the browser, exits) rather than a
persistent app with a window.

**Install location:** `~/Library/Application Support/PieManager` — macOS's own idiomatic
per-user app-data convention, playing the same role as Linux's `~/.local/share/pie-manager`.

**Shared refactor enabling this:** `readInstalledVersion`, `detectComposeCmd`,
`podmanImageExists`, `updateEnvPort`, `forceRecreate`, and `copyFile` were moved from
`install.go`/`start.go` (previously `//go:build linux`-scoped) into `common.go` (no build
tag) — these six functions are pure `os`/`os/exec`/`path/filepath` calls with no Linux-specific
behavior, so `install_darwin.go`/`start_darwin.go` reuse them directly instead of duplicating
them, the same way `main_windows.go` does *not* reuse them (Windows's flow genuinely differs
enough — WSL2, winget, reboot handling — that duplication there is warranted; macOS's flow is
close enough to Linux's that sharing is the better call).

## Full install-flow CI testing (all 3 platforms)

`build-installer.yml` runs a **real `install` invocation** (Podman setup, Podman Machine/
native start, image pull, compose up, health-check poll) on all 3 platforms at release time —
not just a cross-compile check or a `version` smoke test. This only exists because the repo is
**public**: standard GitHub-hosted runner minutes (Linux, Windows, *and* macOS alike) are free
and uncapped on public repos regardless of the 2x/10x-vs-Linux multiplier that applies to
private-repo paid quotas — the only real cost is wall-clock time, not money.

**Gated by `detect-installer-changes`, not run on every release.** A full install test is
expensive relative to a routine backend/frontend-only release where the installer's own code
provably didn't move. That job diffs `installer/`, `packaging/`, `compose-prod.yaml`, and the
two workflow files themselves against the *previous* release tag (`git describe --tags
--abbrev=0 "${GITHUB_REF_NAME}~1"`); no previous tag (first-ever release) defaults to "changed"
rather than silently skipping. If none of those paths moved, all 3 full-install jobs are
skipped — the cheap cross-compile checks (`ci.yml`) and the Linux/macOS `version` smoke tests
still always run regardless.

**Linux runs on `ubuntu-latest`, deliberately not a Fedora-flavored environment**, even though
Fedora is this project's actual reference distro. GitHub has no Fedora-hosted runner; running
Fedora-in-a-container would need privileged nested-Podman setup (Podman managing its own
containers from inside a container) for little real benefit — `install.go`/`start.go` have no
Fedora-specific logic beyond the `dnf install` error message text, and the actual Podman/
compose behavior under test is distro-agnostic. The one genuinely Fedora-specific thing this
project has (the `:z` SELinux volume flag in `compose-prod.yaml`) is inert on Ubuntu, not a
divergent code path — same file, same behavior either way.

**`test-macos` never attempts a full `install` run — deliberately, permanently.** GitHub's own
docs state nested virtualization is unsupported on GitHub-hosted macOS runners (Intel or
Apple Silicon alike): ["Nested-virtualization is not supported due to the limitation of
Apple's Virtualization
Framework"](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), also
tracked as open, unresolved feature requests
([actions/runner-images#9460](https://github.com/actions/runner-images/issues/9460),
[#13505](https://github.com/actions/runner-images/issues/13505)). Podman Machine's `podman
machine start` needs exactly that (krunkit/Hypervisor.framework) — confirmed live, every
time: `Error: krunkit exited unexpectedly with exit code 1` /
`podman machine start: exit status 125`, right after Podman itself installed and `machine
init` succeeded. This is a **permanent platform limitation, not a flakiness problem to
iterate on** — do not re-add a full-install step to `test-macos` expecting a future fix to
make it pass; `continue-on-error` would only hide a test that can never succeed. The `version`
smoke test is the full extent of macOS CI coverage; a genuine full-install validation needs
the user's own Apple Silicon Mac.

**Windows and Linux are `continue-on-error: true` — informational, not release gates, until
proven reliable across a few real releases:**
- **`test-windows-install`**: nested virtualization for WSL2 (in turn needed for Podman
  Machine) has been confirmed working on GitHub's `windows-latest` runners by the community
  since the Dadsv5 hardware migration (Jan 2024) — but this is **not officially documented or
  guaranteed** by GitHub. **The installer's embedded `execution-level: administrator` manifest
  (see "Windows executable code signing" above) hung the job indefinitely the first two times
  this was tested** (confirmed live: 45+ minutes, zero progress, twice) — PowerShell's
  `Start-Process` launches an exe via ShellExecute, which honors that manifest by popping the
  interactive UAC consent dialog, and nobody is present to click it on a headless runner. Fix:
  run the installer through a Scheduled Task (`New-ScheduledTaskPrincipal -RunLevel Highest`)
  instead of `Start-Process` — Task Scheduler's own silent-elevation mechanism bypasses the
  interactive consent dialog entirely, without weakening the shipped manifest or a real end
  user's UAC prompt in any way.
- **`test-linux-install`**: lower risk (no elevation dance, no nested hypervisor), but new and
  unproven — kept `continue-on-error` for the same reason, tighten once stable. The job
  installs `podman-compose` explicitly (`pip install podman-compose`, matching `ci.yml`'s own
  compose-syntax step) — without it, `detectComposeCmd()` falls back to the `podman compose`
  subcommand, which on this runner image auto-delegates to Docker's pre-installed compose CLI
  plugin instead of using Podman's own compose implementation, and that plugin can't reach a
  Docker daemon (confirmed live). A real end-user machine without Docker installed alongside
  Podman wouldn't hit this.

Once each of these two has run clean across a handful of real releases, remove its
`continue-on-error: true` to make it a real release gate — don't leave it soft-failing forever
just because it started that way.

**`workflow_dispatch` lets this whole pipeline run on demand without creating a release.**
`build` computes `VERSION` once — a real tag version on `push`; on a manual run, the
**latest already-published release's version** instead of a made-up placeholder, since no
container image exists on Quay.io for a version nobody ever published (confirmed live:
`podman pull` failing with "manifest unknown" for a first attempt at a synthetic
`0.0.0-dispatch-<sha>` version) — and exposes it as a job output so every downstream job reads
the same value instead of re-deriving it from `GITHUB_REF_NAME` (a branch name on manual runs,
which can contain `/` and would break filenames built from it). The "Create GitHub Release"
and "Delete obsolete releases" steps are both gated `if: github.event_name == 'push'` — a
manual dispatch builds and installer-tests all 3 platforms but never touches GitHub Releases
or Quay.io.

## React pattern to avoid — setState with unmodified new array ref

**Witnessed bug (commit 8ca41c2):** infinite re-render loop causing a 16-minute test hang.

**Dangerous pattern:**
```tsx
// filter() ALWAYS returns a new array, even if nothing changes
const handleFresh = (name: string) => {
  setStaleNames(prev => prev.filter(n => n !== name));
};
```

**Correct pattern:**
```tsx
// Return prev unchanged if nothing to do + useCallback for stable reference
const handleFresh = useCallback((name: string) => {
  setStaleNames(prev => {
    const idx = prev.indexOf(name);
    return idx === -1 ? prev : prev.filter(n => n !== name);
  });
}, []);
```

**Rule:** any callback passed as a prop to a child component that uses it in a `useEffect` **must** be wrapped in `useCallback`. Otherwise each parent re-render creates a new callback → child's useEffect re-fires → setState → re-render → infinite loop.

## Custom drag-to-zoom chart checklist — read before building the next one

`RatioIndicatorChart.tsx` (Indicateurs macro page) is the second hand-rolled drag-to-zoom
chart in this app after `IndexChart.tsx`/`PerformancePage.tsx` (Performance page), and its
first build shipped 3 separate regressions that IndexChart's already-working implementation
doesn't have. All three came from re-deriving IndexChart's behavior from memory instead of
reusing/re-reading it. **`frontend/src/utils/chartZoom.ts` (`clampZoomRange`, `timeAxisStyle`)
now holds the shared, tested logic for #2 and #3 below — import it, don't re-derive it.** The
period-preset-button row (1M/3M/1Y/YTD/5Y/10Y/MAX) is the other reusable piece; copy its JSX
shape from `RatioIndicatorChart.tsx` for the next chart. `IndexChart.tsx` itself still has its
own separate, older copies of this logic (not yet migrated to the shared util — do that the
next time you touch it, but it isn't broken today so it wasn't done opportunistically here).

1. **Responsive width: measuring a ref in a `useEffect([])` when that ref mounts
   conditionally.** The standard pattern in this codebase is:
   ```tsx
   const containerRef = useRef<HTMLDivElement>(null);
   const [chartWidth, setChartWidth] = useState(900);
   useEffect(() => {
     const el = containerRef.current;
     if (!el) return;
     setChartWidth(Math.floor(el.getBoundingClientRect().width));
     const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
     ro.observe(el);
     return () => ro.disconnect();
   }, []);  // ← BUG: empty deps
   ```
   If `<div ref={containerRef}>` only renders once loading finishes (`isLoading ? <Spinner/> :
   ... : <div ref={containerRef}>` — true for every chart in this app), `containerRef.current`
   is still `null` on the first render, the effect's `if (!el) return;` bails out, and the
   `ResizeObserver` is **never created**. When the container later mounts for real, the effect
   does **not** re-run (empty deps), so `chartWidth` stays frozen at its default forever —
   confirmed by reading the live SVG's `viewBox` in the browser (`document.querySelectorAll
   ('svg')`), which read `"0 0 900 320"` regardless of window size, while `clientWidth`
   changed on resize. The chart still *looks* right (Victory always CSS-scales its SVG to fill
   the container regardless of the `width` prop) — invisible until something does pixel math
   against the *real* screen size, at which point drag-to-zoom lands on a shifted, wrong date
   range. **Rule:** depend on whatever gates the ref's conditional render (e.g. `[isLoading,
   hasData]`), never `[]`, unless the ref'd element is unconditionally present on mount. This
   exact latent bug is still present in `PerformancePage.tsx`'s `chartContainerRef` — not yet
   fixed there since it wasn't the one reported broken, but do fix it opportunistically if that
   file is ever touched again.

2. **Native text-selection during the drag.** `victory-zoom-container`'s `onMouseDown` calls
   `evt.preventDefault()` *unconditionally* — even with `allowPan={false} allowZoom={false}`
   set (confirmed by reading `node_modules/victory-zoom-container/es/zoom-helpers.js`). A
   hand-rolled brush handler that skips this has **no** default protection against native
   browser drag-selection: the whole drag highlights every text node it passes over (axis
   labels, legend) with the browser's native selection color, layered underneath the intended
   brush rectangle. `userSelect: 'none'` on the container div is not sufficient by itself in
   every rendering engine (confirmed absent from both `IndexChart.tsx` and
   `RatioIndicatorChart.tsx`, yet only the latter showed the bug — the WebKitGTK-based Linux
   desktop wrapper, see "Native window integration" below, is the likely difference from a
   Chromium-based dev-browser test, which is why this survived a Chromium/Playwright
   verification pass). **Rule:** always call `e.preventDefault()` in the mousedown/brush-start
   handler itself — don't rely on CSS `user-select` alone, and don't assume a Chromium-based
   test catches this class of cross-engine rendering difference.

3. **Axis tick format must never be year-only.** A format that shows only the year once
   zoomed out past some threshold produces visibly duplicated labels ("2001 2001 2001 2002
   2002 2002") the moment the zoomed span covers roughly 1-3 years, since several
   evenly-spaced ticks then legitimately fall within the same calendar year. `timeAxisStyle`
   in `chartZoom.ts` only ever has two tiers — day-level (`yyyy-mm-dd`, zoomed to < 90 days) or
   month-level (`yyyy-mm`, everything else, including fully unzoomed) — plus `tickCount: 16`,
   `fixLabelOverlap: true`, and 45°-angled right-anchored labels, matching
   `PerformancePage.tsx`'s `makeAxisStyle` exactly. Use it for any new time-series chart
   instead of writing a fresh `tickFormat`.

4. **Preset-period buttons and the manual "↺ Réinitialiser zoom" button are both required, and
   are not the same control.** Clicking a preset (including MAX) always clears the "manually
   zoomed" state; a completed drag always sets it and clears the active preset. The reset
   button is shown *only* when a manual drag is active (no preset button highlighted) — it is
   not redundant with clicking MAX, because after a manual drag none of the preset buttons
   visually suggest "click here to get back". Removing it in favor of "just click MAX" was
   tried and explicitly reverted after user feedback — keep both.

5. **Hover tooltip: use the shared `ChartCrosshair` component, never Victory's default flyout
   (`ChartVoronoiContainer`/`ChartTooltip`).** The project's established tooltip style is a
   custom crosshair: a vertical dashed guide line + a dark rounded box showing a date header
   plus one row per series with a small colored bullet, short series name, and bold value —
   originally built inline in `IndexChart.tsx`, now extracted to
   `frontend/src/components/ChartCrosshair.tsx` and reused as-is by `RatioIndicatorChart.tsx`.
   Victory's own `ChartVoronoiContainer`/default flyout renders full legend-length text (e.g.
   "Croissance — Ratio (base 100)") with no color bullets and no shared styling — visibly
   inconsistent the moment two chart types sit near each other in the UI. **Rule:** for any new
   time-series chart, track the nearest data point by date on `mousemove` (skip this while a
   zoom-brush drag is active) and render `<ChartCrosshair crosshair={...} />` with **short**
   series names (no "(base 100)"/"(N ans)"/unit suffixes — those stay in the static legend
   below the chart, not the tooltip) — don't wire up `ChartVoronoiContainer` at all.

## UX design decisions — do not revisit

### Exchange rate (exchange_rate) — mandatory manual entry

**Decision: never pre-fill exchange_rate from asset_prices or a market feed.**

The exchange rate applied to a transaction is the **contractual** rate provided by the broker
at execution time. It includes the broker's spread, implicit fees, and depends on the exact
execution time. It differs from the market rate displayed in asset_prices.

→ The user always enters the rate explicitly provided by their financial institution.
→ This is intentional and does not constitute a UX improvement to implement.

### Stale cash_balance_eur alert — obsolete improvement

**Decision: do not implement.**

All transactions go exclusively through the UI → `_update_account_cash_balance()` is the
only update path → desynchronization is impossible in the current workflow.

→ Do not re-propose this improvement.

### Fee subcategory on Transaction — design decision: DO NOT IMPLEMENT

**Retained convention: typed tickers for fees, classified via `Product.fee_type`.**

`Frais` type products use explicit tickers that encode the nature of the fee:
`FRAIS.TAXE.EUR`, `FRAIS.COURTAGE.EUR`, `FRAIS.GARDE.EUR`, etc. — and each such Product now
also carries a `fee_type` (Courtage/Tenue de compte/Intérêts négatifs/Bourse/TTF/Impôts/Conversion,
see "Product/Transaction typology" above) for structured querying.

A `subcategory` field on `Transaction` was implemented then **removed** as redundant with
the typed-ticker convention. Do not reintroduce it — this decision still stands even after
adding `fee_type`, because `fee_type` lives on `Product`, not `Transaction`. A fee's type is
a property of *what it is* (the product/ticker), not of the individual transaction row.

→ To distinguish fee types: use different tickers + `Product.fee_type`, never a field on
`Transaction`.

## Test environment

### Backend tests

Backend tests require a running PostgreSQL instance.

**Never point `DATABASE_URL` at `compose.yaml`'s `postgres` service.** `compose.yaml` (dev)
and the production installer's `compose-prod.yaml` (`~/.local/share/pie-manager/`) both
resolve to the same podman-compose volume, `pie-manager_postgres_data` (verified via `podman
volume ls`) — since both directories share the basename `pie-manager` and neither sets an
explicit project name. Testing against it risks mounting the **real personal-data database**,
and `conftest.py`'s `engine` fixture does `drop_all()`/`create_all()`/`drop_all()`
unconditionally, which would wipe it. Use CI (`ci.yml`'s `integration-tests` job, fully
isolated) or a manually-named, differently-ported throwaway `postgres:16-alpine` container.

**Match CI's Python version (3.14) when testing locally in a container — mismatches
silently under-report coverage, they don't fail.** Verified: running the exact same tests
against the exact same DB under Python 3.12 (with 3.14 elsewhere identical — same
`coverage`/`greenlet` versions) dropped `app/api/routers/transactions.py` from 100% to 47%,
while pure-sync files were unaffected. The cause is greenlet-crossing async DB code (every
`await db.execute(...)`) not registering with coverage.py's tracer consistently across
Python minor versions.

### Testing a data-migrating Alembic revision (backfills, retargeting UPDATEs)

`pytest` never runs Alembic at all — `conftest.py` builds the schema straight from the
current models via `Base.metadata.create_all`. So a migration's `op.execute("UPDATE ...")`
logic can be broken while the suite stays green at 100%. For any revision beyond
`add_column`/`create_table`: apply it for real against a throwaway container seeded with
synthetic rows covering the edge cases the SQL assumes (multi-row groupings, ordering,
count thresholds), then inspect the result with `psql` — don't just check it didn't raise.

This is exactly how migration `mm66nn77oo88` was caught: 3 sequential `UPDATE`s meant to
retarget historical fee transactions each recomputed their `WHERE`/`GROUP BY` against the
*already partially-mutated* table, so the 2nd UPDATE's rename silently broke the 3rd
UPDATE's `HAVING COUNT(*) = 2` filter and dropped a whole group. Fixed by computing all 3
target sets from a single snapshot of the original rows before issuing any UPDATE.

### Frontend tests

Frontend tests run entirely in-process with jsdom — no server required.

```bash
cd frontend
NODE_OPTIONS='--max-old-space-size=8192' npx vitest run --reporter=dot
```

## Frontend test performance — resolved issue

### Root cause (resolved — commit 8ca41c2)
`StalePriceWarning` in `DashboardPage.tsx` had an **infinite re-render loop**:
`handleFresh` called `setStaleNames(prev => prev.filter(...))` which **always returns a
new array** even if nothing changes → React re-rendered → new `handleFresh` reference
→ `ManuelProductStalenessCheck`'s useEffect re-fired → infinite loop.

Fix: `useCallback` + early return if `name` not in array.
Result: fast, clean exit (previously hung for 16+ minutes — see above).

### What does NOT work (do not retry)
- `vi.useFakeTimers()` in DashboardPage.test.tsx → breaks tests using `userEvent` (which requires real timers)
- Brute-force timer clearing (loop 0→max via `window.setTimeout()`) → OOM: jsdom accumulates millions of IDs, loop allocates 8GB+
- `pool: 'threads'` or `pool: 'vmThreads'` → same behavior, generic "forks worker" message
- `teardownTimeout: 5000` → applies to `afterAll/afterEach` hooks, not worker process timeout
- `globalSetup teardown()` → only called AFTER all workers finish
- `--forceExit` → does not exist as CLI flag in Vitest 4.x

### i18n initialization in tests
`patternfly-mocks.tsx` imports `../../src/i18n` to ensure `initReactI18next` runs in each
test file's module context — required for `useTranslation()` to work without a provider.
Components that don't import patternfly-mocks must import `../../src/i18n` (or `./i18n`)
directly (e.g. `SyncBadge.test.tsx`, `RefreshBanner.test.tsx`).

### GitHub Actions annotations
Actions targeting Node.js 24 natively: `checkout@v6.0.2`, `setup-node@v6.4.0`, `setup-python@v6.2.0`,
`upload-artifact@v7.0.1`.

### Never chain more than 2 commands with `&&` in a workflow `run:` block

Under GitHub Actions' default `set -e`, a failing command that is **not the last** member of
an AND-OR list (`cmd1 && cmd2 && cmd3`) is silently exempt from triggering errexit (POSIX
rule) — the step reports success even though `cmd1`/`cmd2` genuinely failed. Confirmed live:
`cd installer && go mod tidy && go vet ./... && go test ./... && CGO_ENABLED=0 go build ./...`
in `ci.yml` let a real `go test` **failure** (`FAIL`, non-zero exit) print to the log while the
step still reported success — this exact line had been in CI since early in the project,
meaning a real installer test failure could have gone unnoticed the whole time. Fix: put each
command on its own line (a bare simple command IS correctly caught by `set -e`) instead of
chaining with `&&`. A 2-command chain where only the trailing command's failure matters
(`sudo apt-get update && sudo apt-get install -y X`, tolerating a stale-but-working package
cache) is fine to leave as-is — the risk is specifically chains of 3+ commands, or any chain
where a *non-final* command's failure is the one that actually needs to fail the step.

### GitHub Actions artifact quota
Image artifacts (500 MB × N tags) accumulate quickly against the GitHub quota.
- `publish-images.yml`: `retention-days: 3` (do not increase)
- `ci.yml` backend coverage: `retention-days: 1`, `continue-on-error: true`
- If quota exceeded: `gh api repos/lautou/pie-manager/actions/artifacts --paginate | python3 -c "..."` to list/delete

### Mandatory cleanup when deleting a tag/release
When deleting tags/releases (cleanup), always do all 3 actions:
1. `gh release delete vX.Y.Z --yes` — delete the GitHub release
2. `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z` — delete the tag
3. Quay.io images: delete manually via Quay.io UI (no automatic cleanup configured)
   Registry: `quay.io/ltourreau/pie-manager-backend` and `quay.io/ltourreau/pie-manager-frontend`

### Frontend coverage — known limitations and solutions

**Problem 1 — `/* istanbul ignore next */` ignored by v8:**
esbuild strips comments before v8 instruments. Use instead:
```
/* v8 ignore next -- @preserve */
```
The `-- @preserve` forces esbuild to treat the comment as a "legal comment".
Source: [Vitest PR #2496](https://github.com/vitest-dev/vitest/pull/2496)

**Problem 2 — RETRACTED, was a misdiagnosis (kept as a cautionary example):**
A branch gap in `commission.ts` (`weekendRate ?? aboveRate`) was long attributed to a suspected
`ast-v8-to-istanbul` nested-ternary double-counting bug ([vitest#10394](https://github.com/vitest-dev/vitest/issues/10394)),
with the branch threshold set to 94% to tolerate it and a claim that "JSON canonical = 100%".
That claim was never verified against the raw `coverage/coverage-final.json` — when actually
checked, the JSON showed the exact same `[8, 0]` branch count as the text reporter (no
discrepancy at all). The real cause: every test called the deprecated `computeRevolutFXCommission`
alias, which hardcodes `weekendRate: 0.01` — nothing ever exercised the `?? aboveRate` fallback
with a `null` weekendRate. One test added, gap closed, no tool bug involved. The suite is now at
literal 100% branches (see below).
**Lesson:** before attributing a coverage gap to a "known tool bug," check the raw
`coverage-final.json` branch counts directly — a gap that survives from the text reporter into
the JSON is not a reporting artifact, it's a real missing test.

**Problem 3 — Istanbul provider via config doesn't load:**
Bug [#8165](https://github.com/vitest-dev/vitest/issues/8165). Workaround: pass `--coverage.provider=istanbul` via CLI.

**Problem 4 — a leftover `mockRejectedValueOnce`/`mockResolvedValueOnce` silently corrupts a
later, unrelated test (looks like a v8 coverage artifact, but isn't one):**
`vi.clearAllMocks()` in `beforeEach` clears call history (`mock.calls`, `mock.results`) but does
**not** drain a queued one-time implementation set via `mockResolvedValueOnce`/
`mockRejectedValueOnce` — only `mockReset()`/`resetAllMocks()` does that. If a test queues a
one-time mock for a call that (after a refactor) its own code path no longer makes, that queued
value stays put and silently attaches to the **next** test that makes a real call to the same
mocked function — even in a different `describe` block. Because many tests in this codebase use
weak assertions (`expect(screen.getByText('Administration système')).toBeTruthy()` — true
regardless of what the code actually did), the corrupted test still passes, but the code path it
was meant to exercise (e.g. a `setTimeout` callback gated behind a successful API call) never
runs, so its lines/branches silently drop out of coverage with no failing test to point at why.

**Symptom:** a block of code shows uncovered in a full-file/full-suite run but covered when the
one relevant test is run alone via `-t` — this looks exactly like a v8/vitest coverage-merging
artifact, but is not.

**How to diagnose:** add temporary `console.log` at the entry of the suspect function and its
catch block, run with `--reporter=verbose`, and read the interleaved stdout across the *whole*
file (not just the target test) — the log reveals the real, unexpected value being caught (e.g.
an error message from a completely different, earlier test) instead of the expected one.

**Fix:** every test that queues a `mockResolvedValueOnce`/`mockRejectedValueOnce` must actually
drive the code path to consume it within that same test, and assert on the resulting behaviour —
not just `toBeTruthy()` on unrelated static text. When a refactor changes how a flow is triggered
(e.g. a click now opens a confirmation modal instead of calling the API immediately), update
every test that relied on the old immediate call. A leftover queued mock from a stale test is
caught by neither TypeScript, ESLint, nor a passing test suite — only by noticing the coverage gap.

**Rule — `vi.mock` must be at the top level of the test file:**
Vitest hoists `vi.mock` to the top of the module. A `vi.mock` nested inside `it()` or `describe()`
produces a warning — will become an error in a future version.
To change a mock value within a test: use `mockReturnValue` in `beforeEach`.

**Problem 5 — position-based selectors (`getAllByText(...)[.length - 1]`, `.slice(-3)`,
`inputs[0]`) silently break when new, unrelated content is added elsewhere on the same page:**
`GlobalConfigPage.tsx` hosts several independent managers (TTF rate, `CommissionManager`,
`ProductManager`, `RegionManager`) stacked as sibling `Card`s. Several pre-existing tests
targeted "the button/input I care about" by position — `saveBtns[saveBtns.length - 1]` (assumed
last "Enregistrer" on the page = the one just opened), `numberInputs.slice(-3)` (assumed the
last 3 number inputs = the FX panel's three fields). Adding the "Indicateurs macro" card (with
its own always-rendered `SettingField` "Enregistrer" buttons and a numeric "Durée MM" input)
*after* those cards in the JSX shifted what counted as "last" — the tests kept passing (or, for
ones with weak assertions like `toBeTruthy()` on static text, silently stopped exercising their
intended code path at all, dropping real coverage with no failing test to point at why — the
exact same failure shape as Problem 4 above, different mechanism).

**Rule:** never select an element by absolute position/count when the page can grow unrelated
siblings later. Scope with `within(container)` on the specific panel/modal being tested (most
robust — a sibling section's new buttons are structurally excluded), or an exact-text match on
the one you mean (`{ name: 'Ticker' }` instead of `{ name: /ticker/i }`, if another field's
label happens to contain the same substring — as happened here with "Ticker Pétrole"/"Ticker
Or"). When adding a new always-rendered element to a page that already has similarly-labeled
siblings, grep the test file for `getAllBy*`/`.slice(-N)`/`[N]`/`/regex/i` patterns that could
now match your new element, don't assume "my new tests pass" is sufficient.

**Current CI thresholds:**
- statements: **100%** (unreachable code marked with `/* v8 ignore next -- @preserve */`)
- branches: **100%** (see Problem 2 above — the 94% figure was based on a misdiagnosis; the
  suite has since reached genuine 100% branch coverage)
- functions: **100%**
- lines: **100%**

**Test utility structure:**
Helpers live in `frontend/tests/utils/` (outside `src/`) to avoid polluting metrics.
Imports from tests: `'../../tests/utils/patternfly-mocks'` etc.

### Recommended test command
```bash
NODE_OPTIONS='--max-old-space-size=8192' npx vitest run --reporter=dot
```

### React Query in tests
Always configure `makeWrapper()` with:
```ts
gcTime: 0, staleTime: Infinity, retry: false,
refetchOnWindowFocus: false, refetchOnMount: false, refetchOnReconnect: false
```
See `frontend/tests/utils/react-query-wrapper.tsx`.

## Capital Gains (Plus-values) — critical business rules

### Endpoint
`GET /api/pv/?portfolio_id=X&account_id=Y` — returns WACOP, unrealized/realized PV per ticker.
Service: `app/services/pv_service.py`. Router: `app/api/routers/pv.py`.

### WACOP convention by instrument type

**Asset (ETFs, stocks)**: BUY = `quantity < 0` / SELL = `quantity > 0`

**Cash Forex (JPYEUR=X, USDEUR=X…)**: **INVERTED** convention
- Acquiring JPY = `quantity > 0` → BUY for WACOP
- Reducing JPY position = `quantity < 0` → SELL
- Using the standard convention treats all JPY purchases as sells with WACOP=0 → massive fictitious PV.

### Products excluded from PV calculation
- `LIQUIDITE.*` (LIQUIDITE.EURO, LIQUIDITE.USD…) — pure cash, not a financial asset
- `instrument_type='Or physique'` (OR.PHYSIQUE, SICAV…) — special valuation logic
- `type='Fee'` and `type='Income'` — do not affect WACOP

### WACOP reset
When `qty_held ≤ 0.001` (float tolerance), position is closed: WACOP resets to 0 on the next buy.
The cumulative `realized_pv_total` is never reset.

### Backend coverage
Backend: **100%** exact (statements, branches). Gate CI: `--cov-fail-under=100`.

## Database backup

- Endpoint `GET /api/admin/backup` → calls `pg_dump` via `subprocess` from the backend container
- Endpoint `POST /api/admin/restore` → `pg_restore --single-transaction` (rollback on error)
- Format `.dump` (custom binary pg_dump, compressed)
- `pg_dump` v17 in the backend container, PostgreSQL v16 — compatible (client newer than server)

## Security / secrets and personal data

Never commit:
- `.env` (DB passwords, API keys)
- **Real names of portfolio owners** — use "Portfolio 1", "Portfolio 2" in code, tests and documentation
- **Real financial data** (.dump/.sql dumps, CSV exports, screenshots with amounts)
- Any personal document (analyses, specs, project notes)

In code and tests: portfolio names = "Portfolio 1" / "Portfolio 2" only.
The repository is intended to be made public — apply this rule from the first commit.

## Mandatory rule — Regression tests and coverage

**With every code change, update the corresponding tests AND verify coverage.**

### Test locations
- Backend: `backend/tests/` (pytest + pytest-asyncio) — run `pytest --collect-only -q` for the current count
  - `test_transactions.py`, `test_portfolios.py`, `test_accounts.py` — CRUD
  - `test_pv_service.py` — WACOP and capital gains calculation
  - `test_rebalancing_service.py` — rebalancing logic (pure Python, no DB)
  - `test_price_sync.py` — Yahoo Finance price sync (httpx mocks, no DB)
  - `test_products_router.py`, `test_snapshots_router.py`, etc.
- Frontend: `frontend/src/**/*.test.{ts,tsx}` (vitest) — run `npx vitest list` for the current count
  - Test helpers: `frontend/tests/utils/` (outside `src/`)

### Coverage enforced in CI
- **Backend**: 100% statements, branches, functions, lines (`--cov-fail-under=100`)
- **Frontend**: statements 100%, branches 100%, functions 100%, lines 100% (see Problem 2 above)

### CI/CD
- `ci.yml` job `validate`: TypeScript + vitest + coverage (no DB)
- `ci.yml` job `integration-tests`: full pytest with ephemeral PostgreSQL
