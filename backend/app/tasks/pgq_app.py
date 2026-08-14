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

PgQueuer's `SchedulerManager` computes cron next-run times by seeding `croniter` with
`datetime.now(timezone.utc)` (confirmed from `pgqueuer/core/executors.py`) — cron hour/minute
fields are always interpreted in UTC, with no timezone parameter anywhere in the API. The 5
hour-specific expressions above are hand-shifted for Europe/Paris's current CEST offset
(UTC+2); during CET (UTC+1, roughly late Oct-late Mar) these fire 1 hour earlier than the
intended Paris wall-clock time. Accepted, documented drift — not worth dynamic DST-aware
scheduling for a personal single-user app.
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
from app.tasks.etf_holdings import _run_etf_holdings_refresh
from app.tasks.macro_indicators import _run_macro_indicators_refresh
from app.tasks.prices import _run_price_refresh
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

_VALID_ENTRYPOINT_TRIGGERS = {"on_demand", "startup"}


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


def _register_schedules(pgq: PgQueuer) -> None:
    @pgq.schedule("refresh_prices_live", REFRESH_PRICES_LIVE_CRON)
    async def _refresh_prices_live_schedule(schedule: Schedule) -> None:
        await _run_tracked("refresh_prices_live", "schedule", _run_price_refresh)

    @pgq.schedule("compute_daily_snapshots_all_users", COMPUTE_DAILY_SNAPSHOTS_CRON)
    async def _compute_daily_snapshots_schedule(schedule: Schedule) -> None:
        async def _core() -> dict:
            await _compute_daily_snapshots_all_users(None)
            return {"status": "success"}
        await _run_tracked("compute_daily_snapshots_all_users", "schedule", _core)

    @pgq.schedule("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON)
    async def _compute_monthly_snapshots_schedule(schedule: Schedule) -> None:
        async def _core() -> dict:
            await _compute_monthly_snapshots_all_users(None)
            return {"status": "success"}
        await _run_tracked("compute_monthly_snapshots_all_users", "schedule", _core)

    @pgq.schedule("refresh_etf_holdings", REFRESH_ETF_HOLDINGS_CRON)
    async def _refresh_etf_holdings_schedule(schedule: Schedule) -> None:
        await _run_tracked("refresh_etf_holdings", "schedule", _run_etf_holdings_refresh)

    @pgq.schedule("refresh_macro_indicators", REFRESH_MACRO_INDICATORS_CRON)
    async def _refresh_macro_indicators_schedule(schedule: Schedule) -> None:
        await _run_tracked("refresh_macro_indicators", "schedule", _run_macro_indicators_refresh)

    @pgq.schedule("refresh_country_performance", REFRESH_COUNTRY_PERFORMANCE_CRON)
    async def _refresh_country_performance_schedule(schedule: Schedule) -> None:
        await _run_tracked("refresh_country_performance", "schedule", _run_country_performance_refresh)


def _register_entrypoints(pgq: PgQueuer) -> None:
    @pgq.entrypoint("refresh_prices_live")
    async def _refresh_prices_live_entrypoint(job: Job) -> None:
        await _run_tracked(
            "refresh_prices_live", _decode_trigger(job.payload), _run_price_refresh, pgq_job_id=job.id,
        )

    @pgq.entrypoint("refresh_etf_holdings")
    async def _refresh_etf_holdings_entrypoint(job: Job) -> None:
        await _run_tracked(
            "refresh_etf_holdings", _decode_trigger(job.payload), _run_etf_holdings_refresh, pgq_job_id=job.id,
        )

    @pgq.entrypoint("refresh_macro_indicators")
    async def _refresh_macro_indicators_entrypoint(job: Job) -> None:
        await _run_tracked(
            "refresh_macro_indicators", _decode_trigger(job.payload), _run_macro_indicators_refresh, pgq_job_id=job.id,
        )

    @pgq.entrypoint("refresh_country_performance")
    async def _refresh_country_performance_entrypoint(job: Job) -> None:
        await _run_tracked(
            "refresh_country_performance", _decode_trigger(job.payload), _run_country_performance_refresh, pgq_job_id=job.id,
        )

    @pgq.entrypoint("compute_daily_snapshots_all_users")
    async def _compute_daily_snapshots_entrypoint(job: Job) -> None:
        """On-demand payload is a plain ISO date string (or absent → today), unlike the other
        entrypoints' trigger-name payload — matches _trigger_snapshot_recompute's own encoding
        in app/api/routers/transactions.py."""
        target_date_str = job.payload.decode() if job.payload else None

        async def _core() -> dict:
            await _compute_daily_snapshots_all_users(target_date_str)
            return {"status": "success"}
        await _run_tracked(
            "compute_daily_snapshots_all_users", "on_demand", _core, pgq_job_id=job.id,
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
