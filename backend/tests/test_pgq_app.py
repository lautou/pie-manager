"""
Tests for app/tasks/pgq_app.py — schedule/entrypoint registration, the shared _run_tracked/
_decode_trigger glue, the 4 real handlers, and main()'s connect/close lifecycle (issue #66
step 3).

Cron-string-level fidelity/timezone checks live in test_pgq_schedules.py. main()'s real
asyncpg connection was already verified live via a real `pgq run app.tasks.pgq_app:main`
process against a throwaway Postgres and a real windows-latest GitHub Actions runner — here
asyncpg.connect is mocked purely to cover main()'s own connect/close lifecycle as a unit.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pgqueuer import PgQueuer

from app.tasks import job_runs
from app.tasks.pgq_app import (
    COMPUTE_DAILY_SNAPSHOTS_CRON,
    COMPUTE_MONTHLY_SNAPSHOTS_CRON,
    REFRESH_COUNTRY_PERFORMANCE_CRON,
    REFRESH_ETF_HOLDINGS_CRON,
    REFRESH_MACRO_INDICATORS_CRON,
    REFRESH_PRICES_LIVE_CRON,
    _decode_trigger,
    _register_entrypoints,
    _register_schedules,
    _run_tracked,
    main,
)

EXPECTED_SCHEDULE_REGISTRATIONS = {
    ("refresh_prices_live", REFRESH_PRICES_LIVE_CRON),
    ("compute_daily_snapshots_all_users", COMPUTE_DAILY_SNAPSHOTS_CRON),
    ("compute_monthly_snapshots_all_users", COMPUTE_MONTHLY_SNAPSHOTS_CRON),
    ("refresh_etf_holdings", REFRESH_ETF_HOLDINGS_CRON),
    ("refresh_macro_indicators", REFRESH_MACRO_INDICATORS_CRON),
    ("refresh_country_performance", REFRESH_COUNTRY_PERFORMANCE_CRON),
}

EXPECTED_ENTRYPOINTS = {
    "refresh_prices_live", "refresh_etf_holdings",
    "refresh_macro_indicators", "refresh_country_performance",
}


# ---------------------------------------------------------------------------
# Registration shape
# ---------------------------------------------------------------------------

def test_register_schedules_registers_all_six_entrypoint_expression_pairs():
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    registered = {(str(key.entrypoint), str(key.expression)) for key in pgq.sm.registry}
    assert registered == EXPECTED_SCHEDULE_REGISTRATIONS


def test_register_entrypoints_registers_exactly_the_4_cutover_tasks():
    """The 2 snapshot tasks don't get an @pgq.entrypoint this step — still Celery-only."""
    pgq = PgQueuer.in_memory()
    _register_entrypoints(pgq)
    assert set(pgq.qm.entrypoint_registry.keys()) == EXPECTED_ENTRYPOINTS


@pytest.mark.asyncio
async def test_snapshot_placeholder_schedules_still_execute_without_error():
    """The 2 snapshot tasks stay log-only placeholders this step — still safe to call."""
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    placeholder_entrypoints = {"compute_daily_snapshots_all_users", "compute_monthly_snapshots_all_users"}
    for key, executor in pgq.sm.registry.items():
        if key.entrypoint in placeholder_entrypoints:
            await executor.parameters.func(MagicMock())


@pytest.mark.asyncio
async def test_main_yields_a_pgqueuer_with_schedules_and_entrypoints_and_closes_the_connection():
    mock_conn = AsyncMock()
    with patch("app.tasks.pgq_app.asyncpg.connect",
               new_callable=AsyncMock, return_value=mock_conn) as mock_connect:
        async with main() as pgq:
            assert isinstance(pgq, PgQueuer)
            assert len(pgq.sm.registry) == len(EXPECTED_SCHEDULE_REGISTRATIONS)
            assert set(pgq.qm.entrypoint_registry.keys()) == EXPECTED_ENTRYPOINTS
        mock_connect.assert_awaited_once()
    mock_conn.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# _decode_trigger
# ---------------------------------------------------------------------------

def test_decode_trigger_none_payload_is_on_demand():
    assert _decode_trigger(None) == "on_demand"


def test_decode_trigger_startup_payload():
    assert _decode_trigger(b"startup") == "startup"


def test_decode_trigger_on_demand_payload():
    assert _decode_trigger(b"on_demand") == "on_demand"


def test_decode_trigger_unknown_payload_falls_back_to_on_demand():
    """Whitelist-validated: a payload PgQueuer's own CLI/dashboard could manually enqueue
    shouldn't be trusted blindly."""
    assert _decode_trigger(b"something-unexpected") == "on_demand"


# ---------------------------------------------------------------------------
# _run_tracked — the shared glue behind all 4 real tasks' schedule/entrypoint handlers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_tracked_success_writes_job_runs_row(engine):
    async def _core():
        return {"status": "success", "total_tickers": 3, "succeeded": 3, "failed_tickers": []}

    await _run_tracked("refresh_prices_live", "schedule", _core)

    run = await job_runs.get_latest("refresh_prices_live")
    assert run.status == "success"
    assert run.trigger == "schedule"
    assert run.total_steps == 3
    assert run.succeeded_steps == 3
    assert run.pgq_job_id is None


@pytest.mark.asyncio
async def test_run_tracked_with_pgq_job_id_records_it(engine):
    async def _core():
        return {"status": "success", "total_tickers": 0, "succeeded": 0, "failed_tickers": []}

    await _run_tracked("refresh_etf_holdings", "on_demand", _core, pgq_job_id=777)

    run = await job_runs.get_latest("refresh_etf_holdings")
    assert run.pgq_job_id == 777
    assert run.trigger == "on_demand"


