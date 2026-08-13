"""
Integration tests for /api/indicators — global growth/inflation ratio endpoints + region CRUD.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.macro_indicator import MacroRegion, MacroSeriesPrice


async def _seed(db_session, series: str, values: dict[str, float]) -> None:
    for iso_date, value in values.items():
        db_session.add(MacroSeriesPrice(series=series, date=iso_date, value=value))
    await db_session.flush()


async def _seed_region(
    db_session, code: str, label: str = "Test", equity: str = "EQ", bond: str = "BD",
    equity_label: str = "Test Equity", bond_label: str = "Test Bond",
) -> None:
    db_session.add(MacroRegion(
        code=code, label=label, equity_ticker=equity, bond_ticker=bond,
        equity_label=equity_label, bond_label=bond_label,
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_get_growth_indicator_defaults_to_us(client, db_session):
    from datetime import date
    await _seed_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    await _seed(db_session, "us_equity", {date(2020, 1, 1): 100.0, date(2020, 1, 2): 110.0})
    await _seed(db_session, "oil", {date(2020, 1, 1): 1.0, date(2020, 1, 2): 1.0})

    r = await client.get("/api/indicators/growth")
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == ["2020-01-01", "2020-01-02"]
    assert body["ratio"] == pytest.approx([100.0, 110.0])
    assert body["status"] == "above"
    assert body["numerator_ticker"] == "^SPXEW"
    assert body["denominator_ticker"] == "CL=F"
    assert body["numerator_label"] == "S&P 500 Equal Weight"
    assert body["denominator_label"] == "Pétrole (WTI)"


@pytest.mark.asyncio
async def test_get_growth_indicator_no_data_returns_empty(client, db_session):
    await _seed_region(db_session, "us")
    r = await client.get("/api/indicators/growth")
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == []
    assert body["status"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us", "fr", "world"])
async def test_get_growth_indicator_per_region(client, db_session, region):
    from datetime import date
    await _seed_region(db_session, region, equity=f"{region}-EQ")
    await _seed(db_session, f"{region}_equity", {date(2020, 1, 1): 50.0, date(2020, 1, 2): 60.0})
    await _seed(db_session, "oil", {date(2020, 1, 1): 1.0, date(2020, 1, 2): 1.0})

    r = await client.get("/api/indicators/growth", params={"region": region})
    assert r.status_code == 200
    assert r.json()["ratio"] == pytest.approx([100.0, 120.0])


@pytest.mark.asyncio
async def test_get_growth_indicator_unknown_region_returns_404(client, db_session):
    r = await client.get("/api/indicators/growth", params={"region": "atlantis"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_inflation_indicator_defaults_to_us(client, db_session):
    from datetime import date
    await _seed_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    await _seed(db_session, "us_bond", {date(2020, 1, 1): 4.0, date(2020, 1, 2): 3.0})
    await _seed(db_session, "gold", {date(2020, 1, 1): 1.0, date(2020, 1, 2): 1.0})

    r = await client.get("/api/indicators/inflation")
    assert r.status_code == 200
    body = r.json()
    # raw ratio = [4.0, 3.0], rebased to 100 at the first point → [100.0, 75.0]
    assert body["ratio"] == pytest.approx([100.0, 75.0])
    assert body["status"] == "below"
    assert body["numerator_ticker"] == "GOVT"
    assert body["denominator_ticker"] == "GC=F"
    assert body["numerator_label"] == "Obligations Trésor"
    assert body["denominator_label"] == "Or"


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us", "fr", "world"])
async def test_get_inflation_indicator_per_region(client, db_session, region):
    from datetime import date
    await _seed_region(db_session, region, bond=f"{region}-BD")
    await _seed(db_session, f"{region}_bond", {date(2020, 1, 1): 40.0, date(2020, 1, 2): 30.0})
    await _seed(db_session, "gold", {date(2020, 1, 1): 1.0, date(2020, 1, 2): 1.0})

    r = await client.get("/api/indicators/inflation", params={"region": region})
    assert r.status_code == 200
    assert r.json()["ratio"] == pytest.approx([100.0, 75.0])


@pytest.mark.asyncio
async def test_get_inflation_indicator_unknown_region_returns_404(client, db_session):
    r = await client.get("/api/indicators/inflation", params={"region": "atlantis"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_refresh_dispatches_via_pgqueuer(client, db_session):
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[9])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        r = await client.post("/api/indicators/refresh")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json() == {"job_id": 9, "status": "queued"}
    mock_queries.enqueue.assert_called_once_with("refresh_macro_indicators", payload=b"on_demand")


@pytest.mark.asyncio
async def test_sync_status_never_synced(client, db_session):
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        r = await client.get("/api/indicators/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync(client, db_session):
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.started_at = datetime(2026, 7, 14, 7, 0, 0)
    fake_run.finished_at = datetime(2026, 7, 14, 7, 0, 5)
    fake_run.total_steps = 4
    fake_run.succeeded_steps = 4
    fake_run.failed_items = []

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
        r = await client.get("/api/indicators/sync-status")
    assert r.status_code == 200
    assert r.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Region CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_regions_empty(client, db_session):
    r = await client.get("/api/indicators/regions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_and_list_regions(client, db_session):
    r = await client.post("/api/indicators/regions", json={
        "code": "de", "label": "Allemagne", "equity_ticker": "^GDAXI", "bond_ticker": "BUND",
        "equity_label": "DAX 40", "bond_label": "Bund 10 ans",
    })
    assert r.status_code == 201
    assert r.json() == {
        "code": "de", "label": "Allemagne", "equity_ticker": "^GDAXI", "bond_ticker": "BUND",
        "equity_label": "DAX 40", "bond_label": "Bund 10 ans",
    }

    r = await client.get("/api/indicators/regions")
    assert r.status_code == 200
    assert [r_["code"] for r_ in r.json()] == ["de"]


@pytest.mark.asyncio
async def test_create_region_invalid_code_returns_400(client, db_session):
    r = await client.post("/api/indicators/regions", json={
        "code": "DE!", "label": "Allemagne", "equity_ticker": "^GDAXI", "bond_ticker": "BUND",
        "equity_label": "DAX 40", "bond_label": "Bund 10 ans",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_region_duplicate_code_returns_400(client, db_session):
    await _seed_region(db_session, "de")
    r = await client.post("/api/indicators/regions", json={
        "code": "de", "label": "Allemagne (bis)", "equity_ticker": "X", "bond_ticker": "Y",
        "equity_label": "X label", "bond_label": "Y label",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_region(client, db_session):
    await _seed_region(db_session, "de", "Allemagne", "^GDAXI", "BUND", "DAX 40", "Bund 10 ans")
    r = await client.put("/api/indicators/regions/de", json={
        "label": "Deutschland", "equity_ticker": "EWG", "bond_ticker": "BUNL",
        "equity_label": "iShares MSCI Germany", "bond_label": "Bund 10-15 ans",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "Deutschland"
    assert body["equity_ticker"] == "EWG"
    assert body["equity_label"] == "iShares MSCI Germany"
    assert body["bond_label"] == "Bund 10-15 ans"


@pytest.mark.asyncio
async def test_update_region_unknown_returns_404(client, db_session):
    r = await client.put("/api/indicators/regions/zz", json={
        "label": "Nowhere", "equity_ticker": "X", "bond_ticker": "Y",
        "equity_label": "X label", "bond_label": "Y label",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_region(client, db_session):
    await _seed_region(db_session, "us")
    await _seed_region(db_session, "fr")
    r = await client.delete("/api/indicators/regions/fr")
    assert r.status_code == 204

    r = await client.get("/api/indicators/regions")
    assert [r_["code"] for r_ in r.json()] == ["us"]


@pytest.mark.asyncio
async def test_delete_region_unknown_returns_404(client, db_session):
    r = await client.delete("/api/indicators/regions/zz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_last_region_returns_400(client, db_session):
    await _seed_region(db_session, "us")
    r = await client.delete("/api/indicators/regions/us")
    assert r.status_code == 400
