# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sector/commodity performance leaderboard: DB-only helpers (no HTTP) for the fixed 4-row
sector universe CRUD and its trailing-1-year, EUR-adjusted performance, shown as the single
bar chart on the "Performance par secteur" tab of the Indicateurs page.

Full CRUD mirror of country_performance_service.py (a deliberate choice over a hardcoded
constant) — the only structural difference is the absence of any Top-N/ranking concept:
there are only ever as many bars as there are configured rows (4 by default), so this module
never truncates or re-sorts beyond a single ascending sort for left-to-right chart display.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sector_performance import SectorPerfConfig
from app.services.macro_series_price_service import get_series
from app.services.performance_math import ASOF_TOLERANCE_DAYS, TRAILING_WINDOW_DAYS, compute_trailing_performance

# Sector codes are lowercase French-word slugs (e.g. "agriculture"), not ISO codes — wider
# than country_performance_service's 2-3 char regex, matching the model's String(20).
_SECTOR_CODE_RE = re.compile(r"^[a-z]{2,20}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Sector CRUD — user-managed universe
# ---------------------------------------------------------------------------

async def list_sector_configs(db: AsyncSession) -> list[SectorPerfConfig]:
    result = await db.execute(select(SectorPerfConfig).order_by(SectorPerfConfig.code))
    return list(result.scalars().all())


async def create_sector_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> SectorPerfConfig:
    """Raises ValueError (client-facing message) on an invalid code/currency or a duplicate."""
    if not _SECTOR_CODE_RE.match(code):
        raise ValueError(f"Invalid sector code: {code!r} (lowercase letters, 2-20 chars)")
    if not _CURRENCY_RE.match(currency):
        raise ValueError(f"Invalid currency: {currency!r} (uppercase ISO 4217, 3 letters)")
    if await db.get(SectorPerfConfig, code) is not None:
        raise ValueError(f"Sector '{code}' already exists")
    sector = SectorPerfConfig(
        code=code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )
    db.add(sector)
    await db.commit()
    await db.refresh(sector)
    return sector


async def update_sector_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> Optional[SectorPerfConfig]:
    """`code` is immutable — it's the macro_series_prices series-key suffix. Returns None if
    the sector doesn't exist. Raises ValueError on an invalid currency."""
    sector = await db.get(SectorPerfConfig, code)
    if sector is None:
        return None
    if not _CURRENCY_RE.match(currency):
        raise ValueError(f"Invalid currency: {currency!r} (uppercase ISO 4217, 3 letters)")
    sector.label = label
    sector.index_ticker = index_ticker
    sector.currency = currency
    sector.index_label = index_label
    await db.commit()
    await db.refresh(sector)
    return sector


async def delete_sector_config(db: AsyncSession, code: str) -> Optional[bool]:
    """Returns None if the sector doesn't exist, True on success. No 'last remaining row'
    guard, same as CountryPerfConfig — an emptied-out universe simply yields an empty chart."""
    sector = await db.get(SectorPerfConfig, code)
    if sector is None:
        return None
    await db.delete(sector)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

@dataclass
class SectorPerformanceResult:
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: date
    anchor_date: date
    index_label: str


async def compute_sector_performance(db: AsyncSession) -> list[SectorPerformanceResult]:
    """
    Trailing-1-year, EUR-adjusted performance for every configured sector row — no Top-N
    truncation (only ever a handful of rows), sorted ascending for the bar chart's
    left-to-right display. A row with insufficient/stale index or FX history is excluded
    rather than distorting the chart with a guessed value. See performance_math.py for the
    shared per-row math this delegates to.
    """
    configs = await list_sector_configs(db)
    if not configs:
        return []

    today = date.today()
    anchor_target = today - timedelta(days=TRAILING_WINDOW_DAYS)
    fx_cache: dict[str, dict[date, float]] = {}
    results: list[SectorPerformanceResult] = []

    for cfg in configs:
        index_series = await get_series(db, f"sector_{cfg.code}_equity")

        fx_series = None
        if cfg.currency != "EUR":
            if cfg.currency not in fx_cache:
                fx_cache[cfg.currency] = await get_series(db, f"fx_{cfg.currency.lower()}")
            fx_series = fx_cache[cfg.currency]

        perf = compute_trailing_performance(index_series, fx_series, today, anchor_target, ASOF_TOLERANCE_DAYS)
        if perf is None:
            continue

        results.append(SectorPerformanceResult(
            code=cfg.code, label=cfg.label, currency=cfg.currency,
            perf_pct=perf.perf_pct, latest_date=perf.latest_date, anchor_date=perf.anchor_date,
            index_label=cfg.index_label,
        ))

    results.sort(key=lambda r: r.perf_pct)  # ascending only — no Top-N to select first
    return results
