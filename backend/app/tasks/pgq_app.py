# SPDX-License-Identifier: AGPL-3.0-or-later
"""
PgQueuer worker process (issue #66 steps 3+4) — real handlers for all 6 registered tasks.

`refresh_prices_live`/`refresh_etf_holdings`/`refresh_macro_indicators`/
`refresh_country_performance` (step 3) and `compute_daily_snapshots_all_users`/
`compute_monthly_snapshots_all_users`/`fill_missing_snapshots`/`recompute_snapshots_range`
(step 4) are all cut over for real. The first 4 and the 2 `compute_*_all_users` tasks each get
a `@pgq.schedule` handler (cron) and, where an on-demand caller exists, a `@pgq.entrypoint`
handler too — both delegating to an unchanged async core and writing to `job_runs` (the sole
status store for all 6; Celery/Redis stay installed but idle, full removal is a later step).

`compute_monthly_snapshots_all_users` has no entrypoint — zero on-demand call sites exist
anywhere in the app (confirmed by grep), only its 19:00/08:00-family Beat-equivalent cron.
`fill_missing_snapshots` has no schedule — it was never in Celery's own `beat_schedule` either,
only ever triggered from `main.py`'s startup and the admin "fill missing" endpoint.
`recompute_snapshots_range` has no schedule either (admin-triggered only) and its entrypoint
handler has a genuinely different shape from every other task registered here: see its own
docstring below and `app/tasks/snapshots.py`'s `_run_recompute_snapshots` for why its
`job_runs` row is created by its caller (`app/api/routers/admin.py`), not by this handler.

**Overlap prevention (issue #67): every schedule handler that has a matching entrypoint now
enqueues onto that SAME entrypoint instead of calling `_run_tracked` directly, and that
entrypoint is registered with `concurrency_limit=1`.** A schedule tick and an on-demand/startup
trigger of the same task used to be two fully independent dispatch paths — `concurrency_limit`
only throttles concurrent *entrypoint* executions against each other (enforced by the queue
table's dequeue query), and the scheduler's own `dispatch()` never touches that table at all
(confirmed from `pgqueuer/core/sm.py`), so a manual click could always run concurrently with a
cron tick of the same task. Routing every trigger source through the same queue+concurrency-limit
machinery closes that gap uniformly, using only officially-supported PgQueuer parameters — no new
schema, no advisory lock. It also protects a slow schedule tick from overlapping the *next* tick
of itself, a case neither `job_runs` nor a hand-rolled lock would have covered for free.
Crash recovery is inherited from PgQueuer's own heartbeat-based redelivery (default 30s
timeout, confirmed in `adapters/persistence/queries.py`'s `dequeue()`): a worker that dies
mid-handler doesn't need any bespoke staleness logic here, since a stale "picked" job is simply
re-picked without ever double-counting against `concurrency_limit` (confirmed from the same
dequeue query's `stale` handling — a recovered row transfers ownership of its already-counted
slot, it doesn't add a second one). Most of the registered tasks have both a schedule and an
entrypoint (`refresh_prices_live`/`refresh_etf_holdings`/`refresh_macro_indicators`/
`refresh_country_performance`/`refresh_sector_performance`/`refresh_equity_premium`/
`compute_daily_snapshots_all_users`) —
`compute_monthly_snapshots_all_users` has no entrypoint to unify onto (nothing to race against,
see below) and keeps calling `_run_tracked` directly from its schedule handler.

**`_decode_trigger`'s payload contract has one exception: `compute_daily_snapshots_all_users`'s
entrypoint carries an ISO-date-or-absent payload, not a trigger name — see its own docstring
below for how the new `b"schedule"` sentinel coexists with that shape.**

**`asyncio.run()`-inside-a-running-loop hazard, fixed in step 4 for the 2 snapshot cores that
needed it (`_run_fill_missing_snapshots`/`_run_recompute_snapshots` in `snapshots.py`).** Their
Celery-era bodies called `asyncio.run(...)` per phase/iteration — correct for a *synchronous*
Celery task body spinning up a fresh event loop per DB interaction, but a PgQueuer entrypoint
already runs inside the worker's own persistent event loop. Nesting `asyncio.run()` there
raises `RuntimeError: asyncio.run() cannot be called from a running event loop` — confirmed
live in Pass 2 of this step's resilience testing (real wall-clock schedule firing is the only
way to catch this; no mocked unit test exercises a real running PgQueuer loop). Both cores were
rewritten as plain `async def` using a single `create_async_engine`/`Session` for the whole
run and `await` throughout, mirroring `app/tasks/prices.py`'s `_run_price_refresh` — the
pattern every task registered here must follow, not the older Celery-task shape.

`main()` is the factory `pgq run app.tasks.pgq_app:main` expects (an async-context-manager
callable yielding a fully-registered `PgQueuer` instance) — confirmed live on both a real
Fedora podman-compose stack and a real windows-latest GitHub Actions runner (native process,
no containers).

| Task                                | Celery crontab(...) (Paris local) | Cron expression (UTC) |
|--------------------------------------|-------------------------------------|------------------------|
| refresh_prices_live                  | minute="*/15"                       | */15 * * * *           |
| compute_daily_snapshots_all_users     | hour=19, minute=0, day_of_week="1-5"| 0 17 * * 1-5           |
| compute_monthly_snapshots_all_users   | hour=8, minute=0, day_of_month=1    | 0 6 1 * *              |
| refresh_etf_holdings                 | hour=6, minute=0, day_of_week="0"   | 0 4 * * 0              |
| refresh_macro_indicators             | hour=7, minute=0                    | 0 5 * * *              |
| refresh_country_performance          | hour=7, minute=15                   | 15 5 * * *             |
| refresh_sector_performance (no Celery equivalent) | —                       | 30 5 * * *             |
| refresh_equity_premium (no Celery equivalent) | —                          | 45 5 * * *             |
| check_github_update (issue #113, no Celery equivalent) | —                  | 0 */6 * * *            |

PgQueuer's `SchedulerManager` computes cron next-run times by seeding `croniter` with
`datetime.now(timezone.utc)` (confirmed from `pgqueuer/core/executors.py`) — cron hour/minute
fields are always interpreted in UTC, with no timezone parameter anywhere in the API. Every
hour-specific expression migrated from a real Celery `beat_schedule` entry above is
hand-shifted for Europe/Paris's current CEST offset (UTC+2); during CET (UTC+1, roughly late
Oct-late Mar) these fire 1 hour earlier than the intended Paris wall-clock time. Accepted,
documented drift — not worth dynamic DST-aware scheduling for a personal single-user app.
`refresh_sector_performance` has no Celery predecessor to shift from — its `30 5 * * *` was
chosen purely to stagger 15 minutes after `refresh_country_performance`'s own Yahoo-hitting
cron, not from any intended Paris wall-clock time. `refresh_equity_premium` continues the same
stagger one slot further, `45 5 * * *`.

One more schedule, `check_github_update` (issue #113), is registered below too — unrelated to
issue #66's Celery migration above, so it's not part of the "registered tasks" framing this
docstring otherwise uses. It has no matching entrypoint (no on-demand trigger site exists) and
doesn't go through `_run_tracked`/`job_runs` — that machinery exists for user-visible "last
sync" status on real data-refresh tasks, which doesn't apply to this internal update-check
cache. Its own core (`app.tasks.github_update.run_github_update_check`) catches and logs its
own exceptions, so the schedule handler here doesn't need `_run_tracked`'s try/except either.
Hour-agnostic and not Paris-shifted like the table above — checking for a new release doesn't
depend on wall-clock time of day.
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

import asyncpg
from pgqueuer import Job, PgQueuer
from pgqueuer.domain.models import Schedule

from app.core.pgq import asyncpg_dsn as _asyncpg_dsn
from app.tasks import job_runs
from app.tasks.country_performance import _run_country_performance_refresh
from app.tasks.equity_premium import _run_equity_premium_refresh
from app.tasks.etf_holdings import _run_etf_holdings_refresh
from app.tasks.github_update import run_github_update_check
from app.tasks.macro_indicators import _run_macro_indicators_refresh
from app.tasks.prices import _run_price_refresh
from app.tasks.sector_performance import _run_sector_performance_refresh
from app.tasks.snapshots import (
    _compute_daily_snapshots_all_users,
    _compute_monthly_snapshots_all_users,
    _run_fill_missing_snapshots,
    _run_recompute_snapshots,
)

logger = logging.getLogger(__name__)

REFRESH_PRICES_LIVE_CRON = "*/15 * * * *"
COMPUTE_DAILY_SNAPSHOTS_CRON = "0 17 * * 1-5"
COMPUTE_MONTHLY_SNAPSHOTS_CRON = "0 6 1 * *"
REFRESH_ETF_HOLDINGS_CRON = "0 4 * * 0"
REFRESH_MACRO_INDICATORS_CRON = "0 5 * * *"
REFRESH_COUNTRY_PERFORMANCE_CRON = "15 5 * * *"
REFRESH_SECTOR_PERFORMANCE_CRON = "30 5 * * *"
REFRESH_EQUITY_PREMIUM_CRON = "45 5 * * *"
CHECK_GITHUB_UPDATE_CRON = "0 */6 * * *"

_VALID_ENTRYPOINT_TRIGGERS = {"on_demand", "startup", "schedule"}


def _decode_trigger(payload: bytes | None) -> str:
    """Whitelist-validated: a payload could in principle come from PgQueuer's own CLI/
    dashboard manually enqueuing a job, not just this app's own callers — trust nothing beyond
    the two values this app itself ever sends, default safely to "on_demand"."""
    if payload is None:
        return "on_demand"
    decoded = payload.decode("utf-8", errors="replace")
    return decoded if decoded in _VALID_ENTRYPOINT_TRIGGERS else "on_demand"


async def _run_tracked(
    task_name: str, trigger: str, core: Callable[[], Awaitable[dict]], pgq_job_id: int | None = None,
) -> None:
    """Shared glue for the 4 real tasks: start a job_runs row, run the unchanged
    _run_X_refresh() core, finish the row with its {status, total_tickers, succeeded,
    failed_tickers, error} result. No run_tracked()/asyncio.run() needed here — PgQueuer
    handlers are natively async, already running inside the worker's persistent event loop."""
    run_id = await job_runs.start_run(task_name, trigger, pgq_job_id=pgq_job_id)
    try:
        result = await core()
    except Exception as exc:
        await job_runs.finish_run(run_id, status="failed", error=str(exc)[:200])
        logger.exception("pgq task failed: %s", task_name)
        return
    await job_runs.finish_run(
        run_id,
        status=result["status"],
        total_steps=result.get("total_tickers", 0),
        succeeded_steps=result.get("succeeded", 0),
        failed_items=result.get("failed_tickers", []),
        error=result.get("error"),
    )


