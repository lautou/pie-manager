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
`readInstalledVersion`, `updateEnvPort`, `detectComposeCmd`, `copyFile`.
These pure utility functions live in `common.go` (shared Linux/Windows) and
`install.go`/`start.go` (Linux only), tested in `install_test.go`.

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
- Revolut/Lolo: real EUR wallet = 0€ (user-confirmed). `cash_balance_eur` said -108.20€ (wrong).
  `SUM(total_amount_eur) WHERE currency='EUR'` gave exactly 0.00€ (right, by luck of Revolut's
  fully-segregated EUR/JPY wallet architecture).
- IBKR/Lolo: real EUR balance = 1.74€ (user-confirmed) = `cash_balance_eur` exactly (right, this
  time). `SUM(total_amount_eur) WHERE currency='EUR'` gave -18.25€ (wrong here).

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

**HAProxy port 80 forbidden in rootless Podman** — HAProxy must listen on port 8080 internally,
mapped to `APP_PORT:8080` in compose. Port 80 causes `Permission denied` at startup.

**`podman-restart.service` enable via SSH** — `systemctl --user enable` fails silently when
`~/.config/systemd/user/default.target.wants/` is owned by root (Podman Machine default).
Fix: create symlink directly:
```bash
podman machine ssh -- sudo chown -R user:user /home/user/.config
podman machine ssh -- ln -s /usr/lib/systemd/user/podman-restart.service \
  /home/user/.config/systemd/user/default.target.wants/podman-restart.service
podman machine ssh -- bash -c "XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload"
```

**Podman machine start at login** — the Task Scheduler VBS uses `True` (wait) + retry loop
(up to 5 attempts, 5s between) because WSL2 may not be ready immediately at login.

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
