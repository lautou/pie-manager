"""
Integration tests for /api/indicators/country-performance — Top-N ranking + country CRUD.
"""

import json
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.models.country_performance import CountryPerfConfig
from app.models.macro_indicator import MacroSeriesPrice

FIXED_TODAY = date(2026, 7, 19)
ANCHOR_TARGET = FIXED_TODAY - timedelta(days=365)


@pytest.fixture(autouse=True)
def _fixed_today():
    with patch("app.services.country_performance_service.date") as mock_date:
        mock_date.today.return_value = FIXED_TODAY
        yield mock_date


async def _seed_series(db_session, series: str, values: dict[date, float]) -> None:
    for d, value in values.items():
        db_session.add(MacroSeriesPrice(series=series, date=d, value=value))
    await db_session.flush()


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
async def test_refresh_dispatches_celery_task(client, db_session):
    mock_task = MagicMock()
    mock_task.id = "country-perf-task-abc"
    with patch("app.tasks.country_performance.refresh_country_performance") as mock_refresh:
        mock_refresh.delay.return_value = mock_task
        r = await client.post("/api/indicators/country-performance/refresh")
    assert r.status_code == 200
    assert r.json() == {"task_id": "country-perf-task-abc", "status": "queued"}
    mock_refresh.delay.assert_called_once()


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with patch("redis.Redis.from_url", return_value=mock_redis):
        r = await client.get("/api/indicators/country-performance/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    payload = {
        "status": "success",
        "started_at": "2026-07-19T07:15:00Z",
        "finished_at": "2026-07-19T07:15:05Z",
        "total_tickers": 25,
        "succeeded": 25,
        "failed_tickers": [],
    }
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(payload)
    with patch("redis.Redis.from_url", return_value=mock_redis):
        r = await client.get("/api/indicators/country-performance/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
