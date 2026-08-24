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
- For PgQueuer tasks (`app/tasks/pgq_app.py`): exercise the `@pgq.schedule`/`@pgq.entrypoint`
  handler directly via `PgQueuer.in_memory()` (see `test_pgq_app.py`) — real Postgres for
  `job_runs` writes, no reason to mock straightforward DB code

### Installer test coverage policy

The Go installer (`installer/`) has two categories of functions:

**Fully testable (must be 100% covered):** `findAvailablePort`, `readAppPort`,
`readInstalledVersion`, `updateEnvPort`, `detectComposeCmd`, `copyFile`,
`githubLatestAssetURL`, `downloadFile`,
`composePostgresMajor`, `postgresMajorMismatch` (issue #58's PostgreSQL major-version
mismatch guard — see `.claude/rules/containers-and-backup.md`'s "PostgreSQL major-version
bumps" section for what this protects against).
These pure utility functions all live in `common.go` (no build constraint — shared by
Linux/macOS, see `.claude/rules/distribution.md`'s "Shared refactor enabling this"
in the macOS section), tested in `install_test.go`/`common_test.go`.

**Intentionally untestable:** `runInstall`, `runStartWithCompose`, `forceRecreate`,
`notify`, `podmanImageExists`, `focusExistingWindow`, `openBrowser`,
`pgDataVolumeName`, `pgVersionMajor` (both exec `podman` directly, same class as
`podmanImageExists` — issue #58),
and all functions in `install_darwin.go`/
`start_darwin.go`/`main_darwin.go` (Podman `.pkg` install, Podman Machine setup,
`launchd` agent, `.app` bundle writing). These exec external programs (Podman, browser,
OS notifications) and require integration-level testing. They are covered
by the CI smoke test (`go build + ./pie-manager version`). Overall installer coverage is
necessarily low (check `go test ./... -cover` for the current figure) — expected and
acceptable for a system-interaction binary.

**Installer structure:**
- `common.go` — shared code (no build constraint): `Version`, `defaultPort`, `findAvailablePort`, `readAppPort`
- `main.go` — Linux CLI dispatcher (`//go:build linux`)
- `install.go`, `start.go`, `install_test.go` — Linux only (`//go:build linux`)
- `main_darwin.go`, `install_darwin.go`, `start_darwin.go` — macOS full installer (`//go:build darwin`)
- `launcher-native/` — separate Go module, issue #82's native-Windows-port MVP launcher (no
  Podman/containers at all — orchestrates a bundled Postgres + bundled Python backend directly).
  Own coverage policy, mirroring the pattern above: **fully testable (100% covered)** —
  `paths.go` (data-directory resolution under `%USERPROFILE%\PieManager\`, deliberately never
  under `AppData`/`LocalAppData` — confirmed live in #76/#82 that MSIX transparently redirects
  any write under `AppData`, even a fully hardcoded path, to a location wiped on uninstall),
  `ports.go` (dynamic port selection, never the #76 poc's hardcoded 5432/8123), all arg-builder
  functions in `postgres.go`/`backend.go` (`buildInitdbArgs`, `buildPostgresArgs`,
  `buildPgCtlStopArgs`, `buildCreateDbArgs`, `databaseURL`, `buildUvicornArgs`, `healthURL`,
  `buildPgqueuerArgs`),
  `runCapturedCommand`, `stopChildProcess` (renamed from `stopBackend` — issue #83's PgQueuer
  worker is a second long-lived child process it also stops, so the old backend-specific name no
  longer fit), `waitForHealth` (fully exercised via `httptest.Server` and
  real short-lived subprocesses, not just argument-building), `readPostmasterPid`, and
  `hideWindow` (`hidewindow_windows.go`/`hidewindow_other.go` — suppresses the console window
  Windows otherwise pops up per spawned subprocess for a windowless GUI app, confirmed live via
  #82's Store verification: 2 visible CMD windows, one per long-lived child process (Postgres,
  uvicorn). Sets `CreationFlags: CREATE_NO_WINDOW` (a raw `0x08000000` — not exported by Go's
  `syscall` package on Windows), not just `SysProcAttr.HideWindow` alone — `HideWindow` only
  hides a console *after* Windows allocates one, it doesn't stop the allocation, which matters
  specifically for Postgres: its Windows `EXEC_BACKEND` architecture (no `fork()`) has the
  postmaster relaunch itself via its own internal `CreateProcess` calls for every background
  worker (confirmed live: 7 separate `postgres.exe` processes for one idle server), and a
  `HideWindow`-only parent still leaves each of those internal children to allocate their own
  fresh, visible console. `CREATE_NO_WINDOW` means the parent never has a console for any child
  to inherit from in the first place. The non-Windows no-op branch needs a real statement
  (`_ = cmd`), not an empty body, or `go tool cover` reports a permanent false-negative 0.0% for
  it regardless of test coverage.
  **`startPostgres` moved into this fully-tested bucket** (was previously classified alongside
  `startBackend` as an untestable real process spawn) — it now launches `postgres.exe` directly
  instead of going through `pg_ctl start`, specifically because `pg_ctl` internally spawns
  `postgres.exe` via its own Windows `CreateProcess` call with its own new console window that
  `hideWindow()` on the `pg_ctl.exe` process has zero influence over (confirmed live: hiding
  `pg_ctl.exe`'s own window left `postgres.exe`'s separately-created console visible for the
  server's entire lifetime). Fully testable this way (100% covered) via a fake shebang-script
  executable written directly at `postgresExePath(home)`'s computed path, real short-lived
  subprocesses for the error branches (same technique as `runCapturedCommandIn`'s own
  directory-blocked-by-file tests), matching `startBackend`'s own real-process-spawn style rather
  than accepting it as untestable — the "real Windows service" alternative (which would also
  avoid the console entirely) was researched and rejected: Windows SCM's `CreateService`, and
  PostgreSQL's own `pg_ctl register` wrapper around it, both hard-require admin elevation with no
  unprivileged exception, conflicting with this launcher's no-elevation design constraint (see
  `startPostgres`'s own doc comment for sources). The former `pg_ctl -w start`'s built-in
  readiness wait is now `waitForPostgresReady` (also 100% covered) — polls
  `postgresAcceptingConnections` (the bundled `pg_isready.exe`, not a raw TCP dial: issue #83's
  live functional-pass testing found a real race where a bare `net.Dial` succeeds as soon as
  `postgres.exe`'s listener socket is bound, measurably before the server can complete a real
  connection handshake, breaking `runMigrations` with "connection was closed in the middle of
  operation" — `pg_isready` performs the same real libpq-level check `pg_ctl -w` itself relies
  on) against the selected port, detects early process exit via `cmd.Wait()` in a background
  goroutine (deliberately not `isPidRunning`, which is only a real liveness check on Windows —
  see its own doc comment — reusing it here would make the early-exit branch untestable on Linux
  for a platform-quirk reason unrelated to `cmd.Wait()` itself, which works correctly
  everywhere).
  **Issue #83 (feature parity)**: `startWorker` spawns the bundled PgQueuer worker
  (`python.exe -m pgqueuer run app.tasks.pgq_app:main`, matching `buildUvicornArgs`/
  `buildAlembicArgs`'s existing `-m modulename` style rather than a generated `Scripts/pgq.exe`
  wrapper) as a second long-lived child alongside `uvicorn` — before this, the native launcher
  ran no worker at all, a real functional gap (zero background price sync/snapshot computation)
  versus the containerized version's separate `pgq-worker` service. Needs `cmd.Dir =
  backendAppDir(home)`: pgqueuer's own factory-loading code
  (`adapters/cli/factories.py`'s `load_factory`) resolves the `module:function` string via
  `sys.path.insert(0, os.getcwd())`, not an `--app-dir`-style flag the way uvicorn's CLI
  supports — confirmed against the installed `pgqueuer==1.3.2` source, no such flag exists. No
  separate PgQueuer schema-install step needed: `alembic/versions/
  uu44vv55ww66_add_pgqueuer_schema.py` already embeds the verbatim output of `pgq sql install`
  for the pinned version, so the migrations `runMigrations` already applies on every launch
  create it. Same untestable classification as `startBackend` (real process spawn) — not pushed
  into the fully-tested bucket the way `startPostgres` was, to keep this change proportionate to
  what #83 actually needed.

  **Also #83: `startBackend`'s `cmd.Env` now prefixes `PATH` with `pgBinDir(home)`.**
  `backend/app/api/routers/admin.py`'s backup/restore endpoints shell out to bare `pg_dump`/
  `pg_restore` by name (matching the container image, where postgresql-client tooling is already
  on `PATH`) — without this, the launcher's inherited `os.Environ()` PATH has no reason to
  include the bundled `pgsql\bin`, and both endpoints would fail outright with "command not
  found" on a real install. Found by reading `admin.py` directly, not assumed — confirmed nothing
  else in this launcher previously set `PATH` at all. Not yet covered by CI (see #114).

  **Issue #119 (version-aware re-staging for pgsql/the Python interpreter, plus orphan recovery
  for the backend/worker):** `staging.go`'s `stageIfBundleChanged` replaces the old
  exe-presence-only marker with a `bundle-id.txt` manifest `build-installer.yml` computes from
  each payload's actual build inputs (the pgsql download URL; the Python version + a hash of
  `requirements.txt`) — deliberately never this app's own release `Version`, which changes every
  release regardless of whether these large (~150-250MB), rarely-changing payloads actually did.
  Fully tested (100% covered), same as the rest of `staging.go`. Re-staging on a mismatch needs
  any orphaned `postgres.exe`/`python.exe` cleared first (Windows locks a directory a running
  executable still holds open), so `recoverFromPreviousSession` (`crash_recovery.go`) now also
  runs before `stageBundledFiles`, not just before `startPostgres` — and covers the backend/worker
  too, via a self-written `backend.pid`/`worker.pid` record (`writePidRecord`/`readPidRecord`,
  fully tested) whose live process is re-verified by start time (`processStartTime`,
  `processtime_windows.go`/`processtime_other.go` — same Windows-only-real-implementation split
  as `hideWindow`) before being killed — closing the PID-reuse false-positive gap
  `isPidRunning`'s own doc comment accepts for Postgres, whose `postmaster.pid` format isn't ours
  to extend the same way.

  **Intentionally untestable** (real process spawns/OS liveness checks, same class as the
  Podman-based installer's own untestable bucket) — `runInitdb`, `stopPostgres`,
  `createAppDatabase`, `startBackend`, `startWorker`, `isPidRunning`, `recoverFromPreviousSession`,
  `recoverOrphanedPostgres`, `recoverOrphanedPythonProcess`, `killPid` (issue #119's own recovery
  functions — the pure "nothing to recover" early-return paths are tested, the real
  liveness-check/kill paths are not),
  `startupSequence` (the top-level orchestrator — every decision it makes is already covered by
  testing the pure functions it calls; the function itself is thin sequencing glue), and all of
  `main.go` (WebView2/window glue). Covered instead by the CI install+launch smoke test in
  `build-installer.yml`'s `package-native-launcher-msix` job (issue #82) — `Add-AppxPackage` +
  launch via `shell:AppsFolder`, then poll `/api/admin/version` — confirmed live: the full
  first-run bootstrap (stage bundled files, `initdb`, start postgres directly, `createdb`,
  Alembic migrations, spawn `uvicorn`) runs inside a real installed MSIX package on a real
  GitHub-hosted Windows runner, and the backend answers its health check. This also confirms
  `main.go`'s WebView2 window itself initializes there (the backend-spawning goroutine only
  runs once `webview2.NewWithOptions` succeeds). Packaging assets (`AppxManifest.xml`,
  `gen-assets/` icon renderer, `winres/` + `main_windows_amd64.syso` for the exe's own
  taskbar/titlebar icon) live directly in this module — promoted here from a throwaway
  `installer/testing/native-launcher-poc/` diagnostic (now deleted) once this exact mechanism
  was proven live.
- `testing/` — reproducible scripts to recreate the win11 libvirt/QEMU test VM from scratch on
  a fresh Fedora host (not part of the shipped product; see its own `README.md`)
- `testing/msix-loopback-poc/` — throwaway diagnostic confirming (live, on a real `windows-latest`
  GitHub Actions runner) that a full-trust MSIX-packaged WebView2 control can reach `localhost` —
  the gating question for issue #63 (Store-distributing `launcher.exe` as a free fix for #60's
  Smart App Control block); not part of the shipped product, see its own `README.md`

## Absolute rule: refactor after every change

**After every code change** — bug fix, feature, or refactor — scan both the modified code and its tests for improvement opportunities before committing:

1. **Code**: duplicated logic? extract a helper. Long function? split it. Magic constant? name it.
2. **Tests**: duplicated setup? share a fixture. Identical assertions? parameterise. Obscure name? rename.
3. **Coverage**: re-run coverage after refactor — must still be 100% statements, branches, functions, lines.

The goal is a codebase where every commit leaves the code *cleaner* than before the change, not just correct. Small refactors done continuously prevent large debt from accumulating.

## Overview

Multi-account investment portfolio tracking app (Portfolio 1 + Portfolio 2).
All data entry goes through the UI — the one deliberate exception is the bulk Excel import
(see `.claude/rules/transaction-import.md`), which itself funnels through the same
create-transaction code path as manual UI entry.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 + TypeScript + PatternFly 6 + TanStack Query v5 + Vite |
| Backend | Python FastAPI + SQLAlchemy 2.0 async + PgQueuer |
| Database | PostgreSQL 18 |
| Deployment | **Podman** Compose (never Docker) |
| Containerfiles | `Containerfile` (never `Dockerfile`) |

**Keep `@patternfly/react-icons` on the same major as `@patternfly/react-core`/`react-table`
(currently v6) — do not bump it alone.** A version mismatch reintroduces a dual-glyph icon
rendering bug (an old design + a "RH-UI" redesign overlaid, unstyled) that v6 core's own CSS
resolves by default (`.pf-v6-icon-rh-ui { display: none }`) when all three packages match. No
test catches a purely visual regression like this, so this has to stay a manual discipline.
Full v5→v6 migration history: #59.

**`recharts` is on v3** (bumped from v2, issue #3) — the only chart type it's used for is the
Dashboard's Treemap (`DashboardPage.tsx`), since PatternFly-charts/Victory has no Treemap
equivalent. v3's `Treemap` requires an index signature (`[key: string]: unknown`) on custom
data node types to pass extra fields (`pool`, `poolColor`, `pct`) through to the `content`
render prop — add it to any new `TreemapNode`-like interface, or those fields silently come
back `undefined`. Trade-off accepted: v3's internal rewrite onto `@reduxjs/toolkit` adds ~8%
to the production bundle size.

**`@patternfly/react-charts` is on v8** (bumped from v7 for the React 19 migration, issue #110/
#111) — v8 dropped the bare `'@patternfly/react-charts'` entry point entirely (it resolves to
an empty module) in favor of two explicit subpaths, `/victory` (the same Victory-based API as
v7, prop-for-prop identical for every component this app uses) and `/echarts` (a new,
unrelated rewrite this app does not use). Always import from `'@patternfly/react-charts/victory'`
— including in `vi.mock(...)` calls in tests, which must mock that exact subpath, not the bare
package name. Every `victory-*` package (`victory-chart`, `victory-zoom-container`, etc.) is
now an *optional peer* of react-charts instead of a hard dependency, so each one actually used
(directly or via a react-charts component) must be listed explicitly in `package.json` — v7
brought all of them in for free.

**`@patternfly/react-charts` v8, `@types/react`, and `@types/react-dom` also required
one real code fix** during that same React 19 bump: `useRef<T>(null)`'s type changed from
`RefObject<T>` to `RefObject<T | null>` (the old type was always inaccurate — a ref is genuinely
`null` before mount). Any prop typed `React.RefObject<HTMLDivElement>` that receives such a ref
(e.g. `IndexChart`'s `chartContainerRef`) must be typed `React.RefObject<HTMLDivElement | null>`
instead.

**`App.tsx`'s `PortfolioLayout` drives the sidebar's narrow-viewport visibility itself
(`useNarrowViewport` + a direct inline `style` override on `<PageSidebar>`) — never go back to
PatternFly's own `isManagedSidebar`/`onPageResize` mobile detection for this.** Below
PatternFly v6's `xl` breakpoint (1200px viewport width), `.pf-v6-c-page__sidebar` is off-canvas
by default (`translateX(-100%)`, `opacity: 0`) and only becomes visible via PatternFly's own
CSS when its `.pf-m-expanded` modifier class is present — which `PageSidebar` only ever applies
when its own `Page`-level `isMobile` context flag is true. That flag is computed once via a
`ResizeObserver`/`componentDidMount` check on `Page`'s own container, and this measurement
races the native WebView2 launcher's asynchronous initial window-bounds call: confirmed live
(issue #118) via DevTools that `window.innerWidth`/`clientWidth` were genuinely narrow (1028)
while the sidebar's class kept toggling between `pf-m-collapsed` and no modifier at all —
`isMobile` stayed stuck `false` and never self-corrected, since the window is never resized
again after launch. This is a real, unfixable-from-userland race in PatternFly's own detection
in this specific host environment, not something `isManagedSidebar` (tried first, and itself
initially believed to be the fix) can paper over. The actual fix: track narrowness with a plain
`window.innerWidth` check + a `resize` listener, and force the sidebar's `transform`/`opacity`
via inline `style` (highest CSS specificity — wins regardless of whatever class PatternFly's own
broken detection applies). Above 1200px, no override is applied and PatternFly's own root-level
CSS var override makes the sidebar visible unconditionally, which needs no fix and must not be
touched.

**Neither a single deferred re-check nor a bounded startup poll of `window.innerWidth` is
enough** — both confirmed live to still read wrong well past their window (500ms, then a 10s
poll, tried in that order). The native launcher does real blocking work at startup (Postgres
init, migrations, spawning the backend) before it's idle enough to process `WM_SIZE` and call
`PutBounds` with the real window bounds, and how long that takes isn't bounded (e.g. slower under
virtualization) — there's also no guarantee WebView2 dispatches a real `resize` DOM event for a
programmatic `PutBounds` call the way it does for an end-user drag-resize, so the `resize`
listener can't be trusted as a fallback for this either. `useNarrowViewport` polls
`window.innerWidth` every 500ms for the component's entire lifetime instead of any bounded
window — cheap, since React bails out of re-rendering when `setState` receives an unchanged
boolean, and the only approach that's correct regardless of how long the native launcher takes to
settle.

This bug was easy to misdiagnose as an environment/display issue rather than a real,
reproducible layout+timing bug — issue #118 went through three prior incorrect theories (QXL/
SPICE virtual GPU, RDP codec/gfx pipeline, host-compositor stale repaint) before a user's own
resolution testing (fails below ~1200px, works above it) pointed at a genuine CSS breakpoint, and
three more incorrect fix attempts after that (`isManagedSidebar`, a single deferred re-check,
then a 10s bounded poll) before the actual working fix above — always verify the specific
mechanism live in the native launcher rather than trusting that a plausible-looking timing fix
landed correctly.

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
- **SPDX license header on every source file** — every `.py`/`.ts`/`.tsx`/`.go` file must start with
  `SPDX-License-Identifier: AGPL-3.0-or-later` (right after a shebang or a Go `//go:build` block,
  otherwise as line 1). This is GNU's own recommended practice so the license travels with a file
  even if it's copied out of the repo — the root `LICENSE` file alone doesn't. Applied repo-wide
  in one pass; new files must carry it from creation.

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
Beyond a read-only `SELECT`, use an isolated throwaway container instead (see
`.claude/rules/alembic-migrations.md`). Exception: a one-time manual correction after the
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
(`docker.io/library/postgres:18-alpine`) to avoid "short-name resolution enforced" errors in
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
that creation order). **If you ever touch that retargeting SQL again**, read
`.claude/rules/alembic-migrations.md` first — a naive 3-sequential-UPDATE version silently
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
isolated) or a manually-named, differently-ported throwaway `postgres:18-alpine` container.

**Match CI's Python version (3.14) when testing locally in a container — mismatches
silently under-report coverage, they don't fail.** Verified: running the exact same tests
against the exact same DB under Python 3.12 (with 3.14 elsewhere identical — same
`coverage`/`greenlet` versions) dropped `app/api/routers/transactions.py` from 100% to 47%,
while pure-sync files were unaffected. The cause is greenlet-crossing async DB code (every
`await db.execute(...)`) not registering with coverage.py's tracer consistently across
Python minor versions.

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
is torn down at job end, never exposed). Both come from `postgres:18-alpine`'s own `initdb`
bootstrap, not this repo's config — not something to fix.

Also expected: `ERROR: duplicate key value violates unique constraint
"uq_fiscal_carry_forward_portfolio_year"`. Postgres always logs a constraint violation at
`ERROR` level before SQLAlchemy raises `IntegrityError` to the caller — a test deliberately
exercises the fiscal carry-forward create endpoint's duplicate-entry path, which
`fiscal.py`'s `except IntegrityError` converts into a clean `400`. The database confirming a
business rule (one carry-forward entry per portfolio per tax year) is enforced, not a bug.
