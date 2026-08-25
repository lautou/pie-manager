# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for /api/indicators/country-performance — Top-N ranking + country CRUD.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.country_performance import CountryPerfConfig
from tests.helpers import FIXED_TODAY, ANCHOR_TARGET, make_fixed_today_fixture, seed_series_dict as _seed_series

_fixed_today = make_fixed_today_fixture("app.services.country_performance_service")


async def _seed_country(
    db_session, code: str, label: str = "Test", index_ticker: str = "^TEST", currency: str = "EUR",
    index_label: str = "Test Index",
) -> None:
    db_session.add(CountryPerfConfig(
        code=code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    ))
    await db_session.flush()


# ---------------------------------------------------------------------------
# GET /country-performance (ranking)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_country_performance_empty_universe_returns_empty_list(client, db_session):
    r = await client.get("/api/indicators/country-performance")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_country_performance_ranks_eur_country(client, db_session):
    await _seed_country(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await _seed_series(db_session, "country_de_equity", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 120.0})

    r = await client.get("/api/indicators/country-performance")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["code"] == "de"
    assert body[0]["perf_pct"] == pytest.approx(20.0)
    assert body[0]["latest_date"] == FIXED_TODAY.isoformat()
    assert body[0]["anchor_date"] == ANCHOR_TARGET.isoformat()
    assert body[0]["index_label"] == "DAX 40"


@pytest.mark.asyncio
async def test_get_country_performance_applies_fx_for_non_eur_country(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "^GSPC", "USD")
    await _seed_series(db_session, "country_us_equity", {ANCHOR_TARGET: 100.0, FIXED_TODAY: 110.0})
    await _seed_series(db_session, "fx_usd", {ANCHOR_TARGET: 0.9, FIXED_TODAY: 0.95})

    r = await client.get("/api/indicators/country-performance")
    assert r.status_code == 200
    body = r.json()
    expected = ((110.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert body[0]["perf_pct"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_countries_empty(client, db_session):
    r = await client.get("/api/indicators/country-performance/countries")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_countries(client, db_session):
    r = await client.post("/api/indicators/country-performance/countries", json={
        "code": "de", "label": "Allemagne", "index_ticker": "^GDAXI", "currency": "EUR", "index_label": "DAX 40",
    })
    assert r.status_code == 201
    assert r.json() == {
        "code": "de", "label": "Allemagne", "index_ticker": "^GDAXI", "currency": "EUR", "index_label": "DAX 40",
    }

    r = await client.get("/api/indicators/country-performance/countries")
    assert r.status_code == 200
    assert [c["code"] for c in r.json()] == ["de"]


@pytest.mark.asyncio
async def test_create_country_invalid_code_returns_400(client, db_session):
    r = await client.post("/api/indicators/country-performance/countries", json={
        "code": "DEU", "label": "Allemagne", "index_ticker": "^GDAXI", "currency": "EUR", "index_label": "DAX 40",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_country_invalid_currency_returns_400(client, db_session):
    r = await client.post("/api/indicators/country-performance/countries", json={
        "code": "de", "label": "Allemagne", "index_ticker": "^GDAXI", "currency": "eur", "index_label": "DAX 40",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_country_duplicate_code_returns_400(client, db_session):
    await _seed_country(db_session, "de")
    r = await client.post("/api/indicators/country-performance/countries", json={
        "code": "de", "label": "Allemagne (bis)", "index_ticker": "X", "currency": "EUR", "index_label": "X Index",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_country(client, db_session):
    await _seed_country(db_session, "de", "Allemagne", "^GDAXI", "EUR")
    r = await client.put("/api/indicators/country-performance/countries/de", json={
        "label": "Deutschland", "index_ticker": "EWG", "currency": "EUR", "index_label": "DAX ETF",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Deutschland"
    assert body["index_ticker"] == "EWG"
    assert body["index_label"] == "DAX ETF"


@pytest.mark.asyncio
async def test_update_country_invalid_currency_returns_400(client, db_session):
    await _seed_country(db_session, "de")
    r = await client.put("/api/indicators/country-performance/countries/de", json={
        "label": "Allemagne", "index_ticker": "^GDAXI", "currency": "eur", "index_label": "DAX 40",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_country_unknown_returns_404(client, db_session):
    r = await client.put("/api/indicators/country-performance/countries/zz", json={
        "label": "Nowhere", "index_ticker": "X", "currency": "EUR", "index_label": "X Index",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_country(client, db_session):
    await _seed_country(db_session, "us")
    await _seed_country(db_session, "fr")
    r = await client.delete("/api/indicators/country-performance/countries/fr")
    assert r.status_code == 204

    r = await client.get("/api/indicators/country-performance/countries")
    assert [c["code"] for c in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_delete_country_unknown_returns_404(client, db_session):
    r = await client.delete("/api/indicators/country-performance/countries/zz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_last_country_succeeds_no_guard(client, db_session):
    """Unlike regions, there's deliberately no 'last remaining' guard for countries."""
    await _seed_country(db_session, "us")
    r = await client.delete("/api/indicators/country-performance/countries/us")
    assert r.status_code == 204

    r = await client.get("/api/indicators/country-performance/countries")
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
        r = await client.post("/api/indicators/country-performance/refresh")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json() == {"job_id": 11, "status": "queued"}
    mock_queries.enqueue.assert_called_once_with("refresh_country_performance", payload=b"on_demand")


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        r = await client.get("/api/indicators/country-performance/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.started_at = datetime(2026, 7, 19, 7, 15, 0)
    fake_run.finished_at = datetime(2026, 7, 19, 7, 15, 5)
    fake_run.total_steps = 25
    fake_run.succeeded_steps = 25
    fake_run.failed_items = []

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
        r = await client.get("/api/indicators/country-performance/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
