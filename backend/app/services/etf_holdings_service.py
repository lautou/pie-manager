# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ETF look-through holdings: DB-only helpers (no HTTP) for storing Yahoo Finance's top-10
holdings/sector-weightings data and aggregating it into a pool-wide sector/company allocation.

Split from app/tasks/etf_holdings.py the same way price_service.py is split from
tasks/prices.py: this module owns DB reads/writes and business logic, the task module owns
the Yahoo session/HTTP fetching and PgQueuer scheduling.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EtfHolding, EtfSectorWeighting, Pool, PoolProduct, Product
from app.services.dashboard_service import get_holdings, _get_latest_prices, _get_spot_rates
from app.services.price_service import _to_eur, r2

# Sentinel key for the "beyond the top-10" remainder in a pool's by-company allocation.
OTHER_KEY = "__OTHER__"

# A fund's top-10 weights summing to at least this much is treated as "fully covered" —
# below it, the remainder is surfaced as an explicit OTHER_KEY bucket.
_FULL_COVERAGE_THRESHOLD = 0.999


async def get_etf_tickers(db: AsyncSession) -> list[str]:
    """Tickers eligible for a top-10-holdings fetch (ETFs and SICAV/FCP funds)."""
    result = await db.execute(
        select(Product.ticker).where(Product.instrument_type.in_(["ETF", "SICAV/FCP"]))
    )
    return [row[0] for row in result.all()]


async def get_direct_stock_tickers_in_etf_pools(db: AsyncSession) -> list[tuple[str, str]]:
    """
    Directly held stocks (instrument_type='Action') that belong to a pool which also
    contains at least one ETF/SICAV-FCP fund — i.e. a pool where look-through aggregation
    is meaningful (Asie/Energie today). These get a synthetic self-row instead of a
    top-10-holdings fetch, via assetProfile.sectorKey — see app/tasks/etf_holdings.py.

    Returns [(ticker, product_name), ...] — the name is needed for the synthetic self-row's
    holding_name (there is no separate "top holding" name to fetch for a direct stock).
    """
    etf_pool_ids_result = await db.execute(
        select(PoolProduct.pool_id)
        .join(Product, Product.ticker == PoolProduct.ticker)
        .where(Product.instrument_type.in_(["ETF", "SICAV/FCP"]))
        .distinct()
    )
    etf_pool_ids = [row[0] for row in etf_pool_ids_result.all()]
    if not etf_pool_ids:
        return []

    result = await db.execute(
        select(PoolProduct.ticker, Product.name)
        .join(Product, Product.ticker == PoolProduct.ticker)
        .where(Product.instrument_type == "Action", PoolProduct.pool_id.in_(etf_pool_ids))
        .distinct()
    )
    return [(row[0], row[1]) for row in result.all()]


async def replace_etf_holdings(db: AsyncSession, parent_ticker: str, holdings: list[dict]) -> None:
    """
    Replace all etf_holdings rows for parent_ticker with the given snapshot.

    holdings: [{"ticker": str, "name": str, "weight_pct": float}, ...]. Yahoo always returns
    a full top-10 snapshot (never a diff), so delete-then-reinsert is correct and simplest.
    Does not commit — caller controls the transaction.
    """
    await db.execute(delete(EtfHolding).where(EtfHolding.parent_ticker == parent_ticker))
    for h in holdings:
        db.add(EtfHolding(
            parent_ticker=parent_ticker,
            holding_ticker=h["ticker"],
            holding_name=h["name"],
            weight_pct=h["weight_pct"],
        ))


async def replace_sector_weightings(db: AsyncSession, parent_ticker: str, weightings: dict[str, float]) -> None:
    """
    Replace all etf_sector_weightings rows for parent_ticker with the given snapshot.

    weightings: {sector_key: weight_pct} — sector_key is the raw lowercase Yahoo key (e.g.
    "energy"), never the capitalized display form. Does not commit.
    """
    await db.execute(delete(EtfSectorWeighting).where(EtfSectorWeighting.parent_ticker == parent_ticker))
    for sector, pct in weightings.items():
        db.add(EtfSectorWeighting(parent_ticker=parent_ticker, sector=sector, weight_pct=pct))