# Tasks whose schedule handler just enqueues onto their own matching concurrency_limit=1
# entrypoint (see the module docstring's "Overlap prevention" section) instead of calling
# _run_tracked directly.
_ENQUEUE_ONTO_ENTRYPOINT_SCHEDULES = (
    ("refresh_prices_live", REFRESH_PRICES_LIVE_CRON),
    ("compute_daily_snapshots_all_users", COMPUTE_DAILY_SNAPSHOTS_CRON),
    ("refresh_etf_holdings", REFRESH_ETF_HOLDINGS_CRON),
    ("refresh_macro_indicators", REFRESH_MACRO_INDICATORS_CRON),
    ("refresh_country_performance", REFRESH_COUNTRY_PERFORMANCE_CRON),
    ("refresh_sector_performance", REFRESH_SECTOR_PERFORMANCE_CRON),
    ("refresh_equity_premium", REFRESH_EQUITY_PREMIUM_CRON),
)


def _register_enqueue_schedule(pgq: PgQueuer, name: str, cron: str) -> None:
    @pgq.schedule(name, cron)
    async def _schedule(schedule: Schedule) -> None:
        await pgq.queries.enqueue(name, payload=b"schedule")


def _register_schedules(pgq: PgQueuer) -> None:
    """The tasks in _ENQUEUE_ONTO_ENTRYPOINT_SCHEDULES enqueue onto their matching entrypoint
    instead of calling _run_tracked directly — see the module docstring's "Overlap prevention"
    section for why. compute_monthly_snapshots_all_users has no entrypoint to unify onto, so it
    keeps the old direct-dispatch shape."""
    for name, cron in _ENQUEUE_ONTO_ENTRYPOINT_SCHEDULES:
        _register_enqueue_schedule(pgq, name, cron)

    @pgq.schedule("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON)
    async def _compute_monthly_snapshots_schedule(schedule: Schedule) -> None:
        async def _core() -> dict:
            await _compute_monthly_snapshots_all_users(None)
            return {"status": "success"}
        await _run_tracked("compute_monthly_snapshots_all_users", "schedule", _core)

    @pgq.schedule("check_github_update", CHECK_GITHUB_UPDATE_CRON)
    async def _check_github_update_schedule(schedule: Schedule) -> None:
        try:
            await run_github_update_check()
        except Exception:
            logger.exception("pgq task failed: check_github_update")


# (entrypoint name, core function's *module-global name*) pairs sharing the identical
# concurrency_limit=1 + _run_tracked shape. Stored as a name, not a direct function reference,
# and resolved via globals() inside the handler below — tests patch these cores by module
# attribute name (e.g. patch("app.tasks.pgq_app._run_etf_holdings_refresh")), which only takes
# effect on a lookup made *after* the patch is applied. A direct reference captured once at
# import time would keep pointing at the original, unpatched function forever.
_SIMPLE_TRACKED_ENTRYPOINTS = (
    ("refresh_prices_live", _run_price_refresh.__name__),
    ("refresh_etf_holdings", _run_etf_holdings_refresh.__name__),
    ("refresh_macro_indicators", _run_macro_indicators_refresh.__name__),
    ("refresh_country_performance", _run_country_performance_refresh.__name__),
    ("refresh_sector_performance", _run_sector_performance_refresh.__name__),
    ("refresh_equity_premium", _run_equity_premium_refresh.__name__),
)


def _register_tracked_entrypoint(pgq: PgQueuer, name: str, core_name: str) -> None:
    @pgq.entrypoint(name, concurrency_limit=1)
    async def _entrypoint(job: Job) -> None:
        core: Callable[[], Awaitable[dict]] = globals()[core_name]
        await _run_tracked(name, _decode_trigger(job.payload), core, pgq_job_id=job.id)


def _register_entrypoints(pgq: PgQueuer) -> None:
    for name, core in _SIMPLE_TRACKED_ENTRYPOINTS:
        _register_tracked_entrypoint(pgq, name, core)

    @pgq.entrypoint("compute_daily_snapshots_all_users", concurrency_limit=1)
    async def _compute_daily_snapshots_entrypoint(job: Job) -> None:
        """On-demand payload is a plain ISO date string (or absent → today) — matches
        _trigger_snapshot_recompute's own encoding in app/api/routers/transactions.py. The
        schedule handler (issue #67) now enqueues here too, using the b"schedule" sentinel
        (never a valid ISO date string) to signal "trigger=schedule, no date" without
        colliding with the on-demand shape."""
        if job.payload == b"schedule":
            trigger, target_date_str = "schedule", None
        else:
            trigger = "on_demand"
            target_date_str = job.payload.decode() if job.payload else None

        async def _core() -> dict:
            await _compute_daily_snapshots_all_users(target_date_str)
            return {"status": "success"}
        await _run_tracked(
            "compute_daily_snapshots_all_users", trigger, _core, pgq_job_id=job.id,
        )
    # No entrypoint for compute_monthly_snapshots_all_users — zero on-demand call sites.

    @pgq.entrypoint("fill_missing_snapshots")
    async def _fill_missing_snapshots_entrypoint(job: Job) -> None:
        await _run_tracked(
            "fill_missing_snapshots", _decode_trigger(job.payload), _run_fill_missing_snapshots,
            pgq_job_id=job.id,
        )

    @pgq.entrypoint("recompute_snapshots_range")
    async def _recompute_snapshots_range_entrypoint(job: Job) -> None:
        """Different shape from every other handler here: run_id's lifecycle is owned by the
        caller (app/api/routers/admin.py's POST /recompute-snapshots), not this handler — the
        client needs a pollable task_id back synchronously, before the job is even picked up,
        so start_run() already ran before this job was enqueued. This handler only ever reports
        progress onto that existing row (inside _run_recompute_snapshots itself) and owns the
        terminal finish_run call — it never calls start_run, unlike every other entrypoint's
        _run_tracked, so it can't reuse that helper."""
        payload = json.loads(job.payload)
        run_id = payload["run_id"]
        try:
            result = await _run_recompute_snapshots(payload["start"], payload["end"], run_id)
        except Exception as exc:
            await job_runs.finish_run(run_id, status="failed", error=str(exc)[:200])
            logger.exception("pgq task failed: recompute_snapshots_range")
            return
        await job_runs.finish_run(
            run_id, status="success", total_steps=result["total"], succeeded_steps=result["total"],
        )
    # No schedule for recompute_snapshots_range — admin-triggered only, never in Celery's
    # beat_schedule either.


@asynccontextmanager
async def main():
    conn = await asyncpg.connect(dsn=_asyncpg_dsn())
    try:
        pgq = PgQueuer.from_asyncpg_connection(conn)
        _register_schedules(pgq)
        _register_entrypoints(pgq)
        yield pgq
    finally:
        await conn.close()
