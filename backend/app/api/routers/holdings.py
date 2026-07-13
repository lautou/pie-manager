from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.models import Pool, PoolProduct, AssetPrice, Transaction, Product
from app.services.price_service import _to_eur, r2
from app.services.dashboard_service import (
    _get_latest_prices,
    _get_spot_rates,
    _get_spot_rates_at_date,
    _get_latest_holdings,
)

router = APIRouter(tags=["dashboard"])


class HoldingOut(BaseModel):
    ticker: str
    product_name: str
    category: Optional[str]
    instrument_type: Optional[str] = None
    pool_id: Optional[int]
    pool_name: Optional[str]
    quantity: float
    last_price: float
    last_price_date: Optional[date]
    last_price_source: str
    value_eur: float
    currency: str


@router.get("/holdings", response_model=list[HoldingOut])
async def get_holdings(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Returns all non-zero holdings for the portfolio with latest known price."""
    holdings = await _get_latest_holdings(db, portfolio_id)
    if not holdings:
        return []

    tickers = list(holdings.keys())

    # Latest prices (returns {ticker: (price, currency)})
    prices = await _get_latest_prices(db, tickers)
    spot_rates = await _get_spot_rates(db)

    # Latest price dates + sources (for metadata only — currency already in prices)
    subq = (
        select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
        .where(AssetPrice.ticker.in_(tickers))
        .group_by(AssetPrice.ticker)
        .subquery()
    )
    price_rows_result = await db.execute(
        select(AssetPrice).join(
            subq,
            (AssetPrice.ticker == subq.c.ticker) & (AssetPrice.date == subq.c.max_date),
        )
    )
    price_meta: dict[str, AssetPrice] = {r.ticker: r for r in price_rows_result.scalars().all()}

    # Pool membership
    pools_result = await db.execute(
        select(Pool).where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)  # noqa: E712
    )
    pools = {p.id: p for p in pools_result.scalars().all()}
    pp_result = await db.execute(
        select(PoolProduct).where(PoolProduct.pool_id.in_(pools.keys()))
    )
    ticker_to_pool: dict[str, Pool] = {}
    for pp in pp_result.scalars().all():
        ticker_to_pool[pp.ticker] = pools[pp.pool_id]

    # Product names
    products_result = await db.execute(
        select(Product).where(Product.ticker.in_(tickers))
    )
    product_names: dict[str, Product] = {p.ticker: p for p in products_result.scalars().all()}

    result = []
    for ticker, qty in holdings.items():
        price_tuple = prices.get(ticker)
        pm = price_meta.get(ticker)
        pool = ticker_to_pool.get(ticker)
        prod = product_names.get(ticker)
        native_currency = pm.currency if pm else "EUR"
        native_price = price_tuple[0] if price_tuple else 0.0
        price_currency = price_tuple[1] if price_tuple else "EUR"
        price_eur_unit = _to_eur(native_price, price_currency, spot_rates)
        category = prod.category if prod else ""
        instrument_type = prod.instrument_type if prod else ""
        # Or physique assets (OR.PHYSIQUE): price IS the total value, not per-unit
        value_eur = r2(price_eur_unit) if instrument_type == "Or physique" else r2(qty * price_eur_unit)
        result.append(HoldingOut(
            ticker=ticker,
            product_name=prod.name if prod else ticker,
            category=category or None,
            instrument_type=instrument_type or None,
            pool_id=pool.id if pool else None,
            pool_name=pool.name if pool else None,
            quantity=round(qty, 6),
            last_price=round(native_price, 4),
            last_price_date=pm.date if pm else None,
            last_price_source=pm.source if pm else "unknown",
            value_eur=value_eur,
            currency=native_currency,
        ))

    result.sort(key=lambda x: x.product_name.lower())
    return result


@router.get("/holdings/history", response_model=list[HoldingOut])
async def get_holdings_at_date(
    portfolio_id: int = Query(...),
    snap_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Returns portfolio holdings as they were on snap_date, using prices <= snap_date."""

    # Holdings: sum quantities from all transactions up to snap_date
    tx_result = await db.execute(
        select(Transaction.ticker, func.sum(Transaction.quantity).label("qty"))
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.type == "Actif",
            Transaction.ticker.notin_(["LIQUIDITE.EURO"]),
            Transaction.date <= snap_date,
        )
        .group_by(Transaction.ticker)
        .having(func.sum(Transaction.quantity) != 0)
    )
    raw_holdings = {r.ticker: float(r.qty) for r in tx_result.all()}

    if not raw_holdings:
        return []

    tickers = list(raw_holdings.keys())

    # Prices at or before snap_date (latest known for each ticker)
    price_subq = (
        select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
        .where(AssetPrice.ticker.in_(tickers), AssetPrice.date <= snap_date)
        .group_by(AssetPrice.ticker)
        .subquery()
    )
    price_rows = await db.execute(
        select(AssetPrice).join(
            price_subq,
            (AssetPrice.ticker == price_subq.c.ticker) & (AssetPrice.date == price_subq.c.max_date),
        )
    )
    price_meta: dict[str, AssetPrice] = {r.ticker: r for r in price_rows.scalars().all()}

    # FX rates at or before snap_date for currency conversion
    snap_spot_rates = await _get_spot_rates_at_date(db, snap_date)

    # Pools & products
    pools_result = await db.execute(
        select(Pool).where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)  # noqa: E712
    )
    pools = {p.id: p for p in pools_result.scalars().all()}
    pp_result = await db.execute(
        select(PoolProduct).where(PoolProduct.pool_id.in_(pools.keys()))
    )
    ticker_to_pool: dict[str, Pool] = {}
    for pp in pp_result.scalars().all():
        ticker_to_pool[pp.ticker] = pools[pp.pool_id]

    products_result = await db.execute(
        select(Product).where(Product.ticker.in_(tickers))
    )
    product_map: dict[str, Product] = {p.ticker: p for p in products_result.scalars().all()}

    result = []
    for ticker, raw_qty in raw_holdings.items():
        prod = product_map.get(ticker)
        category = prod.category if prod else ""
        instrument_type = prod.instrument_type if prod else ""
        pm = price_meta.get(ticker)
        native_price = pm.price if pm else 0.0
        price_currency = pm.currency if pm else "EUR"
        price_eur = _to_eur(native_price, price_currency, snap_spot_rates)
        pool = ticker_to_pool.get(ticker)

        if instrument_type == "Cash":
            held = max(0.0, raw_qty)
        else:
            held = max(0.0, -raw_qty)

        if held == 0 and instrument_type != "Or physique":
            continue

        value_eur = r2(price_eur) if instrument_type == "Or physique" else r2(held * price_eur)
        if value_eur <= 0:
            continue

        result.append(HoldingOut(
            ticker=ticker,
            product_name=prod.name if prod else ticker,
            category=category or None,
            instrument_type=instrument_type or None,
            pool_id=pool.id if pool else None,
            pool_name=pool.name if pool else None,
            quantity=round(held, 6),
            last_price=round(native_price, 4),
            last_price_date=pm.date if pm else None,
            last_price_source=pm.source if pm else "unknown",
            value_eur=value_eur,
            currency=price_currency,
        ))

    result.sort(key=lambda x: x.product_name.lower())
    return result


