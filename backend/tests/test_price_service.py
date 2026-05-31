"""
Unit tests for services/price_service.py.

Covers lines 13-22 (get_active_tickers), 33-40 (upsert_price), 43-52 (get_price_on_date).
Tested directly with db_session (no HTTP layer).
"""

import pytest
from datetime import date

from app.models.product import Product
from app.models.price import AssetPrice
from app.services.price_service import (
    get_active_tickers,
    upsert_price,
    get_price_on_date,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_product(db, ticker: str, category: str = "Actif",
                        currency: str = "EUR") -> Product:
    p = Product(ticker=ticker, name=ticker, category=category, currency=currency)
    db.add(p)
    await db.flush()
    return p


# ---------------------------------------------------------------------------
# get_active_tickers (lines 13-22)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_tickers_returns_actif(db_session):
    suffix = id(db_session)
    ticker = f"ACT.{suffix}"
    await _add_product(db_session, ticker, category="Actif", currency="EUR")

    tickers = await get_active_tickers(db_session)
    assert (ticker, "EUR") in tickers


@pytest.mark.asyncio
async def test_get_active_tickers_excludes_manuel(db_session):
    suffix = id(db_session)
    ticker = f"MAN.{suffix}"
    await _add_product(db_session, ticker, category="Manuel")

    tickers = await get_active_tickers(db_session)
    ticker_names = [t[0] for t in tickers]
    assert ticker not in ticker_names


@pytest.mark.asyncio
async def test_get_active_tickers_excludes_frais(db_session):
    suffix = id(db_session)
    ticker = f"FRA.{suffix}"
    await _add_product(db_session, ticker, category="Frais")

    tickers = await get_active_tickers(db_session)
    ticker_names = [t[0] for t in tickers]
    assert ticker not in ticker_names


@pytest.mark.asyncio
async def test_get_active_tickers_picks_primary_currency(db_session):
    """currency field is returned directly."""
    suffix = id(db_session)
    ticker = f"MULTI.{suffix}"
    await _add_product(db_session, ticker, category="Actif", currency="USD")

    tickers = await get_active_tickers(db_session)
    found = [(t, c) for t, c in tickers if t == ticker]
    assert len(found) == 1
    assert found[0][1] == "USD"  # primary = first


@pytest.mark.asyncio
async def test_get_active_tickers_includes_cash_category(db_session):
    """Cash category is NOT excluded (only Manuel and Frais are)."""
    suffix = id(db_session)
    ticker = f"CASH.{suffix}"
    await _add_product(db_session, ticker, category="Cash", currency="EUR")

    tickers = await get_active_tickers(db_session)
    ticker_names = [t[0] for t in tickers]
    assert ticker in ticker_names


# ---------------------------------------------------------------------------
# upsert_price (lines 33-40)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_price_inserts_new(db_session):
    suffix = id(db_session)
    ticker = f"UPS.{suffix}"
    await _add_product(db_session, ticker)

    await upsert_price(db_session, ticker, date(2025, 1, 10), 100.0, "EUR")
    await db_session.flush()

    # Verify via get_price_on_date — now returns (price, currency)
    result = await get_price_on_date(db_session, ticker, date(2025, 1, 10))
    assert result is not None
    price, currency = result
    assert price == pytest.approx(100.0)
    assert currency == "EUR"


@pytest.mark.asyncio
async def test_upsert_price_updates_existing(db_session):
    """Calling upsert_price twice for same (ticker, date) updates the price."""
    suffix = id(db_session)
    ticker = f"UPDUP.{suffix}"
    await _add_product(db_session, ticker)

    await upsert_price(db_session, ticker, date(2025, 2, 15), 200.0, "EUR")
    await db_session.flush()

    await upsert_price(db_session, ticker, date(2025, 2, 15), 250.0, "EUR")
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 2, 15))
    assert result is not None
    price, _ = result
    assert price == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_upsert_price_with_custom_source(db_session):
    """Source is stored correctly."""
    suffix = id(db_session)
    ticker = f"SRC.{suffix}"
    await _add_product(db_session, ticker)

    await upsert_price(db_session, ticker, date(2025, 3, 1), 50.0, "USD", source="manual")
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(AssetPrice).where(AssetPrice.ticker == ticker)
    )
    row = result.scalar_one()
    assert row.source == "manual"
    assert row.currency == "USD"


