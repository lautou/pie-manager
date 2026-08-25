# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for /api/indicators/equity-premium — implied equity risk premium bar chart
+ country CRUD (including the last-remaining-row delete guard, unlike sector-performance).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.equity_premium import EquityPremiumConfig
from tests.helpers import FIXED_TODAY, make_fixed_today_fixture, seed_series_dict as _seed_series

_fixed_today = make_fixed_today_fixture("app.services.equity_premium_service")


async def _seed_country(
    db_session, code: str, label: str = "Test", equity_ticker: str = "TEST", bond_ticker: str = "TBND",
    equity_label: str = "Test Equity", bond_label: str = "Test Bond",
) -> None:
    db_session.add(EquityPremiumConfig(
        code=code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    ))
    await db_session.flush()


# ---------------------------------------------------------------------------
# GET /equity-premium (ranking)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_equity_premium_empty_universe_returns_empty_list(client, db_session):
    r = await client.get("/api/indicators/equity-premium")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_equity_premium_computes_premium(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed_series(db_session, "premium_us_equity_yield", {FIXED_TODAY: 0.04})
    await _seed_series(db_session, "premium_us_bond_yield", {FIXED_TODAY: 0.015})

    r = await client.get("/api/indicators/equity-premium")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["code"] == "us"
    assert body[0]["premium_pct"] == pytest.approx(2.5)
    assert body[0]["equity_yield_pct"] == pytest.approx(4.0)
    assert body[0]["bond_yield_pct"] == pytest.approx(1.5)
    assert body[0]["equity_label"] == "S&P 500"
    assert body[0]["bond_label"] == "Trésor US"
    assert body[0]["asof_date"] == FIXED_TODAY.isoformat()


@pytest.mark.asyncio
async def test_get_equity_premium_excludes_country_missing_a_leg(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed_series(db_session, "premium_us_equity_yield", {FIXED_TODAY: 0.04})

    r = await client.get("/api/indicators/equity-premium")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_premium_countries_empty(client, db_session):
    r = await client.get("/api/indicators/equity-premium/countries")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_premium_countries(client, db_session):
    r = await client.post("/api/indicators/equity-premium/countries", json={
        "code": "us", "label": "États-Unis", "equity_ticker": "SPY", "bond_ticker": "IEF",
        "equity_label": "S&P 500 (SPY)", "bond_label": "Trésor US (IEF)",
    })
    assert r.status_code == 201
    assert r.json() == {
        "code": "us", "label": "États-Unis", "equity_ticker": "SPY", "bond_ticker": "IEF",
        "equity_label": "S&P 500 (SPY)", "bond_label": "Trésor US (IEF)",
    }

    r = await client.get("/api/indicators/equity-premium/countries")
    assert r.status_code == 200
    assert [c["code"] for c in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_create_premium_country_invalid_code_returns_400(client, db_session):
    r = await client.post("/api/indicators/equity-premium/countries", json={
        "code": "USA", "label": "États-Unis", "equity_ticker": "SPY", "bond_ticker": "IEF",
        "equity_label": "S&P 500", "bond_label": "Trésor US",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_premium_country_duplicate_code_returns_400(client, db_session):
    await _seed_country(db_session, "us")
    r = await client.post("/api/indicators/equity-premium/countries", json={
        "code": "us", "label": "États-Unis (bis)", "equity_ticker": "SPY", "bond_ticker": "IEF",
        "equity_label": "S&P 500", "bond_label": "Trésor US",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_premium_country(client, db_session):
    await _seed_country(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    r = await client.put("/api/indicators/equity-premium/countries/us", json={
        "label": "USA", "equity_ticker": "SPY", "bond_ticker": "IEF",
        "equity_label": "S&P 500 Index", "bond_label": "US Treasury 7-10y",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "USA"
    assert body["equity_label"] == "S&P 500 Index"
    assert body["bond_label"] == "US Treasury 7-10y"


@pytest.mark.asyncio
async def test_update_premium_country_unknown_returns_404(client, db_session):
    r = await client.put("/api/indicators/equity-premium/countries/zz", json={
        "label": "Nowhere", "equity_ticker": "X", "bond_ticker": "Y",
        "equity_label": "X Index", "bond_label": "Y Index",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_premium_country(client, db_session):
    await _seed_country(db_session, "us")
    await _seed_country(db_session, "fr")
    r = await client.delete("/api/indicators/equity-premium/countries/fr")
    assert r.status_code == 204

    r = await client.get("/api/indicators/equity-premium/countries")
    assert [c["code"] for c in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_delete_premium_country_unknown_returns_404(client, db_session):
    r = await client.delete("/api/indicators/equity-premium/countries/zz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_last_premium_country_returns_400(client, db_session):
    """Unlike sector-performance's no-guard delete, this tab must always keep at least one
    country configured — mirrors macro_regions' own last-row guard."""
    await _seed_country(db_session, "us")
    r = await client.delete("/api/indicators/equity-premium/countries/us")
    assert r.status_code == 400

    r = await client.get("/api/indicators/equity-premium/countries")
    assert [c["code"] for c in r.json()] == ["us"]


# ---------------------------------------------------------------------------
# refresh + sync-status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_dispatches_via_pgqueuer(client, db_session):
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[11])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        r = await client.post("/api/indicators/equity-premium/refresh")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json() == {"job_id": 11, "status": "queued"}
    mock_queries.enqueue.assert_called_once_with("refresh_equity_premium", payload=b"on_demand")


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        r = await client.get("/api/indicators/equity-premium/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.started_at = datetime(2026, 7, 19, 7, 45, 0)
    fake_run.finished_at = datetime(2026, 7, 19, 7, 45, 5)
    fake_run.total_steps = 22
    fake_run.succeeded_steps = 22
    fake_run.failed_items = []

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
        r = await client.get("/api/indicators/equity-premium/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
