# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for /api/indicators/sector-performance — bar chart ranking + sector CRUD.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.sector_performance import SectorPerfConfig
from app.models.macro_indicator import MacroSeriesPrice

FIXED_TODAY = date(2026, 7, 19)
ANCHOR_TARGET = FIXED_TODAY - timedelta(days=365)


@pytest.fixture(autouse=True)
def _fixed_today():
    with patch("app.services.sector_performance_service.date") as mock_date:
        mock_date.today.return_value = FIXED_TODAY
        yield mock_date


async def _seed_series(db_session, series: str, values: dict[date, float]) -> None:
    for d, value in values.items():
        db_session.add(MacroSeriesPrice(series=series, date=d, value=value))
    await db_session.flush()


async def _seed_sector(
    db_session, code: str, label: str = "Test", index_ticker: str = "TEST", currency: str = "USD",
    index_label: str = "Test Index",
) -> None:
    db_session.add(SectorPerfConfig(
        code=code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    ))
    await db_session.flush()


# ---------------------------------------------------------------------------
# GET /sector-performance (ranking)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_sector_performance_empty_universe_returns_empty_list(client, db_session):
    r = await client.get("/api/indicators/sector-performance")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_sector_performance_computes_eur_sector(client, db_session):
    await _seed_sector(db_session, "test", "Test", "TICK", "EUR", "Test Index")
    await _seed_series(db_session, "sector_test_equity", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 120.0})

    r = await client.get("/api/indicators/sector-performance")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["code"] == "test"
    assert body[0]["perf_pct"] == pytest.approx(20.0)
    assert body[0]["latest_date"] == FIXED_TODAY.isoformat()
    assert body[0]["anchor_date"] == ANCHOR_TARGET.isoformat()
    assert body[0]["index_label"] == "Test Index"


@pytest.mark.asyncio
async def test_get_sector_performance_applies_fx_for_non_eur_sector(client, db_session):
    await _seed_sector(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    await _seed_series(db_session, "sector_or_equity", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 110.0})
    await _seed_series(db_session, "fx_usd", {ANCHOR_TARGET: 0.9, FIXED_TODAY: 0.95})

    r = await client.get("/api/indicators/sector-performance")
    assert r.status_code == 200
    body = r.json()
    expected = ((110.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert body[0]["perf_pct"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Sector CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sectors_empty(client, db_session):
    r = await client.get("/api/indicators/sector-performance/sectors")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_sectors(client, db_session):
    r = await client.post("/api/indicators/sector-performance/sectors", json={
        "code": "or", "label": "Or", "index_ticker": "GC=F", "currency": "USD", "index_label": "Or (COMEX)",
    })
    assert r.status_code == 201
    assert r.json() == {
        "code": "or", "label": "Or", "index_ticker": "GC=F", "currency": "USD", "index_label": "Or (COMEX)",
    }

    r = await client.get("/api/indicators/sector-performance/sectors")
    assert r.status_code == 200
    assert [s["code"] for s in r.json()] == ["or"]


@pytest.mark.asyncio
async def test_create_sector_invalid_code_returns_400(client, db_session):
    r = await client.post("/api/indicators/sector-performance/sectors", json={
        "code": "OR", "label": "Or", "index_ticker": "GC=F", "currency": "USD", "index_label": "Or (COMEX)",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_sector_invalid_currency_returns_400(client, db_session):
    r = await client.post("/api/indicators/sector-performance/sectors", json={
        "code": "or", "label": "Or", "index_ticker": "GC=F", "currency": "usd", "index_label": "Or (COMEX)",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_sector_duplicate_code_returns_400(client, db_session):
    await _seed_sector(db_session, "or")
    r = await client.post("/api/indicators/sector-performance/sectors", json={
        "code": "or", "label": "Or (bis)", "index_ticker": "X", "currency": "USD", "index_label": "X Index",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_sector(client, db_session):
    await _seed_sector(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    r = await client.put("/api/indicators/sector-performance/sectors/or", json={
        "label": "Or physique", "index_ticker": "GC=F", "currency": "USD", "index_label": "Gold Futures",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Or physique"
    assert body["index_label"] == "Gold Futures"


@pytest.mark.asyncio
async def test_update_sector_invalid_currency_returns_400(client, db_session):
    await _seed_sector(db_session, "or")
    r = await client.put("/api/indicators/sector-performance/sectors/or", json={
        "label": "Or", "index_ticker": "GC=F", "currency": "usd", "index_label": "Or (COMEX)",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_sector_unknown_returns_404(client, db_session):
    r = await client.put("/api/indicators/sector-performance/sectors/zz", json={
        "label": "Nowhere", "index_ticker": "X", "currency": "USD", "index_label": "X Index",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_sector(client, db_session):
    await _seed_sector(db_session, "or")
    await _seed_sector(db_session, "petrole")
    r = await client.delete("/api/indicators/sector-performance/sectors/petrole")
    assert r.status_code == 204

    r = await client.get("/api/indicators/sector-performance/sectors")
    assert [s["code"] for s in r.json()] == ["or"]


@pytest.mark.asyncio
async def test_delete_sector_unknown_returns_404(client, db_session):
    r = await client.delete("/api/indicators/sector-performance/sectors/zz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_last_sector_succeeds_no_guard(client, db_session):
    await _seed_sector(db_session, "or")
    r = await client.delete("/api/indicators/sector-performance/sectors/or")
    assert r.status_code == 204

    r = await client.get("/api/indicators/sector-performance/sectors")
    assert r.json() == []


# ---------------------------------------------------------------------------
# refresh + sync-status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_dispatches_via_pgqueuer(client, db_session):
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[11])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        r = await client.post("/api/indicators/sector-performance/refresh")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json() == {"job_id": 11, "status": "queued"}
    mock_queries.enqueue.assert_called_once_with("refresh_sector_performance", payload=b"on_demand")


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        r = await client.get("/api/indicators/sector-performance/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.started_at = datetime(2026, 7, 19, 7, 30, 0)
    fake_run.finished_at = datetime(2026, 7, 19, 7, 30, 5)
    fake_run.total_steps = 5
    fake_run.succeeded_steps = 5
    fake_run.failed_items = []

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
        r = await client.get("/api/indicators/sector-performance/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
