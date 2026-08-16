---
paths:
  - "backend/app/models/job_run.py"
  - "backend/app/tasks/job_runs.py"
  - "backend/app/core/pgq.py"
  - "backend/app/tasks/pgq_app.py"
  - "backend/app/utils/datetime_utils.py"
  - "backend/app/tasks/snapshots.py"
  - "backend/app/tasks/prices.py"
  - "backend/app/api/routers/admin.py"
  - "backend/app/main.py"
  - "frontend/src/hooks/useAutoRefresh.ts"
  - "compose.yaml"
  - "compose-prod.yaml"
  - "installer/assets/compose-prod.yaml"
  - "installer/common.go"
---

## Background job processing — PgQueuer (issue #66, Celery/Redis fully removed)

This app is single-user; a distributed-worker model (separate broker + worker process class) was
more machinery than it needed. Issue #66 migrated all 6 periodic/on-demand background tasks off
Celery/Redis onto PgQueuer **incrementally**, one small, independently live-verified step at a
time (steps 1+3: `refresh_prices_live`/`refresh_etf_holdings`/`refresh_macro_indicators`/
`refresh_country_performance`; step 4: `compute_daily_snapshots_all_users`/
`compute_monthly_snapshots_all_users`/`fill_missing_snapshots`/`recompute_snapshots_range`; step
5: removed Celery/Redis/the `worker` container and `celery_app.py` entirely, since nothing used
them anymore by that point). `pgq-worker` is now the only worker process/container in this app.

**`job_runs` table** (`app/models/job_run.py`, `app/tasks/job_runs.py`) replaces Redis-based
sync-status keys *and* Celery's `AsyncResult` for every task: one row per **execution attempt**
(schedule/on-demand/startup-triggered), not per logical job — `pgq_job_id` is deliberately not
unique (see below). Two mapping functions produce two different JSON shapes for two different
consumers: `to_sync_status_dict()` (paired with `get_latest(task_name)`) reproduces what the
old Redis-backed `/sync-status` endpoints already returned; `to_task_status_dict()` (paired with
`get_by_id(run_id)`) reproduces Celery `AsyncResult`'s `PENDING`/`PROGRESS`/`SUCCESS`/`FAILURE`
vocabulary for `recompute_snapshots_range`'s admin progress-bar polling
(`GET /api/admin/task/{task_id}`) — the frontend's `TaskStatus.state` TS type is a closed union
over exactly those 4 strings, so an unmapped state renders a blank result box. Neither cutover
needed frontend changes — both mapping functions were built to match an existing JSON contract,
not the other way around.

**`app/core/pgq.py`** holds the web process's own asyncpg pool + `Queries` instance (FastAPI
`Depends(get_pgq_queries)`, mirrors the existing `get_db` idiom) — routers enqueue on-demand
jobs through this, independent of whether `pgq-worker` is currently up. Confirmed live: an
on-demand POST still returns 200 and the job sits queued even with `pgq-worker` killed.

**`app/tasks/pgq_app.py`** is the worker process itself (`pgq run app.tasks.pgq_app:main`, new
`pgq-worker` compose service) — registers both a `@pgq.schedule` (cron) and a `@pgq.entrypoint`
(on-demand/startup) handler per migrated task, both delegating to the same unchanged
`_run_X_refresh()` core the old Celery task called.

**Critical: PgQueuer's scheduler computes cron next-run times in UTC only** — no timezone
parameter exists anywhere in the library (confirmed from source). The 6 cron constants in
`pgq_app.py` are UTC-shifted from Celery `beat_schedule`'s Paris-local hour numbers (e.g. daily
snapshots' intended 19:00 Paris becomes `0 17 * * 1-5` for CEST) — a ±1h drift across the DST
transition is accepted rather than building timezone-aware scheduling for a personal app.
**Changing a cron expression in code does not update or clean up the old schedule row**:
PgQueuer's bootstrap does `INSERT ... ON CONFLICT (entrypoint, expression) DO NOTHING`, so a
changed expression creates a second row that coexists with (but no longer fires alongside) the
old one — `clean_old=True` on `@pgq.schedule` would delete it, not used here since no schedule's
cron value currently changes at runtime. Confirmed live via a temporary fast cron during
resilience testing.

