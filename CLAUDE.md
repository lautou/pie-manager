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
- **Fixed policy/threshold values** (100% coverage rule, port numbers, interval configs) —
  targets/config, not measurements of current state. Fine to hardcode.
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
These pure utility functions all live in `common.go` (no build constraint — shared by
Linux/Windows/macOS, see "Shared refactor enabling this" in the macOS section below), tested
in `install_test.go`/`common_test.go`.
The last three have no actual Windows dependency (plain HTTP + zip) despite existing
to support a Windows-only fallback — see "Store-independent WSL2/winget install" below —
so they're written as real testable functions instead of being dumped into the
untestable bucket just because their caller lives in `main_windows.go`.

**Intentionally untestable:** `runInstall`, `runStartWithCompose`, `forceRecreate`,
`notify`, `podmanImageExists`, `focusExistingWindow`, `openBrowser`,
all functions in `main_windows.go`, and all functions in `install_darwin.go`/
`start_darwin.go`/`main_darwin.go` (Podman `.pkg` install, Podman Machine setup,
`launchd` agent, `.app` bundle writing — same class of system-interaction code as
`main_windows.go`). These exec external programs (Podman, browser,
OS notifications, Windows API) and require integration-level testing. They are covered
by the CI smoke test (`go build + ./pie-manager version`). Overall installer coverage is
necessarily low (check `go test ./... -cover` for the current figure) — expected and
acceptable for a system-interaction binary.

**Installer structure:**
- `common.go` — shared code (no build constraint): `Version`, `defaultPort`, `findAvailablePort`, `readAppPort`
- `main.go` — Linux CLI dispatcher (`//go:build linux`)
- `main_windows.go` — Windows full installer (`//go:build windows`)
- `install.go`, `start.go`, `install_test.go` — Linux only (`//go:build linux`)
- `main_darwin.go`, `install_darwin.go`, `start_darwin.go` — macOS full installer (`//go:build darwin`)
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
All data entry goes through the UI — the one deliberate exception is the bulk Excel import
(see "Bulk transaction import (Excel)" below), which itself funnels through the same
create-transaction code path as manual UI entry.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + PatternFly 5 + TanStack Query v5 + Vite |
| Backend | Python FastAPI + SQLAlchemy 2.0 async + Celery + Redis |
| Database | PostgreSQL 16 |
| Deployment | **Podman** Compose (never Docker) |
| Containerfiles | `Containerfile` (never `Dockerfile`) |

**Keep `@patternfly/react-icons` on the same major as `@patternfly/react-core`/`react-table`
(currently v5) — do not bump it alone.** Confirmed live: react-icons v6 ships a dual-glyph
mechanism per icon (an old design + a new "RH-UI" redesign) meant to be toggled via PatternFly
v6 core's own CSS, which this app doesn't load (still on core v5). Without that CSS both
glyphs render nested, unstyled, simultaneously. It happens to look fine today for every icon
this app currently uses (verified visually — both are solid `currentColor` silhouettes similar
enough that the overlaid union still reads correctly), but it's an unsupported pairing: any
future icon addition isn't guaranteed to render cleanly, and no test can catch a purely visual
regression like this. Revisit only as part of a real PatternFly v5→v6 core migration (core +
table + icons bumped together), never as a standalone icons bump. Tracked in #59.

