# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import AssetPrice
from app.models.product import Product


def r2(val: float) -> float:
    """Round to 2 decimal places using ROUND_HALF_UP (financial standard).

    Python's built-in round() uses banker's rounding (IEEE 754 half-to-even),
    which rounds 41503.625 → 41503.62 instead of 41503.63.
    This function always rounds .5 away from zero, as expected for monetary amounts.
    """
    return float(Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def get_active_tickers(db: AsyncSession) -> list[tuple[str, str]]:
    """Returns list of (ticker, currency) for non-manual, non-fee products."""
    result = await db.execute(
        select(Product.ticker, Product.currency).where(
            Product.category != "Frais",
            or_(Product.instrument_type != "Or physique", Product.instrument_type.is_(None)),
        )
    )
    tickers = []
    for ticker, currency in result.all():
        tickers.append((ticker, currency))
    return tickers


async def upsert_price(
    db: AsyncSession,
    ticker: str,
    date: date,
    price: float,
    currency: str,
    source: str = "yfinance",
) -> None:
    stmt = insert(AssetPrice).values(
        ticker=ticker, date=date, price=price, currency=currency, source=source
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_asset_price_ticker_date",
        set_={"price": price, "source": source},
    )
    await db.execute(stmt)


async def get_price_on_date(
    db: AsyncSession, ticker: str, on_date: date
) -> tuple[float, str] | None:
    """Returns (price, currency) for the most recent price at or before on_date, or None."""
    result = await db.execute(
        select(AssetPrice.price, AssetPrice.currency)
        .where(AssetPrice.ticker == ticker, AssetPrice.date <= on_date)
        .order_by(AssetPrice.date.desc())
        .limit(1)
    )
    row = result.one_or_none()
    return (row.price, row.currency) if row else None


def held_quantity(raw_qty: float, instrument_type: str | None) -> float:
    """Convert a raw (signed) summed transaction quantity into a non-negative "units held"
    figure, per this app's sign convention: Cash instruments accumulate positive on deposit
    (raw_qty already means "held"), everything else accumulates negative on buy (so
    held = -raw_qty)."""
    return max(0.0, raw_qty) if instrument_type == "Cash" else max(0.0, -raw_qty)


def _to_eur(price: float, currency: str, spot_rates: dict[str, float]) -> float:
    """Convert a price to EUR using known spot rates (from asset_prices for forex tickers).

    Handles GBp (pence) → GBP → EUR conversion automatically.
    Falls back to returning the price unchanged if no rate is available (logs no warning
    at import time; callers should log when rate is missing).
    """
    if currency == "EUR":
        return price
    if currency == "GBp":
        # London Stock Exchange quotes in pence; convert to pounds first
        price = price / 100.0
        currency = "GBP"
    rate_key = f"{currency}EUR=X"
    rate = spot_rates.get(rate_key)
    if rate is not None:
        return price * rate
    # No conversion rate available — return as-is (caller should log a warning)
    return price