**`job_runs.pgq_job_id` has no unique constraint — a real bug found via live kill/restart
testing, not a design choice made upfront.** PgQueuer redelivers a job stuck `picked` (worker
killed mid-handler) to the *same* `job.id` once `pgq-worker` restarts; the entrypoint handler's
`start_run(..., pgq_job_id=job.id)` call then runs a second time for that job_id. A unique index
here (added in migration `tt33uu44vv55`) turned this ordinary, expected redelivery into an
unhandled `IntegrityError` that crashed the job — confirmed live, fixed by dropping the index in
migration `vv55ww66xx77`. Several `job_runs` rows can legitimately share one `pgq_job_id`; a row
stuck `running` forever with no `finished_at` is the accepted, documented shape of an
interrupted attempt (no automatic orphan detection — the same gap Celery had, not a new
regression).

**Every `DateTime` column in this app stores naive UTC — always serialize it through
`app/utils/datetime_utils.py`'s `to_utc_iso()`, never bare `.isoformat()`.** Found live
(issue #72): `job_runs.started_at`/`finished_at` and `portfolios.created_at` were serialized
with plain `.isoformat()`, which on a naive datetime omits the UTC offset entirely. JavaScript's
`Date` constructor then parses an offset-less string as *local* time, not UTC — every "dernière
synchro" badge across the app (price/ETF/macro/country-performance sync status all flow through
`to_sync_status_dict`) displayed a time off by exactly the browser's UTC offset (2h in CEST, 1h
in CET). `to_utc_iso()` attaches an explicit `+00:00` before serializing; use it at every point a
naive-UTC datetime crosses the API boundary, including any new one added later.

**`pgq-worker` compose service**: same image as `backend`, `command: pgq run
app.tasks.pgq_app:main`, depends on `backend` — no Redis env vars, since Celery/Redis were
removed entirely in issue #66's final step. Present in `compose.yaml` and `compose-prod.yaml`;
also present in `installer/assets/compose-prod.yaml`, but that copy is generated at build time
from the root file, not committed (see `.gitignore`) — no separate edit needed there.

**Neither `backend` nor `pgq-worker` uses `depends_on: postgres: condition: service_healthy`
in either compose file — deliberately removed, not an oversight.** That condition was present
from v1.4.0's release through a first attempted fix, and both times `build-installer.yml`'s
`test-linux-install` job hung indefinitely (confirmed live via `gh run cancel` + `gh run view
--job <id> --log`): the hang landed immediately after postgres's digest-pinned image finished
pulling, with zero further output, on GitHub's `ubuntu-latest` runner's combination of podman
4.9.3 (Ubuntu-bundled) + a freshly pip-installed podman-compose 1.6.0. The first fix attempt
(only removing `pgq-worker`'s health condition, in case 2 services concurrently polling the
same condition was the trigger) did **not** resolve it — the hang recurred at the identical
point with `backend` alone still using the condition, disproving that hypothesis. The real
cause is `condition: service_healthy` itself hanging in this specific podman-compose/podman
version combination, regardless of which service uses it or how many do. Fix: both services
now use a plain, unconditioned `depends_on` list; startup-ordering safety relies instead on
`restart: unless-stopped` (a service that starts before its dependency is ready simply crashes
and restarts, already proven resilient throughout this whole migration) plus HAProxy's own
independent active health-check (`/api/admin/health` every 2s, see the root `CLAUDE.md`'s
"Health check endpoint" section) as the real user-facing gate before traffic is routed. `installer/common.go`'s
`forceRecreate()` also had its `up` step's stdout changed from `io.Discard` to `os.Stdout` —
the original hang was invisible in CI logs specifically because that output was discarded,
hiding every podman-compose message after the last image pull. Filed upstream as
**containers/podman-compose#1541** (full repro data + workaround) — check whether it's been
fixed/responded to on a podman-compose version this project would actually adopt before ever
re-adding `condition: service_healthy` anywhere in this repo.