**`recharts` is on v3** (bumped from v2, issue #3) — the only chart type it's used for is the
Dashboard's Treemap (`DashboardPage.tsx`), since PatternFly-charts/Victory has no Treemap
equivalent. v3's `Treemap` requires an index signature (`[key: string]: unknown`) on custom
data node types to pass extra fields (`pool`, `poolColor`, `pct`) through to the `content`
render prop — add it to any new `TreemapNode`-like interface, or those fields silently come
back `undefined`. Trade-off accepted: v3's internal rewrite onto `@reduxjs/toolkit` adds ~8%
to the production bundle size.

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

**`backend/Containerfile` is a multi-stage build** (`builder` → `runtime`, #20) — the final
image no longer carries `pip`, `setuptools`, `build-essential`, `curl`, or `gnupg`, none of
which the app needs after `pip install` finishes at build time. This structurally closes a
class of Trivy finding that `requirements.txt` has no lever to fix: HIGH CVEs in pip's own
vendored `msgpack` and in `setuptools` itself (both ship pre-installed in the `python:3.14-slim`
base image, not from anything this Containerfile's own `RUN` steps add — see #11/#20).
`builder` installs Python deps into an isolated `--prefix=/install` (kept separate from the
base image's own pip) and stages `pg_dump`/`pg_restore` plus their full transitive
shared-library closure into `/pg-runtime/` via an `ldd`-based walk (self-computing on every
build, not a hand-maintained `.so` list that goes stale). `runtime` starts fresh from the same
base+digest, removes the base image's own pip/setuptools/wheel
(`python -m pip uninstall -y pip setuptools wheel` — uses pip's own RECORD manifest so
companion files like the `_distutils_hack` `.pth` shim are removed correctly, not a `rm -rf`
glob), then copies both artifacts in. A `RUN` step at the end of the `runtime` stage — a real
import of `app.main`/`app.tasks.celery_app` plus `pg_dump --version`/`pg_restore --version` —
fails the build itself immediately if either copy is incomplete, instead of only surfacing at
container start. **Both `FROM` lines must be bumped to the same digest together** — a future
Dependabot base-image PR that only updates one would silently run the `builder`'s `ldd`
closure against a different glibc than the `runtime` stage ships. Verified live: real
`podman build`, a local Trivy scan confirming `msgpack`/`setuptools` are gone (present on the
old single-stage image, absent here), a ~43% image size reduction (772 MB → 439 MB), and full
`podman-compose up` smoke tests (see below) on both dev and prod-style stacks.

**`backend/Containerfile` runs as a non-root user (`appuser`, UID/GID 1000)** — fixed
issue #17 (previously ran fully as root). Celery Beat's schedule file is redirected to
`/tmp` (`beat_schedule_filename` in `app/tasks/celery_app.py`) instead of the default
CWD (`/app`), so `appuser` never needs write access to the application source tree —
this also sidesteps host/container UID mismatches on the dev bind-mount
(`./backend:/app:z`), since reading it only relies on standard "other" read permission
bits, not an exact UID match. `pg_dump`/`pg_restore` (admin backup/restore) and the
Excel import already only touch `/tmp` or memory, so neither needed any change.
Verified live (not just build success): a real `podman-compose up` in both dev
(bind-mount) and prod-style (`alembic upgrade head && uvicorn`, baked image) modes,
confirming clean startup, no permission errors, and a working backup+restore
round-trip, all as `appuser`.

**`frontend/Containerfile` runs `node:24-alpine`** (matches CI's `node-version: '24'` in
`ci.yml`). Bumped from `node:20-alpine` (2026-08) after a Trivy scan flagged an Alpine
`libssl3`/`libcrypto3` CVE (CVE-2026-45447) that a rebuild alone couldn't fix — Node 20
reached EOL 2026-04-30 and Docker Hub stopped rebuilding `node:20-alpine` shortly before,
so its baked-in Alpine packages were permanently frozen pre-fix. Verified via real
`podman run` + `apk list --installed` that `node:22-alpine`/`node:24-alpine` (both actively
rebuilt) already carry the fixed `openssl` packages. If a future CVE report on this image
assumes "just rebuild it", check the base tag's actual last-push date on Docker Hub first —
an EOL runtime's official image can silently stop receiving any OS-level security rebuilds.

**Do not bump `node:24-alpine` → `node:26-alpine` before Node 26 reaches Active LTS
(2026-10-28) — tracked in #57.** Dependabot PR #29 proposing this was closed (not
`@dependabot ignore`d) rather than merged: the bump itself builds and runs cleanly (verified
live), but Node 24 is Active LTS until 2026-10-20 / Maintenance until 2028-04-30, while Node 26
is still on the less battle-tested "Current" release line until its LTS date. No urgency to
take on that risk early. Dependabot's own weekly scan will re-propose an equivalent PR on its
own — merge it once Node 26 is actually Active LTS, don't defer indefinitely.

**`frontend/Containerfile` is a multi-stage build** (`builder` → `runtime`, #13), mirroring
the backend's #20 refactor for the same reason: `builder` runs `npm ci` (now copies
`package-lock.json` before install too — previously only `package.json` was copied, so the
image's `npm install` silently ignored the pinned lockfile and re-resolved from the registry
at build time, picking up whatever transitive versions happened to be current) and the app
source; `runtime` starts fresh from the same base+digest, deletes the base image's own bundled
npm CLI (`rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx`) before
copying in `builder`'s `/app`. This structurally removes a class of Trivy finding
`package.json` has no lever to fix: HIGH/CRITICAL CVEs in npm's own vendored `tar`/
`brace-expansion`/`ip-address`/`undici` (pre-installed in the `node:24-alpine` base image, not
from anything this app's own dependencies pull in — confirmed by locating them under
`/usr/local/lib/node_modules/npm/node_modules/`, not `app/node_modules/`). Safe to remove
because the dev server is invoked via its own binary (`node_modules/.bin/vite`, both in the
Containerfile's `CMD` and in `compose.yaml`'s dev override), never via `npm run` — `node`
itself doesn't depend on npm's bundled `node_modules` at runtime. Verified: real
`podman build`, a from-scratch Trivy scan going from 4 HIGH/CRITICAL findings to 0, and a full
`podman-compose up` smoke test (dev stack, isolated project name) confirming the Vite dev
server still starts and serves the app correctly. As with the backend, **both `FROM` lines
must be bumped to the same digest together** on a future base-image update.

### Development (compose.yaml)

```
compose.yaml
├── postgres (PostgreSQL 16)
├── redis
├── backend (FastAPI)
├── worker (Celery worker + Beat, `-B` flag)
└── frontend (Vite dev server, port 5173)
```

### Production (compose-prod.yaml)

```
compose-prod.yaml
├── postgres (PostgreSQL 16)             restart: unless-stopped
├── redis                                restart: unless-stopped
├── backend (FastAPI)                    restart: unless-stopped, no exposed ports
├── worker (Celery worker + Beat, -B)    restart: unless-stopped
├── frontend (Vite dev server)           restart: unless-stopped, no exposed ports
└── haproxy (reverse proxy)              restart: unless-stopped, port APP_PORT:8080
```

In production, **HAProxy** is the single public entry point. It routes:
- `/api/*` → `backend:8000` (FastAPI) — active health check on `/api/admin/health`
- `/*` → `frontend:5173` (Vite dev server)

Backend and frontend containers have no exposed ports — all traffic flows through HAProxy.
HAProxy uses `parse-resolv-conf` + `resolve-prefer ipv4` to handle Podman's DNS correctly
on both Docker (127.0.0.11) and Podman (gateway IP) environments.

### Port selection (production)

Default port: **14943** (constant `defaultPort` in `installer/common.go`).

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

**Image cleanup** — use targeted removal of old pie-manager versions only, never
`podman image prune -af`, which would delete images from other projects on the machine.

**Fedora/RHEL short image names** — always use fully qualified names
(`docker.io/library/postgres:16-alpine`) to avoid "short-name resolution enforced" errors in
non-interactive contexts.

**Ad hoc container smoke tests (`podman run -p ...` outside compose) — see the global
`~/.claude/rules/podman-pasta-dual-stack-networking.md` rule**: use `curl -4`/`127.0.0.1`,
never bare `localhost`, or a healthy Vite dev server can look unreachable
(`Connection reset by peer`).

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
  - `_update_account_cash_balance(db, account_id, portfolio_id, delta, tx_type, ticker,
    operation=None)` → writes here (the `tx_type`/`ticker` args gate the forex-position/
    Attribution skip logic, see "Transaction running-balance display" below)
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
that creation order). **If you ever touch that retargeting SQL again**, read "Testing a
data-migrating Alembic revision" below first — a naive 3-sequential-UPDATE version silently
dropped the 2-fee group's TTF leg there.

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

`dashboard_service.get_holdings()` applies this adjustment: for each held forex ticker it
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
sign/fee/balance rule and its existing test coverage apply unchanged.

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
import would silently drop real relevé data) while every other non-Achat/Vente Sens rejects
the row with a validation error if Courtage/TTF is entered non-zero (not silently forced to 0
— an omitted/blank cell is what defaults to 0).

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

## Rebalancing — "capital insuffisant" needed-amount is backend-computed, not a frontend estimate

`compute_injection_total_needed` (`rebalancing_service.py`) answers "how much total capital
(liquidity + injection) would it take to bring every pool to at least its target via
injection alone, no selling" — returned as `injection_total_needed` in the rebalancing API
response and consumed as-is by `RebalancingPage.tsx`'s "Injection seule" sufficiency banner.
It solves by fixed-point iteration, not a single closed-form pass: growing the total pulls up
every pool's euro target, which can push an already near-target pool below its own target
even though it received no money — the underweight set is recomputed and grown until it
stabilizes. Returns `None` when even unlimited injection can't satisfy every pool (the
underweight set's combined target_pct reaches 100%).

**`None` is a common, expected real-world outcome — not just a defensive guard.** Correction
of an earlier (wrong) claim in this file: a "Legacy" pool with `target_pct=0` holding real
value (an old holding no longer part of the active strategy) makes `None` mathematically
*guaranteed*, not just possible, the moment its value exceeds one cent — proven via the
iteration's own conservation identity: with that pool as the sole remaining complement
member, its current value must equal `target_pct(=0) * total_after - legacy_value`, forcing
it into the underweight set at some iteration no matter how large `total_after` grows, since
the active pools already target 100% between them and can never fully absorb a total that
also includes the legacy pool's frozen, off-target money. `find_untargeted_pools_with_value`
(pools with `target_pct≈0` and `current_value > 0.01`) identifies the actual blocking pool(s),
returned as `injection_blocking_pools` in the API response — `RebalancingPage.tsx` names them
in the banner (`insufficientImpossibleWithCause`) instead of a vague "even with unlimited
capital" message. Only truly malformed input (e.g. a partial pool subset whose targets don't
sum to 1) hits this without an identifiable blocking pool, in which case the banner falls back
to the generic `insufficientImpossible` message.

