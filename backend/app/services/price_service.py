# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import AssetPrice
from app.models.product import Product
from app.models.transaction import Transaction


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


async def get_forex_fee_adjustments(
    db: AsyncSession,
    portfolio_id: int,
    held_tickers: list[str],
    as_of: Optional[date] = None,
    group_by_account: bool = False,
) -> dict:
    """Returns the EUR-independent fee amount to add to each held Cash/forex position, for
    fees paid in that position's own currency — e.g. FRAIS.COURTAGE.JPY (type=Frais,
    currency=JPY, total_amount=-165) reduces the JPYEUR=X position; its quantity=-1 is a
    fee-event count, not JPY units, so total_amount carries the real deduction.

    Only Product.instrument_type == 'Cash' tickers are matched — a foreign-currency
    equity/ETF must never be adjusted just because its currency happens to match a fee's
    currency (that would subtract a EUR/USD/... fee amount from a *share count*).

    Returns {ticker: adjustment} normally, or {(account_id, ticker): adjustment} when
    group_by_account=True (fees are matched to the position in the *same* account, never
    pooled across accounts). Callers are responsible for applying the adjustment to their
    own holdings dict (each has a different shape/timing relative to held_quantity()) — this
    function only computes the amounts.
    """
    if not held_tickers:
        return {}

    ticker_clauses = [
        Transaction.portfolio_id == portfolio_id,
        Transaction.ticker.in_(held_tickers),
        Transaction.type == "Actif",
        Transaction.currency != "EUR",
    ]
    if as_of is not None:
        ticker_clauses.append(Transaction.date <= as_of)

    ticker_columns = [Transaction.ticker, Transaction.currency]
    if group_by_account:
        ticker_columns.insert(0, Transaction.account_id)

    ticker_rows = (await db.execute(
        select(*ticker_columns)
        .join(Product, Transaction.ticker == Product.ticker)
        .where(*ticker_clauses, Product.instrument_type == "Cash")
        .distinct()
    )).all()
    if not ticker_rows:
        return {}

    foreign_currencies = list({r.currency for r in ticker_rows})

    fee_clauses = [
        Transaction.portfolio_id == portfolio_id,
        Transaction.type == "Frais",
        Transaction.currency.in_(foreign_currencies),
    ]
    if as_of is not None:
        fee_clauses.append(Transaction.date <= as_of)

    fee_columns = [Transaction.currency, func.sum(Transaction.total_amount).label("adj")]
    fee_group_by = [Transaction.currency]
    if group_by_account:
        fee_columns.insert(0, Transaction.account_id)
        fee_group_by.insert(0, Transaction.account_id)

    fee_rows = (await db.execute(
        select(*fee_columns).where(*fee_clauses).group_by(*fee_group_by)
    )).all()

    if group_by_account:
        fee_by_key = {(r.account_id, r.currency): float(r.adj or 0) for r in fee_rows}
        return {
            (r.account_id, r.ticker): fee_by_key.get((r.account_id, r.currency), 0.0)
            for r in ticker_rows
        }
    fee_by_currency = {r.currency: float(r.adj or 0) for r in fee_rows}
    return {r.ticker: fee_by_currency.get(r.currency, 0.0) for r in ticker_rows}


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