# ---------------------------------------------------------------------------
# get_price_on_date (lines 43-52)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_price_on_date_exact(db_session):
    suffix = id(db_session)
    ticker = f"GPD.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 5, 1),
                               price=300.0, currency="EUR", source="yfinance"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 5, 1))
    assert result is not None
    price, currency = result
    assert price == pytest.approx(300.0)
    assert currency == "EUR"


@pytest.mark.asyncio
async def test_get_price_on_date_most_recent_before(db_session):
    """Returns the most recent price at or before on_date."""
    suffix = id(db_session)
    ticker = f"GPDMRB.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 1),
                               price=100.0, currency="EUR"))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 10),
                               price=110.0, currency="EUR"))
    await db_session.flush()

    # Query for date between the two entries — should return the earlier one
    result = await get_price_on_date(db_session, ticker, date(2025, 4, 5))
    assert result is not None
    price, _ = result
    assert price == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_get_price_on_date_returns_latest_when_multiple(db_session):
    """Among multiple prices at or before on_date, returns the latest one."""
    suffix = id(db_session)
    ticker = f"GPDLAT.{suffix}"
    await _add_product(db_session, ticker)
    for d, p in [(date(2025, 6, 1), 50.0), (date(2025, 6, 5), 60.0),
                 (date(2025, 6, 10), 70.0)]:
        db_session.add(AssetPrice(ticker=ticker, date=d, price=p,
                                   currency="EUR"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 6, 15))
    assert result is not None
    price, _ = result
    assert price == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_get_price_on_date_no_price_returns_none(db_session):
    suffix = id(db_session)
    ticker = f"GPDNONE.{suffix}"
    await _add_product(db_session, ticker)

    result = await get_price_on_date(db_session, ticker, date(2025, 1, 1))
    assert result is None


@pytest.mark.asyncio
async def test_get_price_on_date_future_date_excluded(db_session):
    """Prices after on_date should not be returned."""
    suffix = id(db_session)
    ticker = f"GPDFUT.{suffix}"
    await _add_product(db_session, ticker)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 12, 31),
                               price=999.0, currency="EUR"))
    await db_session.flush()

    result = await get_price_on_date(db_session, ticker, date(2025, 1, 1))
    assert result is None


# ---------------------------------------------------------------------------
# r2() — ROUND_HALF_UP regression (Python banker's rounding)
# ---------------------------------------------------------------------------

def test_r2_ppfb_de_case():
    """Regression: 547 × 75.875 = 41503.625 must round to 41503.63, not 41503.62.
    Python's round() uses banker's rounding → 41503.62 (rounds to even).
    r2() uses ROUND_HALF_UP → 41503.63 (financial standard)."""
    from app.services.price_service import r2
    assert r2(547 * 75.875) == 41503.63

def test_r2_half_up_always_rounds_away_from_zero():
    from app.services.price_service import r2
    assert r2(0.125) == 0.13   # banker: 0.12 (rounds to even 2)
    assert r2(0.135) == 0.14
    assert r2(0.145) == 0.15   # banker: 0.14 (rounds to even 4)
    assert r2(20857.425) == 20857.43  # banker: 20857.42

def test_r2_normal_cases_unchanged():
    from app.services.price_service import r2
    assert r2(41503.624) == 41503.62
    assert r2(41503.626) == 41503.63
    assert r2(0.0) == 0.0
    assert r2(100.0) == 100.0