**Why backend, not frontend:** an earlier frontend-only version (`computeRebalancingStatus`,
deleted) used a single-pass closed form completely decoupled from the actual allocation
algorithm and from the pool set it was fed (a filtered subset whose current values didn't sum
to the `totalCurrent` argument it was given) — it under-estimated the true needed amount in
exactly the flip-underweight scenario above, producing a "manque : 4 737€" banner alongside
"Acheter 5€/8€/8€" suggestions that looked contradictory to the user. Moving the computation
into the same service module as the real allocation algorithm removes the possibility of the
two drifting apart.

## Rebalancing — gap severity thresholds are configurable, not hardcoded

`rebalancing.tolerance_ok_pct` (default 1) and `rebalancing.tolerance_warning_pct` (default 2)
are `SystemSetting` rows edited via the "Rééquilibrage — seuils de tolérance" card in
Configuration générale (`GlobalConfigPage.tsx`), read in `RebalancingPage.tsx` via
`useSystemSetting`. A single absolute-value severity scale (`|gap| < ok` → green,
`ok ≤ |gap| < warning` → orange, `|gap| ≥ warning` → red) drives the per-pool label and both
the before/after allocation bars uniformly — previously these were three separate, mutually
inconsistent hardcoded thresholds (an asymmetric -0.5%/+1.5% window for the label, ±2% for the
before-bar, ±1.5% for the after-bar).