@pytest.mark.asyncio
async def test_run_tracked_core_raises_records_failed_row(engine):
    async def _core():
        raise RuntimeError("boom")

    await _run_tracked("refresh_macro_indicators", "startup", _core)

    run = await job_runs.get_latest("refresh_macro_indicators")
    assert run.status == "failed"
    assert run.error == "boom"


# ---------------------------------------------------------------------------
# The 4 real handlers, exercised via their own registry — success + failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_prices_live_schedule_handler_calls_the_real_core(engine):
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    key = next(k for k in pgq.sm.registry if k.entrypoint == "refresh_prices_live")
    with patch("app.tasks.pgq_app._run_price_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 1, "succeeded": 1, "failed_tickers": []}):
        await pgq.sm.registry[key].parameters.func(MagicMock())

    run = await job_runs.get_latest("refresh_prices_live")
    assert run.status == "success"
    assert run.trigger == "schedule"
    assert run.pgq_job_id is None


@pytest.mark.asyncio
async def test_refresh_prices_live_entrypoint_handler_calls_the_real_core(engine):
    pgq = PgQueuer.in_memory()
    _register_entrypoints(pgq)
    handler = pgq.qm.entrypoint_registry["refresh_prices_live"].parameters.func
    fake_job = MagicMock(id=321, payload=b"on_demand")
    with patch("app.tasks.pgq_app._run_price_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 2, "succeeded": 2, "failed_tickers": []}):
        await handler(fake_job)

    run = await job_runs.get_latest("refresh_prices_live")
    assert run.status == "success"
    assert run.trigger == "on_demand"
    assert run.pgq_job_id == 321


@pytest.mark.asyncio
async def test_refresh_etf_holdings_schedule_handler_calls_the_real_core(engine):
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    key = next(k for k in pgq.sm.registry if k.entrypoint == "refresh_etf_holdings")
    with patch("app.tasks.pgq_app._run_etf_holdings_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 1, "succeeded": 1, "failed_tickers": []}):
        await pgq.sm.registry[key].parameters.func(MagicMock())

    run = await job_runs.get_latest("refresh_etf_holdings")
    assert run.status == "success"
    assert run.trigger == "schedule"
    assert run.pgq_job_id is None


@pytest.mark.asyncio
async def test_refresh_macro_indicators_schedule_handler_calls_the_real_core(engine):
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    key = next(k for k in pgq.sm.registry if k.entrypoint == "refresh_macro_indicators")
    with patch("app.tasks.pgq_app._run_macro_indicators_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 4, "succeeded": 4, "failed_tickers": []}):
        await pgq.sm.registry[key].parameters.func(MagicMock())

    run = await job_runs.get_latest("refresh_macro_indicators")
    assert run.status == "success"
    assert run.trigger == "schedule"
    assert run.pgq_job_id is None


@pytest.mark.asyncio
async def test_refresh_country_performance_schedule_handler_calls_the_real_core(engine):
    pgq = PgQueuer.in_memory()
    _register_schedules(pgq)
    key = next(k for k in pgq.sm.registry if k.entrypoint == "refresh_country_performance")
    with patch("app.tasks.pgq_app._run_country_performance_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 5, "succeeded": 5, "failed_tickers": []}):
        await pgq.sm.registry[key].parameters.func(MagicMock())

    run = await job_runs.get_latest("refresh_country_performance")
    assert run.status == "success"
    assert run.trigger == "schedule"
    assert run.pgq_job_id is None


@pytest.mark.asyncio
async def test_refresh_etf_holdings_entrypoint_handler_decodes_trigger_and_job_id(engine):
    pgq = PgQueuer.in_memory()
    _register_entrypoints(pgq)
    handler = pgq.qm.entrypoint_registry["refresh_etf_holdings"].parameters.func
    fake_job = MagicMock(id=555, payload=b"on_demand")
    with patch("app.tasks.pgq_app._run_etf_holdings_refresh", new_callable=AsyncMock,
               return_value={"status": "partial", "total_tickers": 2, "succeeded": 1, "failed_tickers": ["X"]}):
        await handler(fake_job)

    run = await job_runs.get_latest("refresh_etf_holdings")
    assert run.status == "partial"
    assert run.trigger == "on_demand"
    assert run.pgq_job_id == 555


@pytest.mark.asyncio
async def test_refresh_macro_indicators_entrypoint_handler_startup_trigger(engine):
    pgq = PgQueuer.in_memory()
    _register_entrypoints(pgq)
    handler = pgq.qm.entrypoint_registry["refresh_macro_indicators"].parameters.func
    fake_job = MagicMock(id=1, payload=b"startup")
    with patch("app.tasks.pgq_app._run_macro_indicators_refresh", new_callable=AsyncMock,
               return_value={"status": "success", "total_tickers": 4, "succeeded": 4, "failed_tickers": []}):
        await handler(fake_job)

    run = await job_runs.get_latest("refresh_macro_indicators")
    assert run.trigger == "startup"
    assert run.pgq_job_id == 1


@pytest.mark.asyncio
async def test_refresh_country_performance_entrypoint_handler_failure(engine):
    pgq = PgQueuer.in_memory()
    _register_entrypoints(pgq)
    handler = pgq.qm.entrypoint_registry["refresh_country_performance"].parameters.func
    fake_job = MagicMock(id=2, payload=None)
    with patch("app.tasks.pgq_app._run_country_performance_refresh",
               new_callable=AsyncMock, side_effect=RuntimeError("network down")):
        await handler(fake_job)

    run = await job_runs.get_latest("refresh_country_performance")
    assert run.status == "failed"
    assert run.error == "network down"
    assert run.trigger == "on_demand"
