# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared HTTP helper functions and DB setup helpers for integration tests.

HTTP helpers call real FastAPI endpoints via the injected test client so they
exercise the same code paths as production requests.

DB setup helpers insert model objects directly via the SQLAlchemy session.
"""
from datetime import date, timedelta
from datetime import date as _date
from unittest.mock import patch

import pytest
from sqlalchemy import select as _sa_select

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.snapshot import DailySnapshot
from app.models.portfolio_account import PortfolioAccount
from app.models.macro_indicator import MacroSeriesPrice

# ---------------------------------------------------------------------------
# Shared fixture/seed helpers for the country/sector-performance and equity-premium
# test suites (router + service files) — each hand-copied an identical FIXED_TODAY/
# _fixed_today fixture (differing only in which service module's `date` gets patched)
# and an identical seed helper before being collapsed here.
# ---------------------------------------------------------------------------

FIXED_TODAY = date(2026, 7, 19)
ANCHOR_TARGET = FIXED_TODAY - timedelta(days=365)


def make_fixed_today_fixture(module_path: str, fixed_today: date = FIXED_TODAY):
    """Factory for an autouse fixture that freezes `date.today()` as seen by one service
    module, without touching `date(...)` construction elsewhere. Each performance test file
    needs a different module patched, so this returns a fresh fixture function per call
    rather than being a single shared fixture."""
    @pytest.fixture(autouse=True)
    def _fixed_today():
        with patch(f"{module_path}.date") as mock_date:
            mock_date.today.return_value = fixed_today
            yield mock_date
    return _fixed_today


async def seed_series_points(db_session, series: str, points: list[tuple[date, float]]) -> None:
    """Seed a MacroSeriesPrice series via the real replace_series_prices — used by the
    country/sector-performance and equity-premium *service* tests."""
    from app.services.macro_series_price_service import replace_series_prices
    await replace_series_prices(db_session, series, points)
    await db_session.flush()


async def seed_series_dict(db_session, series: str, values: dict[date, float]) -> None:
    """Seed a MacroSeriesPrice series by inserting rows directly — used by the
    country/sector-performance and equity-premium *router* tests."""
    for d, value in values.items():
        db_session.add(MacroSeriesPrice(series=series, date=d, value=value))
    await db_session.flush()


async def create_portfolio(client, name: str) -> int:
    """POST /api/portfolios/ and return the new portfolio id."""
    r = await client.post("/api/portfolios/", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def create_broker(
    client,
    portfolio_id: int,
    name: str = "Degiro",
    currency: str = "EUR",
) -> dict:
    """POST /api/brokers/ and return the full response dict."""
    r = await client.post("/api/brokers/", json={
        "name": name,
        "currency": currency,
        "portfolio_ids": [portfolio_id],
    })
    assert r.status_code == 201, r.text
    return r.json()


async def create_broker_id(
    client,
    portfolio_id: int,
    name: str = "Degiro",
    currency: str = "EUR",
) -> int:
    """POST /api/brokers/ and return only the new broker id."""
    return (await create_broker(client, portfolio_id, name, currency))["id"]


async def create_product(
    client,
    ticker: str,
    name: str | None = None,
    category: str = "Actif",
    currency: str = "EUR",
    instrument_type: str | None = None,
) -> None:
    """POST /api/products/ (201 or 409 if already exists)."""
    r = await client.post("/api/products/", json={
        "ticker": ticker,
        "name": name or ticker,
        "category": category,
        "currency": currency,
        "instrument_type": instrument_type,
    })
    assert r.status_code in (201, 409), r.text


async def create_pool(
    client,
    portfolio_id: int,
    name: str = "TestPool",
    strategy: str = "Offensive",
    target_pct: float = 0.25,
    is_active: bool = True,
) -> dict:
    """POST /api/pools/ and return the full response dict."""
    r = await client.post("/api/pools/", json={
        "portfolio_id": portfolio_id,
        "name": name,
        "strategy": strategy,
        "target_pct": target_pct,
        "is_active": is_active,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# DB-level setup helper for dashboard tests
# ---------------------------------------------------------------------------

async def full_dashboard_setup(db, suffix: str) -> dict:
    """
    Insert a minimal but complete portfolio for dashboard testing directly
    via the SQLAlchemy session (bypasses HTTP so it is faster and supports
    low-level assertions).

    Returns a dict with all created IDs/objects.
    """
    portfolio = Portfolio(name=f"Dash-{suffix}")
    db.add(portfolio)
    await db.flush()
    portfolio_id = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db.add(account)
    await db.flush()
    db.add(PortfolioAccount(portfolio_id=portfolio_id, broker_id=account.id, cash_balance_eur=1000.0))
    await db.flush()

    # Ensure LIQUIDITE.EURO product exists (may already exist from a previous test)
    liq_ticker = "LIQUIDITE.EURO"
    existing_liq = await db.execute(_sa_select(Product).where(Product.ticker == liq_ticker))
    if not existing_liq.scalar_one_or_none():
        db.add(Product(ticker=liq_ticker, name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db.flush()

    ticker_off = f"OFF.{suffix}"
    ticker_def = f"DEF.{suffix}"
    db.add(Product(ticker=ticker_off, name="Offensive ETF", category="Actif", currency="EUR"))
    db.add(Product(ticker=ticker_def, name="Defensive ETF", category="Actif", currency="EUR"))
    await db.flush()

    pool_off = Pool(portfolio_id=portfolio_id, name="Offensive Pool",
                    strategy="Offensive", target_pct=0.5, is_active=True)
    pool_def = Pool(portfolio_id=portfolio_id, name="Defensive Pool",
                    strategy="Defensive", target_pct=0.5, is_active=True)
    db.add(pool_off)
    db.add(pool_def)
    await db.flush()

    db.add(PoolProduct(pool_id=pool_off.id, ticker=ticker_off))
    db.add(PoolProduct(pool_id=pool_def.id, ticker=ticker_def))
    await db.flush()

    tx_date = _date(2025, 1, 10)
    for ticker in (ticker_off, ticker_def):
        db.add(Transaction(
            portfolio_id=portfolio_id, account_id=account.id,
            date=tx_date, type="Actif", ticker=ticker,
            currency="EUR", exchange_rate=1.0,
            quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
            total_amount=-1000.0, total_amount_eur=-1000.0,
        ))
    db.add(Transaction(
        portfolio_id=portfolio_id, account_id=account.id,
        date=_date(2025, 1, 5), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=1000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=1000.0, total_amount_eur=1000.0,
    ))
    await db.flush()

    for ticker in (ticker_off, ticker_def):
        db.add(AssetPrice(ticker=ticker, date=tx_date,
                          price=110.0, currency="EUR", source="yfinance"))
    await db.flush()

    snap = DailySnapshot(portfolio_id=portfolio_id, date=tx_date,
                         total_eur=3200.0, offensive_eur=1100.0, defensive_eur=1100.0)
    db.add(snap)
    await db.flush()

    return {
        "portfolio_id": portfolio_id,
        "broker_id": account.id,
        "ticker_off": ticker_off,
        "ticker_def": ticker_def,
        "pool_off_id": pool_off.id,
        "pool_def_id": pool_def.id,
        "snap_id": snap.id,
    }
