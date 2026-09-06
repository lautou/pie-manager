# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for /api/indicators/bond-performance — bar chart ranking + bond-market CRUD.
Mirrors test_sector_performance_router.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.bond_performance import BondPerfConfig
from tests.helpers import FIXED_TODAY, ANCHOR_TARGET, make_fixed_today_fixture, seed_series_dict as _seed_series

_fixed_today = make_fixed_today_fixture("app.services.bond_performance_service")


async def _seed_country(
    db_session, code: str, label: str = "Test", index_ticker: str = "TEST", currency: str = "USD",
    index_label: str = "Test Bond",
) -> None:
    db_session.add(BondPerfConfig(
        code=code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    ))
    await db_session.flush()


# ---------------------------------------------------------------------------
# GET /bond-performance (ranking)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_bond_performance_empty_universe_returns_empty_list(client, db_session):
    r = await client.get("/api/indicators/bond-performance")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_bond_performance_computes_eur_country(client, db_session):
    await _seed_country(db_session, "fr", "France", "IFRB.AS", "EUR", "Obligations françaises")
    await _seed_series(db_session, "bond_fr_govt", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 108.0})

    r = await client.get("/api/indicators/bond-performance")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["code"] == "fr"
    assert body[0]["perf_pct"] == pytest.approx(8.0)
    assert body[0]["latest_date"] == FIXED_TODAY.isoformat()
    assert body[0]["anchor_date"] == ANCHOR_TARGET.isoformat()
    assert body[0]["index_label"] == "Obligations françaises"


@pytest.mark.asyncio
async def test_get_bond_performance_applies_fx_for_non_eur_country(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    await _seed_series(db_session, "bond_us_govt", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 95.0})
    await _seed_series(db_session, "fx_usd", {ANCHOR_TARGET: 0.9, FIXED_TODAY: 0.95})

    r = await client.get("/api/indicators/bond-performance")
    assert r.status_code == 200
    body = r.json()
    expected = ((95.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert body[0]["perf_pct"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Bond-market CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_bond_countries_empty(client, db_session):
    r = await client.get("/api/indicators/bond-performance/countries")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_bond_countries(client, db_session):
    r = await client.post("/api/indicators/bond-performance/countries", json={
        "code": "us", "label": "États-Unis", "index_ticker": "IEF", "currency": "USD",
        "index_label": "Trésor américain",
    })
    assert r.status_code == 201
    assert r.json() == {
        "code": "us", "label": "États-Unis", "index_ticker": "IEF", "currency": "USD",
        "index_label": "Trésor américain",
    }

    r = await client.get("/api/indicators/bond-performance/countries")
    assert r.status_code == 200
    assert [c["code"] for c in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_create_bond_country_invalid_code_returns_400(client, db_session):
    r = await client.post("/api/indicators/bond-performance/countries", json={
        "code": "US", "label": "États-Unis", "index_ticker": "IEF", "currency": "USD",
        "index_label": "Trésor américain",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_bond_country_invalid_currency_returns_400(client, db_session):
    r = await client.post("/api/indicators/bond-performance/countries", json={
        "code": "us", "label": "États-Unis", "index_ticker": "IEF", "currency": "usd",
        "index_label": "Trésor américain",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_bond_country_duplicate_code_returns_400(client, db_session):
    await _seed_country(db_session, "us")
    r = await client.post("/api/indicators/bond-performance/countries", json={
        "code": "us", "label": "USA (bis)", "index_ticker": "X", "currency": "USD", "index_label": "X",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_bond_country(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    r = await client.put("/api/indicators/bond-performance/countries/us", json={
        "label": "USA", "index_ticker": "IEF", "currency": "USD", "index_label": "US Treasury 7-10y",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "USA"
    assert body["index_label"] == "US Treasury 7-10y"


@pytest.mark.asyncio
async def test_update_bond_country_invalid_currency_returns_400(client, db_session):
    await _seed_country(db_session, "us")
    r = await client.put("/api/indicators/bond-performance/countries/us", json={
        "label": "Test", "index_ticker": "TEST", "currency": "usd", "index_label": "Test Bond",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_bond_country_unknown_returns_404(client, db_session):
    r = await client.put("/api/indicators/bond-performance/countries/zz", json={
        "label": "Nowhere", "index_ticker": "X", "currency": "USD", "index_label": "X",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_bond_country(client, db_session):
    await _seed_country(db_session, "us")
    await _seed_country(db_session, "fr")
    r = await client.delete("/api/indicators/bond-performance/countries/fr")
    assert r.status_code == 204

    r = await client.get("/api/indicators/bond-performance/countries")
    assert [c["code"] for c in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_delete_bond_country_unknown_returns_404(client, db_session):
    r = await client.delete("/api/indicators/bond-performance/countries/zz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_last_bond_country_succeeds_no_guard(client, db_session):
    await _seed_country(db_session, "us")
    r = await client.delete("/api/indicators/bond-performance/countries/us")
    assert r.status_code == 204

    r = await client.get("/api/indicators/bond-performance/countries")
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
        r = await client.post("/api/indicators/bond-performance/refresh")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json() == {"job_id": 11, "status": "queued"}
    mock_queries.enqueue.assert_called_once_with("refresh_bond_performance", payload=b"on_demand")


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        r = await client.get("/api/indicators/bond-performance/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.started_at = datetime(2026, 9, 6, 6, 0, 0)
    fake_run.finished_at = datetime(2026, 9, 6, 6, 0, 5)
    fake_run.total_steps = 5
    fake_run.succeeded_steps = 5
    fake_run.failed_items = []

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
        r = await client.get("/api/indicators/bond-performance/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