**The zero-action pool label is self-explanatory and severity-only, no over/under direction**
(`onTargetLabel`/`warningLabel`/`dangerLabel` in `RebalancingPage.tsx`, e.g. "Déséquilibre
léger (écart entre 1% et 2% — à surveiller)") — the actual configured `ok`/`warning` values are
interpolated into the text itself, never hardcoded, so the label stays accurate if those
settings change. This deliberately drops the earlier "Surpondéré"/"Sous-pondéré" distinction
from the *visible* label (a simplification, not an oversight) — but the underweight case
(`gapBefore < 0` and non-ok) still wraps the label in `underweightTooltip`, since "capital
insufficient to act" is real explanatory context a bare severity level can't convey.

## Rebalancing — banner/card copy conventions

Every "capital" banner (Injection seule and Hybride, sufficient/insufficient/partial/
impossible) appends `liquidityIncluded` ("Incluant liquidités à répartir : {{liquidity}}.") on
its own line, where `{{liquidity}}` is `total_apport` (liquidity + any typed injection) — not
liquidity alone. An earlier version showed just the liquidity portion, reasoning that naming
two separately-computed figures (liquidity vs. injected) risked one of them being wrong; user
feedback reversed this — the combined `total_apport` is what's actually being distributed in
the simulation, and splitting it back out added confusion, not clarity. The "impossible"
banner's own explanation and its "switch mode" call-to-action are two more separate lines
(`insufficientImpossible(WithCause)` / `switchModeHint`), not one run-on sentence. Each pool
card shows one visible "Cible : X%" label above the
Actuel/Après bars (shared by both, since the target doesn't change between them) and a
per-row `Écart actuel` / `Écart cible` label next to each bar instead of one combined line at
the bottom — the combined line used to sit far from the "Actuel" row it partly described.

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

## Country market performance leaderboard (portfolio-independent)

Second tab on the Indicateurs page ("Performance des marchés", `MarketPerformanceSection.tsx`),
deliberately kept separate from the growth/inflation tab (`GrowthInflationSection.tsx`) via
PatternFly `Tabs` — a static ranked bar chart (categorical x-axis, no time series) has nothing
in common with the region-scoped ratio line charts, so mixing them on one view was rejected.

**Ranking**: `country_performance_service.compute_country_performance()` ranks every configured
`CountryPerfConfig` row by trailing-1-year, **EUR-adjusted** performance —
`(index_latest × fx_latest) / (index_anchor × fx_anchor) − 1`, multiplicative (never additive,
since a local-currency move and an FX move compound). EUR-currency countries skip the FX
factor entirely. Only the top N (`SystemSetting country_perf.top_n`, default 15) are returned,
sorted ascending for the chart (worst-of-the-top-N left, best right). A country whose index or
FX series has no snapshot within `ASOF_TOLERANCE_DAYS` (10) of "today" or "~1 year ago" is
excluded from ranking rather than distorting it with stale data.

**Storage reuses `MacroSeriesPrice`** (no new price table) via a distinct series-key
namespace: `country_{code}_equity` per country, `fx_{currency}` per **distinct non-EUR
currency** (shared/deduped across countries with the same currency). `CountryPerfConfig`
(code/label/index_ticker/currency/index_label) is a separate, user-editable table — no "last
remaining row" delete guard, unlike `MacroRegion` (an empty universe just yields an empty
chart).

**`index_label`** (e.g. "KOSPI Composite", "CAC 40", "Shanghai Composite") is a
human-readable name for `index_ticker`, mirroring `MacroRegion.equity_label`/`bond_label` —
added via migration `ss22tt33uu44` after comparing our leaderboard against an external
reference chart revealed that different sources track different underlying indices for the
same country (e.g. Shenzhen vs Shanghai for "Chine"). Shown in the chart's hover tooltip
(`"{country} — {index_label}: {pct}%"`) and as its own column in `MarketCountryManager`, so
which index feeds a bar is never ambiguous.

**Shared Yahoo fetch/Redis-status helpers**: `app/tasks/yahoo_fetch.py`
(`fetch_yahoo_chart`/`fetch_yahoo_history`) and `app/tasks/sync_status.py`
(`get_redis`/`write_status`) were extracted here from what used to be near-identical private
copies in `prices.py`/`macro_indicators.py`/`etf_holdings.py` — this task was the third
occurrence of the same duplication, the trigger for finally factoring it out.

**Seed list ticker gotchas** (found via empirical Yahoo verification before trusting the
migration seed, same discipline as `^SBF120` above): Poland's `WIG20.WA` returns exactly 1
data point regardless of window (dead) — replaced with `ETFBW20TR.WA`, an ETF tracking the
same index. Taiwan (TWD) and Turkey (TRY) are excluded from the seed entirely: their direct
`{CCY}EUR=X` crosses (`TWDEUR=X`, `TRYEUR=X`) are also always 1 point — only the *reverse*
cross (`EURTWD=X`/`EURTRY=X`) has real history, which would need a per-currency reciprocal
special case to support, not worth it for 2 currencies.

**Known pitfall — aria-label collisions between independent CRUD managers on the same
page**: `MarketCountryManager`'s edit/delete buttons originally used the same
`"{action} {code}"` aria-label pattern as `RegionManager`'s. Since both managers can have a
row with the same code (e.g. `fr`, seeded in both `macro_regions` and
`country_perf_configs`), their buttons collided (`"Modifier fr"` × 2) on the same
Configuration générale page — a real accessibility bug and a Playwright strict-mode
violation, only caught by a live browser check (unit tests used non-overlapping fixture
codes, which hid it). Fixed by adding a disambiguating noun (`"Modifier pays fr"`). When
adding a second CRUD table whose codes can overlap with an existing one on the same page,
disambiguate the action labels up front.

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

### Container image vulnerability scanning (Trivy)

`publish-images.yml` scans both published images with Trivy (`severity: HIGH,CRITICAL`) on every
release, with `ignore-unfixed: true` — Debian OS-package CVEs with no upstream fix are common and
not actionable (confirmed live: 103 such HIGH/CRITICAL findings on a single release, see #11/#18), so
filtering them out keeps the report limited to CVEs that can actually be fixed by bumping a
pinned version.

`msgpack`/`setuptools` (the two HIGH CVEs `requirements.txt` had no lever to fix — see #11) are
now structurally gone from the backend image via the multi-stage build in #20 (see "Container
architecture" above) rather than suppressed in the scan config.

**Still report-only for now** (`exit-code: 0` + `continue-on-error: true`) — see #21 to flip this
to a real release gate (`exit-code: 1`, drop `continue-on-error`) once the filtered scan has run
clean across a handful of releases, mirroring the `test-windows-install`/`test-linux-install`
progressive-hardening pattern below.

### Backend backup/restore smoke test (`smoke-test-backend`, #45)

`publish-images.yml`'s `smoke-test-backend` job (`needs: publish`, `continue-on-error: true` —
same progressive-hardening pattern as `test-windows-install`/`test-linux-install`) runs a real
`pg_dump`/`pg_restore` round-trip against the just-published backend image: starts real
`postgres:16-alpine`/`redis:8-alpine` GitHub Actions services, runs the image via
`podman run --network host` (so `localhost:5432`/`localhost:6379` inside the container reach the
services' host-published ports) with the same `alembic upgrade head && uvicorn ...` command as
`compose-prod.yaml`, waits for `/api/admin/health`, seeds one portfolio, downloads
`/api/admin/backup`, re-uploads it to `/api/admin/restore`, then confirms the seeded portfolio is
still present. This exists because #20's multi-stage build hand-copies `pg_dump`/`pg_restore`'s
shared-library closure instead of apt-installing `postgresql-client`, and the Containerfile's own
build-time check (`pg_dump --version`) only proves the binaries *start* — it can't catch a future
base-image bump breaking the closure in a way that only surfaces against a real database. Verified
locally end-to-end (same commands, standalone containers) before landing.

### Dependabot + pinned base image digests

`.github/dependabot.yml` covers 6 ecosystems: `pip`/`npm`/`docker` (backend and frontend each),
`docker-compose` (root, covers both `compose.yaml` and `compose-prod.yaml`), and
`github-actions`. Every base image (`Containerfile` `FROM` lines, `compose.yaml`/
`compose-prod.yaml` `image:` lines) carries a `@sha256:` digest pin alongside its tag — without a
digest, Dependabot's `docker`/`docker-compose` ecosystems have nothing discrete to bump, and the
base image silently drifts underneath a floating tag (see #11/#19: a Trivy-flagged package was
already gone from a same-tag rebuild days later). If a Dependabot PR changes the tag itself (not
just refreshes the digest on the same tag), the "match CI's Python version" verification rule
above still applies — a passing CI job doesn't prove the Containerfile itself still builds.
`backend/Containerfile` has **two** `FROM` lines since its multi-stage refactor (#20, both
pinned to the same base+digest) — a Dependabot PR bumping one must bump both, or the
`builder` stage's `ldd`-computed shared-library closure ends up staged for a different glibc
than the `runtime` stage actually ships. `frontend/Containerfile` also has two `FROM` lines
since its own multi-stage refactor (#13) — same rule: bump both together.

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

**Launcher distribution: Store-first, local-exe fallback (issue #63, fix for #60's Smart App
Control block).** SAC can hard-block a sideloaded `launcher.exe` outright with no in-product
override (issue #60) — no code-signing certificate path fixes this reliably. `launcher.exe`
itself needs no elevation, so it's distributed as a full-trust MSIX package
(`installer/launcher/AppxManifest.xml`, identity `PIEManager.PIEManager`, PFN
`PIEManager.PIEManager_9h5hzpm8nc7w0`, Store ID `9PM8GPSMJG0N`) via the Microsoft Store — Store
apps bypass SAC/SmartScreen by design. Confirmed live
(`installer/testing/msix-loopback-poc/`) that a full-trust (`mediumIL`) packaged WebView2
control reaches `localhost` exactly like the unpackaged exe does — the loopback-isolation
restriction only ever applied to sandboxed AppContainer/UWP apps, never to full-trust Desktop
Bridge apps.

`main_windows.go`'s desktop-integration step is hybrid: `ensureStoreLauncherInstalled()` checks
`Get-AppxPackage`, and if absent, opens `ms-windows-store://pdp/?productid=9PM8GPSMJG0N` and
waits (with a "keep waiting or fall back?" prompt after each 5-minute window). If the Store
isn't available on the machine at all (the same class of gap already handled for WSL2/winget
via `installWSLFromGitHub`/`installWingetFromGitHub`), the user declines, or `CI=true`, it falls
back to today's exact embed-write-shortcut-launch behavior — confirmed live via a full
`test-windows-install`-style run that this fallback fires cleanly with no hang/crash. Shortcuts
target `explorer.exe` with `Arguments = shell:AppsFolder\<AUMID>` on the Store path (Explorer
resolves the correct tile icon from the AUMID itself, no `IconLocation` needed) or the raw exe
path on the fallback path.

`installer/launcher/gen-assets/main.go` renders the MSIX Store logo assets (`Square44x44Logo`,
`Square150x150Logo`, `StoreLogo`) by extracting the largest PNG-encoded frame directly from
`pie-manager.ico` and bilinearly downsampling it — **not** from `installer/launcher/*.png`,
which are gitignored local-only icon-extraction artifacts (see `.gitignore`) absent on a fresh
checkout. `build-installer.yml`'s `package-launcher-msix` job builds, packages, and signs a real
`pie-manager-launcher-<version>.msix` release artifact on every release (ephemeral self-signed
cert matching the real Publisher CN — a Store submission's original signature never needs to
chain to a trusted root, Microsoft re-signs at publish time) — this only produces a downloadable
artifact, it does **not** submit anything to Partner Center.

**As of this writing the Store listing is a reserved-but-unpublished Partner Center draft** —
uploading `pie-manager-launcher-<version>.msix` there, filling in listing details, and
submitting for certification are manual steps for the repo owner (registering the Store
developer account itself required personal identity verification). Until the listing is
confirmed live and approved, real users only ever take the local-fallback path above — identical
behavior to before this feature, since the Store-detection check simply never finds the app
installed.

**Automating every update *after* the first manual submission.** Microsoft's Store submission
API cannot create an app or its first submission — that one-time step (upload, listing details,
age ratings, certification) must happen by hand in Partner Center, no way around it. Every
update after that first live, approved submission can be automated: `package-launcher-msix`'s
last two steps (`build-installer.yml`) call the official `microsoft/microsoft-store-apppublisher`
GitHub Action + `msstore` CLI (`msstore reconfigure` then `msstore publish <msix> -id
9PM8GPSMJG0N`) to push every new release's `.msix` straight to the Store — no more manual
uploads. These steps self-skip (an `if:` checking all four secrets are non-empty) until the
one-time setup below is done, so they're harmless to have merged early:

1. Create/associate a Microsoft Entra ID (Azure AD) tenant with the Partner Center account
   (Partner Center → Account settings → Entra applications) — free, doable from an individual
   account, no pre-existing organization needed.
2. Register an app in that tenant, assign it the **Manager** role on the Partner Center account.
3. Add 4 repo secrets (Settings → Secrets and variables → Actions): `AZURE_AD_TENANT_ID`,
   `AZURE_AD_APPLICATION_CLIENT_ID`, `AZURE_AD_APPLICATION_SECRET` (from the Entra app
   registration), `SELLER_ID` (Partner Center Account settings → Identifiers → "ID de vendeur").

Not live-tested (can't be, until the first manual submission is live) — written directly from
[Microsoft's own GitHub Actions publishing guide](https://learn.microsoft.com/en-us/windows/apps/publish/msstore-dev-cli/github-actions),
verify the actual publish step once the secrets are in place.

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
2. After reboot, installer auto-resumes via a Windows Scheduled Task (not RunOnce — see
   "Auto-resume after reboot uses a single Scheduled Task" below)
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

**Target macOS version: 14 Sonoma minimum, 15 Sequoia recommended.** The installer doesn't
pass a `--provider` flag to `podman machine init`, so it relies on whatever Podman's own
current default is for macOS — **`libkrun`, not `applehv`** (verified against
docs.podman.io: `libkrun` is the starred/default provider for macOS in current Podman
releases; `applehv` is only the alternative — correcting an earlier wrong claim in this
file). Either provider requires macOS 13 Ventura at minimum — but Ventura is already EOL (no
security patches since Aug 2025), so Sonoma (still patched) is the documented floor instead.
No runtime OS-version check exists in
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
rather than silently skipping. If none of those paths moved, the 2 gated full-install jobs
(`test-linux-install`, `test-windows-install`) are skipped — `test-macos` is **not** gated by
this (it always runs, but only ever does a `version` smoke test, never a full install, see
below) — and the cheap cross-compile checks (`ci.yml`) and the Linux/macOS `version` smoke
tests still always run regardless.

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
  user's UAC prompt in any way. **A second, distinct hang surfaced right after this fix**: the
  install log showed every real step (WSL2/Podman/Docker Compose, `podman compose up -d`,
  shortcuts) succeed within ~3 minutes, yet the Scheduled Task still reported `Running` a full
  10 minutes later — `popupYesNo`'s final "Voulez-vous lancer maintenant ?" `MessageBox.Show`
  blocks forever with nobody to click it. Fixed at the source in `popup()`/`popupYesNo()`
  (`main_windows.go`): both skip the interactive dialog and log instead when `CI` is set in
  the environment (GitHub Actions, and virtually every other CI provider, sets `CI=true`) —
  never set on a real end user's machine, so their experience is unchanged. **Third hang, same
  symptom, after that fix**: a Scheduled Task does not inherit the calling PowerShell step's
  own process environment — Task Scheduler builds a fresh environment block for the target
  user from machine/user-scoped variables, not the caller's transient `env:` block — so
  `os.Getenv("CI")` still saw nothing and the popup still blocked. Fixed by persisting it with
  `[Environment]::SetEnvironmentVariable('CI', 'true', 'Machine')` in the workflow step
  *before* registering the task, harmless since this runner VM is destroyed right after.
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

**Both jobs poll Quay.io before pulling — `publish-images.yml` fires off the same tag push with
no ordering guarantee.** Confirmed live on the real v1.3.0 release: `test-linux-install` failed
in 15s on "manifest unknown" and `test-windows-install` failed at the compose step, both well
before `publish-images.yml` finished pushing 4 minutes later (issue #16). Each install-test job
now has a "Wait for images to be published to Quay.io" step (polls the public
`quay.io/api/v1/repository/.../tag/` endpoint, 10-minute timeout) before invoking the installer —
chosen over reordering the two workflows via `workflow_run` (ref/context quirks) or merging them
into one (bigger restructure for a timing bug).

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

### Changelog generation

`CHANGELOG.md` is regenerated by `git-cliff` (`cliff.toml`) on every tag push — committed to
`main` **after** the release is created and its binaries uploaded, and never fails the job on a
push error, since documentation must never block the release itself. Its newest entry is also
appended to the GitHub Release body — this is what actually survives the "Delete obsolete
releases" cleanup above, since that step only prunes GitHub Release objects, not git history.
Generation is restricted to the `v1.0.21..` commit range: tags `v1.0.1`–`v1.0.20` were deleted
during early iteration and no longer exist, so `cliff.toml`'s static **footer** (rendered last,
oldest-entry-last like every other entry, per Keep a Changelog convention) hand-documents the
initial release through `v1.0.21` as one combined entry instead of guessing at the lost
boundaries — see issue #15. Every release from `v1.0.22` onward is generated automatically and
is accurate. Commit messages must stay Conventional-Commits-formatted (`type(scope): message`)
for this to keep working — `feat`→Added, `refactor`/`perf`→Changed, `fix`→Fixed (Keep a
Changelog section order); `docs`/`chore`/`ci`/`build`/`test`/`style`/merge commits are
intentionally omitted from the changelog.

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
only update path → desynchronization **between two competing update paths** is impossible in
the current workflow.

→ Do not re-propose an alert for that specific scenario (e.g. a stale-import-vs-UI mismatch).

**This does not mean `cash_balance_eur` itself can't be wrong.** A single-path *logic* bug can
still corrupt it — confirmed for real: Revolut/Portfolio 1's `cash_balance_eur` read -108,20€
against a real balance of 0,00€, caused by forex-position transactions contaminating the EUR
balance inside `_update_account_cash_balance()` itself (see "Transaction running-balance
display" above for the full fix and the manual one-time correction). If a *different* kind of
staleness/correctness concern is raised in the future (not the two-path desync this decision
rejects), evaluate it on its own merits rather than citing this decision as blanket proof
`cash_balance_eur` is always trustworthy.

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

**Expected noise: `Error: <message>` lines from the App.test.tsx ErrorBoundary tests.**
jsdom reports an error thrown inside a React component through its own internal event-dispatch
"virtual console", a separate channel from `console.error` — so it prints even though those
tests already mock `console.error` to suppress React's own dev-mode logging. Not a real failure; the suite still exits 0 with every test green. Confirmed via
`--reporter=verbose`: the trace points at `App.test.tsx`'s mocked `RebalancingPage` throw, not
an unhandled error elsewhere.

## Frontend test performance — resolved issue

A 16-minute test hang was traced to `StalePriceWarning` (`DashboardPage.tsx`)'s infinite
re-render loop — see "React pattern to avoid — setState with unmodified new array ref"
above for the root cause and fix (commit 8ca41c2). Result: fast, clean exit.

### What does NOT work (do not retry)
- `vi.useFakeTimers()` in DashboardPage.test.tsx → breaks tests using `userEvent` (which requires real timers)
- Brute-force timer clearing (loop 0→max via `window.setTimeout()`) → OOM: jsdom accumulates millions of IDs, loop allocates 8GB+
- `pool: 'threads'` or `pool: 'vmThreads'` → same behavior, generic "forks worker" message
- `teardownTimeout: 5000` → applies to `afterAll/afterEach` hooks, not worker process timeout
- `globalSetup teardown()` → only called AFTER all workers finish
- `--forceExit` → does not exist as CLI flag in Vitest 4.x

### Expected noise: `act(...)` warnings across many page test files
`Warning: An update to <Component> inside a test was not wrapped in act(...)` appears in
several page test files — an async state update (React Query background refetch, a `useEffect`
timer) lands slightly outside React Testing Library's tracked `act()` boundary. Not a sign of
incorrect component behavior by itself, and the suite still passes with 100% coverage regardless.
Given the number of files involved and the varied async causes, this is deliberately left as
documented noise rather than chased down file-by-file for a purely cosmetic fix (see #8) — unlike
the `validateDOMNesting` warning that used to accompany it (fixed at the source: `patternfly-mocks.tsx`'s
`Thead`/`Tbody` mocks were bare passthrough fragments, so `<Tr>` landed directly under `<table>`
with no wrapping element — now real `<thead>`/`<tbody>` elements), there's no single shared root
cause here to fix.

### i18n initialization in tests
`patternfly-mocks.tsx` imports `../../src/i18n` to ensure `initReactI18next` runs in each
test file's module context — required for `useTranslation()` to work without a provider.
Components that don't import patternfly-mocks must import `../../src/i18n` (or `./i18n`)
directly (e.g. `SyncBadge.test.tsx`, `RefreshBanner.test.tsx`).

### GitHub Actions annotations
Pinned versions are the Node.js 24-native ones (verified via each action's own `action.yml`,
`using: node24`): `checkout@v6.0.2`, `setup-node@v6.4.0`, `setup-python@v6.2.0`,
`upload-artifact@v7.0.1`, `download-artifact@v8.0.1`.

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
`publish-images.yml` does **not** use GitHub Actions artifacts at all — it pushes container
images straight to Quay.io, a separate registry with its own storage, not this quota. The
actual GitHub artifact consumers, both already `retention-days: 1`:
- `ci.yml` backend coverage upload, `continue-on-error: true`
- `build-installer.yml`'s 3 binary uploads (Linux/Windows/macOS), used to hand binaries off to
  the per-platform install-test jobs and for real-hardware testing
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

**Problem 6 — Vite 8 (Oxc transform) breaks the `-- @preserve` ignore-comment mechanism from
Problem 1 — do not bump `vite`/`@vitejs/plugin-react` past major 7 yet:**
Confirmed live (PR #46, dependabot bump to `vite@8.2.1`/`@vitejs/plugin-react@6.0.5`): build and
all 1384 tests still pass, but coverage drops to 99.96%/99.78%/99.89% — exactly the 4 spots
using `/* v8 ignore next -- @preserve */`. Vite 8 replaces esbuild with Oxc for TS/JSX
transformation, and Oxc strips comments (including `@preserve` ones) before the coverage tool
ever sees them. This is an open upstream bug
([vitest#9918](https://github.com/vitest-dev/vitest/issues/9918),
[#9881](https://github.com/vitest-dev/vitest/issues/9881),
[#10628](https://github.com/vitest-dev/vitest/issues/10628)), not something fixable here.
`vite@^7.3.6`/`@vitejs/plugin-react@^5.2.0` (still esbuild-based) was verified to build clean and
hold 100% coverage — safe to take. Revisit the Vite 8 jump only once the upstream issue closes.
A second, independent Dependabot PR (#38, `vite@8.2.0` alone) reproduced the identical failure
hours after #46 was closed — closing one PR doesn't stop the next major-version proposal.
`.github/dependabot.yml` now has an `ignore` rule for `vite`/`@vitejs/plugin-react` major bumps
so this stops recurring; remove that rule when re-attempting the Vite 8 jump.

**Current CI thresholds:**
- statements: **100%** (unreachable code marked with `/* v8 ignore next -- @preserve */`)
- branches: **100%** (see Problem 2 above — the 94% figure was based on a misdiagnosis; the
  suite has since reached genuine 100% branch coverage)
- functions: **100%**
- lines: **100%**

**Test utility structure:**
Helpers live in `frontend/tests/utils/` (outside `src/`) to avoid polluting metrics.
Imports from tests: `'../../tests/utils/patternfly-mocks'` etc.

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

Same sign convention as "Transaction conventions" above (Buy = `quantity < 0`, Sell =
`quantity > 0` for assets; **inverted** for Cash Forex — acquiring = `quantity > 0` → BUY,
reducing = `quantity < 0` → SELL). Getting the Forex inversion wrong here specifically
breaks WACOP: applying the standard asset convention to JPY acquisitions would treat them
as SELL with WACOP=0 → massive fictitious PV.

### Products excluded from PV calculation
- `LIQUIDITE.*` (LIQUIDITE.EURO, LIQUIDITE.USD…) — pure cash, not a financial asset
- `instrument_type='Or physique'` (OR.PHYSIQUE, SICAV…) — special valuation logic
- `type='Frais'` and `type='Revenu'` — do not affect WACOP

### WACOP reset
When `qty_held ≤ 0.001` (float tolerance), position is closed: WACOP resets to 0 on the next buy.
The cumulative `realized_pv_total` is never reset.

## Database backup

- Endpoint `GET /api/admin/backup` → calls `pg_dump` via `subprocess` from the backend container
- Endpoint `POST /api/admin/restore` → `pg_restore --clean --if-exists --no-owner --no-privileges`
  — deliberately **no** `--single-transaction`: it would fail the whole restore on a
  non-critical `transaction_timeout` error emitted by dumps taken with a pg_dump newer than
  PostgreSQL 16 (a documented pg_restore quirk, not something to "fix" by adding the flag back)
- Format `.dump` (custom binary pg_dump, compressed)
- `backend/Containerfile` pins `postgresql-client-16` to match the server (PostgreSQL 16) — a
  mismatched client version produces dumps the server's own pg_restore can't read

**A PostgreSQL major-version bump (e.g. 16→18) is not a simple image-tag swap — do not merge
one via Dependabot without a real migration plan (tracked in #58).** Confirmed live: `postgres:18-alpine`'s
official image changed its volume mount convention (a single mount at `/var/lib/postgresql`
with a version-scoped subdirectory, instead of today's direct mount at
`/var/lib/postgresql/data`) — it refuses to even start on a **fresh, empty** volume under the
current `compose.yaml`/`compose-prod.yaml` mount layout, let alone an existing data volume.
A v16 `pg_dump` client also flatly refuses to dump a v18 server (`aborting because of server
version mismatch`), so the pinned client above must be bumped in lockstep. A dump/restore
migration path (matching-version dump, then restore into a fresh volume under the new mount
layout with a matching-or-newer client) was verified to work end-to-end on a throwaway volume
— but treat any future postgres major bump as its own migration project (compose changes +
client bump + a tested, documented upgrade path for existing installs, including real
end-users of the published installer), never a routine dependency bump.

## Security / secrets and personal data

Never commit:
- `.env` (DB passwords, API keys)
- **Real names of portfolio owners** — use "Portfolio 1", "Portfolio 2" in code, tests, and documentation
- **Real financial data** (.dump/.sql dumps, CSV exports, screenshots with amounts)
- Any personal document (analyses, specs, project notes)

The repository is intended to be made public — apply this rule from the first commit.

## Test locations and CI/CD

(Coverage *policy* is defined in "Absolute rule: 100% test coverage" above — this section
is just the map of where tests live and which CI job runs them.)

- Backend: `backend/tests/` (pytest + pytest-asyncio) — run `pytest --collect-only -q` for the current count
  - `test_transactions.py`, `test_portfolios.py`, `test_accounts_router.py` — CRUD
  - `test_pv_service.py` — WACOP and capital gains calculation
  - `test_rebalancing_service.py` — rebalancing logic (pure Python, no DB)
  - `test_price_sync.py` — Yahoo Finance price sync (httpx mocks, no DB)
  - `test_products_router.py`, `test_snapshots_router.py`, etc.
- Frontend: `frontend/src/**/*.test.{ts,tsx}` (vitest) — run `npx vitest list` for the current count
  - Test helpers: `frontend/tests/utils/` (outside `src/`)
- CI/CD: `ci.yml` job `validate` runs TypeScript + vitest + coverage (no DB); `ci.yml` job
  `integration-tests` runs full pytest with ephemeral PostgreSQL.

**Expected noise in `integration-tests`' Postgres service container**: `WARNING: no usable
system locales were found` (Alpine ships no locale data, Postgres falls back to `C`, harmless —
no locale-sensitive collation in this app's schema/queries) and `initdb: warning: enabling
"trust" authentication for local connections` (initdb's default for local Unix-socket
connections when only `POSTGRES_PASSWORD` is set; the ephemeral, network-isolated CI container
is torn down at job end, never exposed). Both come from `postgres:16-alpine`'s own `initdb`
bootstrap, not this repo's config — not something to fix.

Also expected: `ERROR: duplicate key value violates unique constraint
"uq_fiscal_carry_forward_portfolio_year"`. Postgres always logs a constraint violation at
`ERROR` level before SQLAlchemy raises `IntegrityError` to the caller — a test deliberately
exercises the fiscal carry-forward create endpoint's duplicate-entry path, which
`fiscal.py`'s `except IntegrityError` converts into a clean `400`. The database confirming a
business rule (one carry-forward entry per portfolio per tax year) is enforced, not a bug.