async def save_etf_fetch_result(
    db: AsyncSession,
    ticker: str,
    holdings: list[dict],
    sector_weightings: dict[str, float],
    fetched_at: datetime,
    bond_duration: Optional[float] = None,
    bond_maturity: Optional[float] = None,
) -> None:
    """Apply one ticker's fetch result: holdings + sectors + bond metrics + freshness marker."""
    await replace_etf_holdings(db, ticker, holdings)
    await replace_sector_weightings(db, ticker, sector_weightings)
    # holdings_updated_at is stored as naive UTC (column has no timezone) — normalize here so
    # every caller (task, tests) can pass either a naive or tz-aware datetime freely.
    if fetched_at.tzinfo is not None:
        fetched_at = fetched_at.astimezone(timezone.utc).replace(tzinfo=None)
    await db.execute(
        Product.__table__.update()
        .where(Product.ticker == ticker)
        .values(
            bond_duration=bond_duration,
            bond_maturity=bond_maturity,
            holdings_updated_at=fetched_at,
        )
    )


async def get_composition(db: AsyncSession, ticker: str) -> Optional[dict]:
    """
    Single-ticker composition read for the "click a ticker" modal.

    Returns None if the product doesn't exist. Returns empty holdings/sectors (not None) if
    the product exists but has no fetched composition yet (e.g. gold ETC, not yet synced).
    """
    product = await db.get(Product, ticker)
    if product is None:
        return None

    holdings_result = await db.execute(
        select(EtfHolding).where(EtfHolding.parent_ticker == ticker).order_by(EtfHolding.weight_pct.desc())
    )
    holdings = holdings_result.scalars().all()
    sectors_result = await db.execute(
        select(EtfSectorWeighting)
        .where(EtfSectorWeighting.parent_ticker == ticker)
        .order_by(EtfSectorWeighting.weight_pct.desc())
    )
    sectors = sectors_result.scalars().all()

    return {
        "ticker": ticker,
        "name": product.name,
        "top_holdings": [
            {"ticker": h.holding_ticker, "name": h.holding_name, "weight_pct": h.weight_pct}
            for h in holdings
        ],
        "top_holdings_coverage_pct": r2(sum(h.weight_pct for h in holdings) * 100),
        "sector_weightings": [{"sector": s.sector, "weight_pct": s.weight_pct} for s in sectors],
        "bond_duration": product.bond_duration,
        "bond_maturity": product.bond_maturity,
        "holdings_updated_at": product.holdings_updated_at,
    }