**Never nest `asyncio.run()` inside a PgQueuer handler — it runs inside the worker's own
persistent event loop already.** The Celery-era `fill_missing_snapshots`/
`recompute_snapshots_range` task bodies called `asyncio.run(...)` per phase/iteration (correct
for a *synchronous* Celery task spinning up a fresh loop per DB interaction) — reusing that
shape unchanged inside a `@pgq.entrypoint` raises `RuntimeError: asyncio.run() cannot be called
from a running event loop`. Confirmed live in step 4's Pass 2 (real wall-clock schedule
firing) — no mocked unit test exercises a real running PgQueuer loop, so this class of bug only
surfaces there. Fixed by rewriting both cores as plain `async def` with a single
`create_async_engine`/`Session` for the whole run and `await` throughout
(`_run_fill_missing_snapshots`/`_run_recompute_snapshots` in `snapshots.py`), matching
`app/tasks/prices.py`'s `_run_price_refresh` — every task registered in `pgq_app.py` must
follow this shape, never the older Celery-task one.

**`recompute_snapshots_range` has a different `job_runs` lifecycle from every other task,
because its client needs a pollable `task_id` back synchronously, before the job is even
picked up.** Every other task's `job_runs` row is created by its own PgQueuer handler once the
worker actually starts processing it (via `start_run` inside `_run_tracked`) — fine, since
nothing polls those rows by identity, only "give me the latest run for this task_name."
`recompute_snapshots_range` is different: `admin.py`'s `POST /recompute-snapshots` calls
`job_runs.start_run(...)` itself *before* enqueueing, embeds the resulting `run_id` in the
PgQueuer payload (JSON: `{"start", "end", "run_id"}`), and returns `{"task_id": str(run_id)}`
immediately — so `GET /api/admin/task/{task_id}` has something real to poll even while the job
is still queued (mapped to `PENDING` via `to_task_status_dict`'s `total_steps==0` branch). The
entrypoint handler in `pgq_app.py` never calls `start_run` for this task — it only reports
progress onto the given row and owns the terminal `finish_run` call directly, so it can't reuse
the shared `_run_tracked` helper. Confirmed live: killing `pgq-worker` mid-run leaves the row
`PENDING`/`running` (not an error), and after PgQueuer's own heartbeat-staleness window elapses
and redelivers the job to the same `job.id`, the handler correctly resumes against the *same*
`run_id` rather than creating a duplicate row.

Tracking: #66 (main migration, complete). Related: #67 (considering `concurrency_limit=1` to
prevent overlapping runs of the same sync task — separate, not yet implemented).

## Daily snapshot logic

- Auto-generated at **app startup** (via PgQueuer entrypoint `fill_missing_snapshots` — see
  "Background job processing" above)
- Triggered at **midnight** when the app is open (frontend detection, `useAutoRefresh`)
- Excludes **weekends** (filter `EXTRACT(DOW) NOT IN (0, 6)`)
- Based on prices from `asset_prices` (yfinance + manual)
- The **Admin** page allows forced regeneration over a custom date range

## Yahoo Finance price sync

- Every 15 min via PgQueuer's own cron scheduler (`pgq-worker`, `refresh_prices_live`), plus
  once at **backend startup** (`main.py` lifespan does
  `await get_pgq_queries().enqueue("refresh_prices_live", payload=b"startup")` alongside 4
  other startup enqueues including `fill_missing_snapshots`, each in its own independent
  try/except so one failing doesn't block the others) — see "Background job processing" above
  for the full migration context
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

