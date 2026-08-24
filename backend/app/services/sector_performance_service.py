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

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sector_performance import SectorPerfConfig
from app.services.code_keyed_crud import make_code_keyed_crud
from app.services.macro_series_price_service import get_series
from app.services.performance_math import ASOF_TOLERANCE_DAYS, TRAILING_WINDOW_DAYS, compute_trailing_performance

# Sector codes are lowercase French-word slugs (e.g. "agriculture"), not ISO codes — wider
# than country_performance_service's 2-3 char regex, matching the model's String(20).
_SECTOR_CODE_RE = re.compile(r"^[a-z]{2,20}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Sector CRUD — user-managed universe. No "last remaining row" guard, same as
# CountryPerfConfig — an emptied-out universe simply yields an empty chart.
# ---------------------------------------------------------------------------

_sector_crud = make_code_keyed_crud(
    model_cls=SectorPerfConfig,
    code_re=_SECTOR_CODE_RE,
    invalid_code_message=lambda code: f"Invalid sector code: {code!r} (lowercase letters, 2-20 chars)",
    duplicate_message=lambda code: f"Sector '{code}' already exists",
    field_validators={
        "currency": (_CURRENCY_RE, lambda v: f"Invalid currency: {v!r} (uppercase ISO 4217, 3 letters)"),
    },
)


async def list_sector_configs(db: AsyncSession) -> list[SectorPerfConfig]:
    return await _sector_crud.list(db)


async def create_sector_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> SectorPerfConfig:
    return await _sector_crud.create(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def update_sector_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> Optional[SectorPerfConfig]:
    """`code` is immutable — it's the macro_series_prices series-key suffix."""
    return await _sector_crud.update(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def delete_sector_config(db: AsyncSession, code: str) -> Optional[bool]:
    return await _sector_crud.delete(db, code)


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
