# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for Part 1 and Part 2 changes:
  - _to_eur() currency conversion helper
  - get_price_on_date() returning (price, currency) tuple
  - Transaction POST account ownership validation (HTTP 400)
"""
import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.price import AssetPrice
from app.services.price_service import get_price_on_date, _to_eur


# ---------------------------------------------------------------------------
# _to_eur — unit tests (no DB required)
# ---------------------------------------------------------------------------

def test_to_eur_already_eur():
    """EUR input returns unchanged price."""
    result = _to_eur(100.0, "EUR", {})
    assert result == pytest.approx(100.0)


def test_to_eur_gbp_with_rate():
    """GBP is converted using GBPEUR=X rate."""
    spot_rates = {"GBPEUR=X": 1.17}
    result = _to_eur(100.0, "GBP", spot_rates)
    assert result == pytest.approx(117.0)


def test_to_eur_gbp_pence_converted_to_gbp_first():
    """GBp (pence) is divided by 100 to get GBP, then converted to EUR."""
    spot_rates = {"GBPEUR=X": 1.17}
    result = _to_eur(10000.0, "GBp", spot_rates)
    # 10000 GBp → 100 GBP → 117 EUR
    assert result == pytest.approx(117.0)


def test_to_eur_usd_with_rate():
    """USD converted using USDEUR=X rate."""
    spot_rates = {"USDEUR=X": 0.92}
    result = _to_eur(200.0, "USD", spot_rates)
    assert result == pytest.approx(184.0)


def test_to_eur_no_rate_fallback():
    """When no conversion rate exists, price is returned as-is."""
    result = _to_eur(50.0, "CHF", {})
    assert result == pytest.approx(50.0)


def test_to_eur_gbp_pence_no_gbp_rate_fallback():
    """GBp without GBPEUR=X rate: still divides by 100, then returns the GBP value as-is."""
    result = _to_eur(500.0, "GBp", {})
    # 500 GBp → 5.0 GBP, no rate → return 5.0
    assert result == pytest.approx(5.0)


def test_to_eur_zero_price():
    """Zero price stays zero regardless of currency."""
    spot_rates = {"GBPEUR=X": 1.17}
    assert _to_eur(0.0, "GBP", spot_rates) == pytest.approx(0.0)
    assert _to_eur(0.0, "GBp", spot_rates) == pytest.approx(0.0)
    assert _to_eur(0.0, "EUR", spot_rates) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# get_price_on_date — returns (price, currency) tuple
# ---------------------------------------------------------------------------

async def _add_product(db, ticker: str, category: str = "Actif") -> None:
    p = Product(ticker=ticker, name=ticker, category=category, currency="EUR")
    db.add(p)
    await db.flush()


@pytest.mark.asyncio
async def test_get_price_on_date_returns_tuple(db_session):
    """get_price_on_date now returns (price, currency) instead of a bare float."""
    suffix = id(db_session)
    ticker = f"TUPLE.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 6, 1),
                               price=42.5, currency="EUR", source="yfinance"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 6, 1))
    assert result is not None
    assert isinstance(result, tuple)
    price, currency = result
    assert price == pytest.approx(42.5)
    assert currency == "EUR"


@pytest.mark.asyncio
async def test_get_price_on_date_gbp_currency(db_session):
    """Currency is propagated correctly for non-EUR tickers."""
    suffix = id(db_session)
    ticker = f"GBPTICKER.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 7, 15),
                               price=1234.5, currency="GBp", source="yfinance"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 7, 15))
    assert result is not None
    price, currency = result
    assert price == pytest.approx(1234.5)
    assert currency == "GBp"


@pytest.mark.asyncio
async def test_get_price_on_date_returns_none_when_no_price(db_session):
    """Returns None when no price exists at or before the date."""
    suffix = id(db_session)
    ticker = f"NOPRICE.{suffix}"
    await _add_product(db_session, ticker)

    result = await get_price_on_date(db_session, ticker, date(2025, 1, 1))
    assert result is None


@pytest.mark.asyncio
async def test_get_price_on_date_picks_most_recent_before(db_session):
    """With multiple prices, returns the one closest to (but not after) the query date."""
    suffix = id(db_session)
    ticker = f"RECENT.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 1),
                               price=10.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 10),
                               price=15.0, currency="EUR"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 3, 5))
    assert result is not None
    price, _ = result
    assert price == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Transaction POST — account ownership validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_rejects_wrong_account_owner(client):
    """
    POST /api/transactions/ should return HTTP 400 when the account_id belongs
    to a different portfolio than portfolio_id.
    """
    # Create two separate portfolios
    r1 = await client.post("/api/portfolios/", json={"name": "OwnerCheck-Port1"})
    assert r1.status_code == 201
    uid1 = r1.json()["id"]

    r2 = await client.post("/api/portfolios/", json={"name": "OwnerCheck-Port2"})
    assert r2.status_code == 201
    uid2 = r2.json()["id"]

    # Account belongs to portfolio 2 only
    r_acct = await client.post("/api/brokers/", json={
        "name": "Foreign Account", "currency": "EUR", "portfolio_ids": [uid2]
    })
    assert r_acct.status_code == 201
    foreign_account_id = r_acct.json()["id"]

    # Create a product for the transaction
    await client.post("/api/products/", json={
        "ticker": "XTEST.OWN1", "name": "Test Product", "category": "Actif", "currency": "EUR"
    })

    # Try to create a transaction for portfolio 1 using account from portfolio 2 — should fail
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid1,
        "account_id": foreign_account_id,   # wrong owner!
        "date": "2025-06-01",
        "type": "Actif",
        "ticker": "XTEST.OWN1",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -5.0,
        "unit_price": 100.0,
    })

    assert r.status_code == 400
    assert "portfolio_id mismatch" in r.json()["detail"].lower() or "belong" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_transaction_rejects_nonexistent_account(client):
    """POST /api/transactions/ returns HTTP 400 when account_id does not exist."""
    r = await client.post("/api/portfolios/", json={"name": "NoAcct-Port"})
    assert r.status_code == 201
    uid = r.json()["id"]

    await client.post("/api/products/", json={
        "ticker": "XTEST.NOACCT", "name": "Test", "category": "Actif", "currency": "EUR"
    })

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid,
        "account_id": 999999,  # does not exist
        "date": "2025-06-01",
        "type": "Actif",
        "ticker": "XTEST.NOACCT",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -1.0,
        "unit_price": 50.0,
    })

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_transaction_accepts_correct_account_owner(client):
    """POST /api/transactions/ succeeds when account belongs to the same portfolio."""
    r1 = await client.post("/api/portfolios/", json={"name": "OwnerOK-Port"})
    assert r1.status_code == 201
    uid = r1.json()["id"]

    r_acct = await client.post("/api/brokers/", json={
        "name": "My Account", "currency": "EUR", "portfolio_ids": [uid]
    })
    assert r_acct.status_code == 201
    account_id = r_acct.json()["id"]

    await client.post("/api/products/", json={
        "ticker": "XTEST.OKOWN", "name": "Test Product", "category": "Actif", "currency": "EUR"
    })

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid,
        "account_id": account_id,
        "date": "2025-07-01",
        "type": "Actif",
        "ticker": "XTEST.OKOWN",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -3.0,
        "unit_price": 75.0,
    })

    assert r.status_code == 201
