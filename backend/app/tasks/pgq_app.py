"""
PgQueuer worker process (issue #66 step 3) — real handlers for 4 of the 6 registered tasks.

`refresh_prices_live`/`refresh_etf_holdings`/`refresh_macro_indicators`/
`refresh_country_performance` are cut over for real: each gets a `@pgq.schedule` handler (cron)
and a `@pgq.entrypoint` handler (on-demand, from routers or main.py's startup), both delegating
to the same unchanged `_run_X_refresh()` core and writing to `job_runs` (now the sole status
store for these 4 — their Redis dual-write was removed in this step). `compute_daily_
snapshots_all_users`/`compute_monthly_snapshots_all_users` stay log-only placeholders — the
snapshot family is still Celery-only, a later step.

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
        logger.info("pgq schedule fired: compute_daily_snapshots_all_users")

    @pgq.schedule("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON)
    async def _compute_monthly_snapshots_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: compute_monthly_snapshots_all_users")

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
