"""
Pool valuation logic shared across dashboard, rebalancing, and snapshot services.

This module centralises the computation of pool EUR values from positions and
prices, eliminating the duplicated loop that previously existed in:
  - app/api/routers/dashboard.py (GET /)
  - app/api/routers/rebalancing.py (POST /rebalancing)
  - app/services/snapshot_service.py (compute_daily_snapshot)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.price_service import _to_eur, get_price_on_date


def compute_pool_values(
    pools: list,
    tickers_by_pool: dict[int, list[str]],
    positions: dict[str, float],
    prices: dict[str, tuple[float, str]],
    spot_rates: dict[str, float],
    product_instrument_types: dict[str, str],
) -> dict[int, float]:
    """
    Compute {pool_id: value_eur} from pre-loaded price and position data.

    Rules:
    - LIQUIDITE.EURO is skipped (tracked separately via account cash balances).
    - Or physique instrument type: price in asset_prices IS the total value of the
      asset (physical gold), not a per-unit price.
    - All other instrument types: value = qty * price_eur.
    - Tickers with no price data are skipped (contribute 0).

    Args:
        pools: List of Pool ORM objects (must have .id attribute).
        tickers_by_pool: {pool_id: [ticker, ...]} mapping.
        positions: {ticker: units_held} as positive numbers.
        prices: {ticker: (price, currency)} — latest prices, pre-loaded.
        spot_rates: {ticker: rate} for forex conversion (e.g. GBPEUR=X).
        product_instrument_types: {ticker: instrument_type} — e.g. "Or physique",
            "ETF", "Cash".

    Returns:
        {pool_id: total_eur_value}
    """
    pool_values: dict[int, float] = {}
    for pool in pools:
        pool_val = 0.0
        for ticker in tickers_by_pool.get(pool.id, []):
            if ticker == "LIQUIDITE.EURO":
                continue  # Liquidity tracked separately via account cash balances
            instrument_type = product_instrument_types.get(ticker, "")
            price_tuple = prices.get(ticker)
            if price_tuple is None:
                continue
            price, price_currency = price_tuple
            price_eur = _to_eur(price, price_currency, spot_rates)
            if instrument_type == "Or physique":
                # Price stores the TOTAL value of the physical asset (not per unit)
                pool_val += price_eur
            else:
                qty = positions.get(ticker, 0.0)
                pool_val += qty * price_eur
        pool_values[pool.id] = pool_val
    return pool_values


async def load_prices_at_date(
    db: AsyncSession,
    tickers: set[str],
    snap_date: date,
) -> dict[str, tuple[float, str]]:
    """
    Load {ticker: (price, currency)} for the given tickers at or before snap_date.

    Used by compute_daily_snapshot to pre-load all prices in a single batch
    before calling compute_pool_values, avoiding one DB round-trip per ticker.
    """
    prices: dict[str, tuple[float, str]] = {}
    for ticker in tickers:
        result = await get_price_on_date(db, ticker, snap_date)
        if result is not None:
            prices[ticker] = result
    return prices