async def compute_pool_lookthrough(db: AsyncSession, portfolio_id: int, pool_id: int) -> Optional[dict]:
    """
    Look-through sector/company allocation for one pool.

    Every position in the pool — ETF or direct stock, no special-casing — feeds the same
    by_company/by_sector accumulators keyed by underlying ticker/sector. This is what merges
    any number of overlapping sources automatically: a stock held directly AND inside an ETF,
    or the same company found in several different ETFs in the pool with no direct position
    at all (e.g. Tencent inside 3 separate Asie-pool ETFs).

    Returns None if the pool doesn't exist or doesn't belong to portfolio_id.
    """
    pool = await db.get(Pool, pool_id)
    if pool is None or pool.portfolio_id != portfolio_id:
        return None

    pp_result = await db.execute(select(PoolProduct.ticker).where(PoolProduct.pool_id == pool_id))
    pool_tickers = [row[0] for row in pp_result.all()]

    empty_result = {
        "pool_id": pool_id,
        "pool_name": pool.name,
        "total_eur": 0.0,
        "by_sector": [],
        "by_company": [],
        "unclassified_eur": 0.0,
        "unclassified_pct": 0.0,
        "holdings_updated_at": None,
    }
    if not pool_tickers:
        return empty_result

    positions = await get_holdings(db, portfolio_id)
    relevant_tickers = [t for t in pool_tickers if positions.get(t, 0.0) > 0]
    if not relevant_tickers:
        return empty_result

    products_result = await db.execute(select(Product).where(Product.ticker.in_(relevant_tickers)))
    product_by_ticker = {p.ticker: p for p in products_result.scalars().all()}

    prices = await _get_latest_prices(db, relevant_tickers)
    spot_rates = await _get_spot_rates(db)

    position_values: dict[str, float] = {}
    for ticker in relevant_tickers:
        product = product_by_ticker.get(ticker)
        instrument_type = product.instrument_type if product else None
        if instrument_type in ("Cash", "Or physique"):
            continue  # no meaningful sector/company composition for these
        price_tuple = prices.get(ticker)
        if price_tuple is None:
            continue
        price, price_currency = price_tuple
        price_eur = _to_eur(price, price_currency, spot_rates)
        value_eur = r2(positions[ticker] * price_eur)
        if value_eur > 0:
            position_values[ticker] = value_eur

    total_eur = r2(sum(position_values.values()))
    if total_eur <= 0:
        return empty_result

    holdings_result = await db.execute(
        select(EtfHolding).where(EtfHolding.parent_ticker.in_(position_values.keys()))
    )
    holdings_by_parent: dict[str, list[EtfHolding]] = defaultdict(list)
    for h in holdings_result.scalars().all():
        holdings_by_parent[h.parent_ticker].append(h)

    sectors_result = await db.execute(
        select(EtfSectorWeighting).where(EtfSectorWeighting.parent_ticker.in_(position_values.keys()))
    )
    sectors_by_parent: dict[str, list[EtfSectorWeighting]] = defaultdict(list)
    for s in sectors_result.scalars().all():
        sectors_by_parent[s.parent_ticker].append(s)

    by_company: dict[str, dict] = {}
    by_sector: dict[str, dict] = {}
    unclassified_eur = 0.0

    for ticker, value_eur in position_values.items():
        h_rows = holdings_by_parent.get(ticker, [])
        s_rows = sectors_by_parent.get(ticker, [])
        if not h_rows and not s_rows:
            unclassified_eur += value_eur
            continue

        for h in h_rows:
            entry = by_company.setdefault(h.holding_ticker, {"label": h.holding_name, "value_eur": 0.0})
            entry["value_eur"] += value_eur * h.weight_pct
        covered = sum(h.weight_pct for h in h_rows)
        if h_rows and covered < _FULL_COVERAGE_THRESHOLD:
            entry = by_company.setdefault(OTHER_KEY, {"label": OTHER_KEY, "value_eur": 0.0})
            entry["value_eur"] += value_eur * (1.0 - covered)

        for s in s_rows:
            entry = by_sector.setdefault(s.sector, {"label": s.sector, "value_eur": 0.0})
            entry["value_eur"] += value_eur * s.weight_pct

    updated_dates = [
        product_by_ticker[t].holdings_updated_at
        for t in position_values
        if product_by_ticker.get(t) and product_by_ticker[t].holdings_updated_at is not None
    ]

    # total_eur > 0 is guaranteed here (checked above), so every pct below is a plain division.
    def _to_sorted_entries(raw: dict[str, dict], *, last_key: Optional[str] = None) -> list[dict]:
        """Sort by value_eur descending; last_key (e.g. OTHER_KEY) always sorts last regardless
        of its value, since it's a residual/catch-all bucket rather than a real entity to rank."""
        pinned_last = raw.pop(last_key, None) if last_key else None
        entries = sorted(raw.items(), key=lambda kv: kv[1]["value_eur"], reverse=True)
        if pinned_last is not None:
            entries.append((last_key, pinned_last))
        return [
            {
                "key": key,
                "label": data["label"],
                "value_eur": r2(data["value_eur"]),
                "pct": r2(data["value_eur"] / total_eur * 100),
            }
            for key, data in entries
        ]

    return {
        "pool_id": pool_id,
        "pool_name": pool.name,
        "total_eur": total_eur,
        "by_sector": _to_sorted_entries(by_sector),
        "by_company": _to_sorted_entries(by_company, last_key=OTHER_KEY),
        "unclassified_eur": r2(unclassified_eur),
        "unclassified_pct": r2(unclassified_eur / total_eur * 100),
        "holdings_updated_at": min(updated_dates) if updated_dates else None,
    }
