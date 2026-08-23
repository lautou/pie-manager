# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for /api/prices — list with filters, upsert, and delete.

Covers prices.py lines: 42-51 (list with filters), 56-67 (upsert), 70-74 (fetch).
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from app.core.pgq import get_pgq_queries
from app.main import app as fastapi_app
from app.models.product import Product
from app.models.price import AssetPrice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_product(db, ticker: str) -> None:
    existing = await db.get(Product, ticker)
    if not existing:
        db.add(Product(ticker=ticker, name=ticker, category="Actif", currency="EUR"))
        await db.flush()


async def _upsert(client, ticker: str, price_date: date, price: float,
                   currency: str = "EUR", source: str = "manual") -> dict:
    r = await client.post("/api/prices/", json={
        "ticker": ticker,
        "date": price_date.isoformat(),
        "price": price,
        "currency": currency,
        "source": source,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /api/prices/ — list with filters (lines 42-51)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_prices_no_filter(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.LIST.{suffix}"
    await _ensure_product(db_session, ticker)

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 10),
                               price=10.0, currency="EUR", source="yfinance"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 20),
                               price=20.0, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/prices/")
    assert r.status_code == 200
    data = r.json()
    tickers_in_response = [d["ticker"] for d in data]
    assert ticker in tickers_in_response


@pytest.mark.asyncio
async def test_list_prices_filter_by_ticker(client, db_session):
    suffix = id(db_session)
    ticker_a = f"PRC.A.{suffix}"
    ticker_b = f"PRC.B.{suffix}"
    await _ensure_product(db_session, ticker_a)
    await _ensure_product(db_session, ticker_b)

    db_session.add(AssetPrice(ticker=ticker_a, date=date(2025, 2, 1),
                               price=100.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker_b, date=date(2025, 2, 1),
                               price=200.0, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/prices/", params={"ticker": ticker_a})
    assert r.status_code == 200
    data = r.json()
    assert all(d["ticker"] == ticker_a for d in data)
    assert any(d["price"] == pytest.approx(100.0) for d in data)


@pytest.mark.asyncio
async def test_list_prices_filter_by_date_from(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.FROM.{suffix}"
    await _ensure_product(db_session, ticker)

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 1),
                               price=10.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 15),
                               price=20.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 1),
                               price=30.0, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/prices/", params={"ticker": ticker, "date_from": "2025-03-15"})
    assert r.status_code == 200
    data = r.json()
    dates_returned = [d["date"] for d in data]
    assert "2025-03-01" not in dates_returned
    assert "2025-03-15" in dates_returned
    assert "2025-04-01" in dates_returned


@pytest.mark.asyncio
async def test_list_prices_filter_by_date_to(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.TO.{suffix}"
    await _ensure_product(db_session, ticker)

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 5, 1),
                               price=50.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 5, 31),
                               price=60.0, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/prices/", params={"ticker": ticker, "date_to": "2025-05-15"})
    assert r.status_code == 200
    data = r.json()
    dates_returned = [d["date"] for d in data]
    assert "2025-05-01" in dates_returned
    assert "2025-05-31" not in dates_returned


@pytest.mark.asyncio
async def test_list_prices_filter_combined(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.COMB.{suffix}"
    await _ensure_product(db_session, ticker)

    for d, p in [(date(2025, 1, 1), 10), (date(2025, 3, 1), 20), (date(2025, 6, 1), 30)]:
        db_session.add(AssetPrice(ticker=ticker, date=d, price=p, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/prices/", params={
        "ticker": ticker,
        "date_from": "2025-02-01",
        "date_to": "2025-05-01",
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["price"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_list_prices_ordered_by_date_desc(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.ORD.{suffix}"
    await _ensure_product(db_session, ticker)

    for d, p in [(date(2025, 7, 1), 1), (date(2025, 7, 15), 2), (date(2025, 7, 31), 3)]:
        db_session.add(AssetPrice(ticker=ticker, date=d, price=p, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/prices/", params={"ticker": ticker})
    assert r.status_code == 200
    data = r.json()
    dates = [d["date"] for d in data]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# POST /api/prices/ — upsert (lines 56-67)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_price_creates_new(client, db_session):
    suffix = id(db_session)
    ticker = f"PRC.NEW.{suffix}"
    await _ensure_product(db_session, ticker)

    r = await client.post("/api/prices/", json={
        "ticker": ticker,
        "date": "2025-08-01",
        "price": 150.0,
        "currency": "EUR",
        "source": "manual",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["ticker"] == ticker
    assert data["date"] == "2025-08-01"
    assert data["price"] == pytest.approx(150.0)
    assert data["source"] == "manual"
    assert "id" in data


@pytest.mark.asyncio
async def test_upsert_price_updates_existing(client, db_session):
    """POSTing the same (ticker, date) twice should update the price."""
    suffix = id(db_session)
    ticker = f"PRC.UPD.{suffix}"
    await _ensure_product(db_session, ticker)

    await _upsert(client, ticker, date(2025, 9, 1), 100.0)
    r2 = await client.post("/api/prices/", json={
        "ticker": ticker,
        "date": "2025-09-01",
        "price": 200.0,
        "currency": "EUR",
        "source": "manual",
    })
    assert r2.status_code == 201
    assert r2.json()["price"] == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_upsert_price_returns_full_object(client, db_session):
    """The response should include all fields of PriceOut."""
    suffix = id(db_session)
    ticker = f"PRC.FULL.{suffix}"
    await _ensure_product(db_session, ticker)

    r = await client.post("/api/prices/", json={
        "ticker": ticker,
        "date": "2025-10-01",
        "price": 75.5,
        "currency": "USD",
        "source": "yfinance",
    })
    assert r.status_code == 201
    data = r.json()
    required_fields = {"id", "ticker", "date", "price", "currency", "source"}
    assert required_fields <= set(data.keys())
    assert data["currency"] == "USD"
    assert data["source"] == "yfinance"


@pytest.mark.asyncio
async def test_list_prices_empty_returns_list(client, db_session):
    """Sanity check: endpoint returns 200 with empty list for unknown ticker."""
    r = await client.get("/api/prices/", params={"ticker": "COMPLETELY.UNKNOWN.TICKER.XYZ"})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# POST /api/prices/fetch — trigger via PgQueuer (lines 70-74)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_price_fetch_returns_job_id(client):
    """POST /prices/fetch must return 200 with job_id without a live PgQueuer worker — it
    enqueues the same "refresh_prices_live" entrypoint as admin.py's /refresh-prices."""
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[7])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        r = await client.post("/api/prices/fetch")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == 7
    mock_queries.enqueue.assert_called_once_with("refresh_prices_live", payload=b"on_demand")