class HoldingValueEntry(BaseModel):
    ticker: str
    product_name: str
    value_eur: float
    unit_price: float  # price per unit — used for price-performance index (not qty-inflated)


class DailyHoldingValuesOut(BaseModel):
    date: date
    holdings: list[HoldingValueEntry]


@router.get("/daily-holding-values", response_model=list[DailyHoldingValuesOut])
async def get_daily_holding_values(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    For each business day from the earliest transaction to today, returns the
    EUR value of every non-cash holding using the most recent price at or before
    that date.  Result is downsampled to <=500 data points.
    """
    from datetime import date as date_cls, timedelta

    # 1. All tickers held (non-cash, non-LIQUIDITE) with at least one transaction
    tickers_result = await db.execute(
        select(Transaction.ticker, Product.name, Product.instrument_type)
        .join(Product, Transaction.ticker == Product.ticker)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.type == "Actif",
            Transaction.ticker != "LIQUIDITE.EURO",
        )
        .distinct()
    )
    ticker_rows = tickers_result.all()
    if not ticker_rows:
        return []

    tickers = [r.ticker for r in ticker_rows]
    product_names: dict[str, str] = {r.ticker: r.name for r in ticker_rows}
    product_instrument_types: dict[str, str] = {r.ticker: r.instrument_type for r in ticker_rows}

    # 2. Earliest transaction date
    from sqlalchemy import func as sa_func
    earliest_result = await db.execute(
        select(sa_func.min(Transaction.date))
        .where(Transaction.portfolio_id == portfolio_id, Transaction.type == "Actif")
    )
    earliest_date: date_cls | None = earliest_result.scalar_one_or_none()
    if not earliest_date:  # pragma: no cover — dead code: ticker_rows non-empty guarantees min(date) is non-None
        return []

    today = date_cls.today()

    # 3. All business days (Monday-Friday) from earliest_date to today
    all_days: list[date_cls] = []
    current = earliest_date
    while current <= today:
        if current.weekday() < 5:
            all_days.append(current)
        current += timedelta(days=1)

    if not all_days:
        return []

    # 4. Downsample to <=500 data points
    max_pts = 500
    if len(all_days) > max_pts:
        step = len(all_days) / max_pts
        sampled_days = [all_days[int(i * step)] for i in range(max_pts)]
        if all_days[-1] not in sampled_days:  # pragma: no branch
            sampled_days.append(all_days[-1])
    else:
        sampled_days = all_days

    # 5. All transactions ordered by date — to cumulate quantities per ticker
    tx_result = await db.execute(
        select(Transaction.date, Transaction.ticker, Transaction.quantity)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.type == "Actif",
            Transaction.ticker.in_(tickers),
        )
        .order_by(Transaction.date.asc())
    )
    all_tx = tx_result.all()

    # Pre-group transactions by date for scanning
    from collections import defaultdict
    tx_by_date: dict[date_cls, list[tuple[str, float]]] = defaultdict(list)
    for row in all_tx:
        tx_by_date[row.date].append((row.ticker, float(row.quantity)))

    # 6. All prices for these tickers in the date range (one fetch)
    prices_result = await db.execute(
        select(AssetPrice.date, AssetPrice.ticker, AssetPrice.price, AssetPrice.currency)
        .where(
            AssetPrice.ticker.in_(tickers),
            AssetPrice.date >= earliest_date,
            AssetPrice.date <= today,
        )
        .order_by(AssetPrice.date.asc())
    )
    # Build: price_history[ticker] = sorted list of (date, price, currency)
    price_history: dict[str, list[tuple[date_cls, float, str]]] = defaultdict(list)
    for row in prices_result.all():
        price_history[row.ticker].append((row.date, row.price, row.currency))

    # FX spot rates for currency conversion (latest available)
    spot_rates_dhv = await _get_spot_rates(db)

    # Pointer per ticker for O(n) price lookups as we walk forward in time
    price_ptr: dict[str, int] = {t: 0 for t in tickers}
    latest_price: dict[str, float] = {t: 0.0 for t in tickers}
    latest_price_currency: dict[str, str] = {t: "EUR" for t in tickers}

    def advance_prices(up_to: date_cls) -> None:
        for ticker in tickers:
            hist = price_history.get(ticker, [])
            ptr = price_ptr[ticker]
            while ptr < len(hist) and hist[ptr][0] <= up_to:
                latest_price[ticker] = hist[ptr][1]
                latest_price_currency[ticker] = hist[ptr][2]
                ptr += 1
            price_ptr[ticker] = ptr

    # 7. Walk through sampled days, maintaining running quantity per ticker
    cumulative_qty: dict[str, float] = {t: 0.0 for t in tickers}

    # Build a sorted list of all transaction dates for efficient scanning
    all_tx_dates = sorted(tx_by_date.keys())
    tx_date_ptr = 0

    out: list[DailyHoldingValuesOut] = []

    for day in sampled_days:
        # Apply all transactions up to and including this day
        while tx_date_ptr < len(all_tx_dates) and all_tx_dates[tx_date_ptr] <= day:
            tx_date = all_tx_dates[tx_date_ptr]
            for ticker, qty in tx_by_date[tx_date]:
                cumulative_qty[ticker] = cumulative_qty.get(ticker, 0.0) + qty
            tx_date_ptr += 1

        # Advance price pointers to this day
        advance_prices(day)

        day_holdings: list[HoldingValueEntry] = []
        for ticker in tickers:
            raw_qty = cumulative_qty.get(ticker, 0.0)
            instrument_type = product_instrument_types.get(ticker, "")
            native_price = latest_price.get(ticker, 0.0)
            price_cur = latest_price_currency.get(ticker, "EUR")
            price = _to_eur(native_price, price_cur, spot_rates_dhv)

            if instrument_type == "Cash":
                held = max(0.0, raw_qty)
            elif instrument_type == "Or physique":
                held = abs(raw_qty) if raw_qty != 0 else 0.0
            else:
                held = max(0.0, -raw_qty)

            if instrument_type == "Or physique":
                value_eur = price if held > 0 else 0.0
            else:
                value_eur = r2(held * price)

            if value_eur > 0:
                day_holdings.append(HoldingValueEntry(
                    ticker=ticker,
                    product_name=product_names.get(ticker, ticker),
                    value_eur=value_eur,
                    unit_price=round(native_price, 4),
                ))

        if day_holdings:
            out.append(DailyHoldingValuesOut(date=day, holdings=day_holdings))

    return out
