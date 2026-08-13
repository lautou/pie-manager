"""
PgQueuer viability POC (issue #66 step 1) — NOT wired into production yet.

Registers the 6 periodic schedules as `@pgq.schedule` cron translations of `celery_app.py`'s
`beat_schedule` (see the table below), plus a `main()` factory in the exact shape `pgq run`
expects (`pgq run app.tasks.pgq_app:main` — an async-context-manager-returning callable
yielding a fully-registered `PgQueuer` instance, confirmed against pgqueuer's own
`adapters/cli/factories.py`/`supervisor.py`).

This module exists purely to empirically prove the architecture (schema install, cron
fidelity, timezone behavior — see the Step 1 plan's "Resolve the timezone gap" section) before
committing to the real cutover in a later step. The 6 handlers below are placeholders that only
log that they fired; wiring them to the real `_run_X_refresh()`/`_compute_X` logic, and
actually invoking this module from compose.yaml's `worker` service, is explicitly out of scope
here.

| Task                                | Celery crontab(...)                          | Cron expression |
|--------------------------------------|-----------------------------------------------|------------------|
| refresh_prices_live                  | minute="*/15"                                  | */15 * * * *     |
| compute_daily_snapshots_all_users     | hour=19, minute=0, day_of_week="1-5"          | 0 19 * * 1-5     |
| compute_monthly_snapshots_all_users   | hour=8, minute=0, day_of_month=1              | 0 8 1 * *        |
| refresh_etf_holdings                 | hour=6, minute=0, day_of_week="0"              | 0 6 * * 0        |
| refresh_macro_indicators             | hour=7, minute=0                               | 0 7 * * *        |
| refresh_country_performance          | hour=7, minute=15                              | 15 7 * * *       |
"""

import logging
from contextlib import asynccontextmanager

import asyncpg
from pgqueuer import PgQueuer
from pgqueuer.domain.models import Schedule

from app.core.config import settings

logger = logging.getLogger(__name__)

REFRESH_PRICES_LIVE_CRON = "*/15 * * * *"
COMPUTE_DAILY_SNAPSHOTS_CRON = "0 19 * * 1-5"
COMPUTE_MONTHLY_SNAPSHOTS_CRON = "0 8 1 * *"
REFRESH_ETF_HOLDINGS_CRON = "0 6 * * 0"
REFRESH_MACRO_INDICATORS_CRON = "0 7 * * *"
REFRESH_COUNTRY_PERFORMANCE_CRON = "15 7 * * *"


def _asyncpg_dsn() -> str:
    """asyncpg.connect() wants a plain postgresql:// DSN, not SQLAlchemy's +asyncpg driver
    suffix — same conversion already used by admin.py's _pg_conn_args() for pg_dump/pg_restore."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _register_schedules(pgq: PgQueuer) -> None:
    @pgq.schedule("refresh_prices_live", REFRESH_PRICES_LIVE_CRON)
    async def _refresh_prices_live_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: refresh_prices_live")

    @pgq.schedule("compute_daily_snapshots_all_users", COMPUTE_DAILY_SNAPSHOTS_CRON)
    async def _compute_daily_snapshots_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: compute_daily_snapshots_all_users")

    @pgq.schedule("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON)
    async def _compute_monthly_snapshots_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: compute_monthly_snapshots_all_users")

    @pgq.schedule("refresh_etf_holdings", REFRESH_ETF_HOLDINGS_CRON)
    async def _refresh_etf_holdings_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: refresh_etf_holdings")

    @pgq.schedule("refresh_macro_indicators", REFRESH_MACRO_INDICATORS_CRON)
    async def _refresh_macro_indicators_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: refresh_macro_indicators")

    @pgq.schedule("refresh_country_performance", REFRESH_COUNTRY_PERFORMANCE_CRON)
    async def _refresh_country_performance_schedule(schedule: Schedule) -> None:
        logger.info("pgq schedule fired: refresh_country_performance")


@asynccontextmanager
async def main():
    conn = await asyncpg.connect(dsn=_asyncpg_dsn())
    try:
        pgq = PgQueuer.from_asyncpg_connection(conn)
        _register_schedules(pgq)
        yield pgq
    finally:
        await conn.close()
