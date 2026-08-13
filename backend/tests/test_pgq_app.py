"""
Tests for app/tasks/pgq_app.py's registration/main() plumbing (issue #66 step 1 POC).

Cron-string-level fidelity/timezone checks live in test_pgq_schedules.py — this file covers
`_register_schedules`/`main()` themselves. Uses PgQueuer's own `in_memory()` factory (no real
Postgres needed) for the registration checks; `main()`'s real asyncpg connection was already
verified live via a real `pgq run app.tasks.pgq_app:main` process against a throwaway
Postgres (see test_pgq_schedules.py's module docstring) — here `asyncpg.connect` is mocked
purely to cover `main()`'s own connect/close lifecycle as a unit.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pgqueuer import PgQueuer

from app.tasks.pgq_app import (
    COMPUTE_DAILY_SNAPSHOTS_CRON,
    COMPUTE_MONTHLY_SNAPSHOTS_CRON,
    REFRESH_COUNTRY_PERFORMANCE_CRON,
    REFRESH_ETF_HOLDINGS_CRON,
    REFRESH_MACRO_INDICATORS_CRON,
    REFRESH_PRICES_LIVE_CRON,
    _register_schedules,
    main,
)

EXPECTED_REGISTRATIONS = {
    ("refresh_prices_live", REFRESH_PRICES_LIVE_CRON),
    ("compute_daily_snapshots_all_users", COMPUTE_DAILY_SNAPSHOTS_CRON),
    ("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON),
    ("refresh_etf_holdings", REFRESH_ETF_HOLDINGS_CRON),
    ("refresh_macro_indicators", REFRESH_MACRO_INDICATORS_CRON),
    ("refresh_country_performance", REFRESH_COUNTRY_PERFORMANCE_CRON),
}


def test_register_schedules_registers_all_six_entrypoint_expression_pairs():
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    registered = {(str(key.entrypoint), str(key.expression)) for key in pgq.sm.registry}
    assert registered == EXPECTED_REGISTRATIONS


@pytest.mark.asyncio
async def test_every_registered_handler_executes_without_error():
    """Each handler is a real async function taking one positional (Schedule) arg — exercise
    every one so the (currently placeholder, log-only) bodies are covered."""
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    for executor in pgq.sm.registry.values():
        await executor.parameters.func(MagicMock())


@pytest.mark.asyncio
async def test_main_yields_a_pgqueuer_with_all_schedules_and_closes_the_connection():
    mock_conn = AsyncMock()
    with patch("app.tasks.pgq_app.asyncpg.connect",
               new_callable=AsyncMock, return_value=mock_conn) as mock_connect:
        async with main() as pgq:
            assert isinstance(pgq, PgQueuer)
            assert len(pgq.sm.registry) == len(EXPECTED_REGISTRATIONS)
        mock_connect.assert_awaited_once()
    mock_conn.close.assert_awaited_once()


def test_asyncpg_dsn_strips_the_sqlalchemy_driver_suffix():
    from app.tasks.pgq_app import _asyncpg_dsn

    with patch("app.tasks.pgq_app.settings") as mock_settings:
        mock_settings.database_url = "postgresql+asyncpg://pie:pw@host:5432/db"
        assert _asyncpg_dsn() == "postgresql://pie:pw@host:5432/db"
