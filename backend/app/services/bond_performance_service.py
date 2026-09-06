# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sovereign bond market performance leaderboard: DB-only helpers (no HTTP) for the curated
bond-market universe CRUD and the trailing-1-year, EUR-adjusted performance shown on the
"Performance obligataire" tab of the Indicateurs page.

Structurally identical to sector_performance_service.py: no Top-N truncation (the universe
is already curated down to countries with confirmed working Yahoo price history — see
.claude/rules/macro-indicators.md's "Sovereign bond performance" section), every configured
row that has valid data is returned, sorted ascending for the chart's left-to-right display.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bond_performance import BondPerfConfig
from app.services.code_keyed_crud import make_code_keyed_crud
from app.services.macro_series_price_service import get_series
from app.services.performance_math import ASOF_TOLERANCE_DAYS, TRAILING_WINDOW_DAYS, compute_trailing_performance

_BOND_CODE_RE = re.compile(r"^[a-z]{2,3}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Bond-market CRUD — user-managed leaderboard universe. No "last remaining row" guard,
# same as CountryPerfConfig/SectorPerfConfig — an emptied-out universe simply yields an
# empty chart, a valid (if degenerate) state.
# ---------------------------------------------------------------------------

_bond_crud = make_code_keyed_crud(
    model_cls=BondPerfConfig,
    code_re=_BOND_CODE_RE,
    invalid_code_message=lambda code: f"Invalid country code: {code!r} (lowercase letters, 2-3 chars)",
    duplicate_message=lambda code: f"Country '{code}' already exists",
    field_validators={
        "currency": (_CURRENCY_RE, lambda v: f"Invalid currency: {v!r} (uppercase ISO 4217, 3 letters)"),
    },
)


async def list_bond_configs(db: AsyncSession) -> list[BondPerfConfig]:
    return await _bond_crud.list(db)


async def create_bond_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> BondPerfConfig:
    return await _bond_crud.create(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def update_bond_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> Optional[BondPerfConfig]:
    """`code` is immutable — it's the macro_series_prices series-key suffix."""
    return await _bond_crud.update(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def delete_bond_config(db: AsyncSession, code: str) -> Optional[bool]:
    return await _bond_crud.delete(db, code)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

@dataclass
class BondPerformanceResult:
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: date
    anchor_date: date
    index_label: str


async def compute_bond_performance(db: AsyncSession) -> list[BondPerformanceResult]:
    """
    Trailing-1-year, EUR-adjusted performance for every configured bond-market row — no
    Top-N truncation, sorted ascending for the bar chart's left-to-right display. A row with
    insufficient/stale price or FX history is excluded rather than distorting the chart with
    a guessed value. See performance_math.py for the shared per-row math this delegates to.
    """
    configs = await list_bond_configs(db)
    if not configs:
        return []

    today = date.today()
    anchor_target = today - timedelta(days=TRAILING_WINDOW_DAYS)
    fx_cache: dict[str, dict[date, float]] = {}
    results: list[BondPerformanceResult] = []

    for cfg in configs:
        price_series = await get_series(db, f"bond_{cfg.code}_govt")

        fx_series = None
        if cfg.currency != "EUR":
            if cfg.currency not in fx_cache:
                fx_cache[cfg.currency] = await get_series(db, f"fx_{cfg.currency.lower()}")
            fx_series = fx_cache[cfg.currency]

        perf = compute_trailing_performance(price_series, fx_series, today, anchor_target, ASOF_TOLERANCE_DAYS)
        if perf is None:
            continue

        results.append(BondPerformanceResult(
            code=cfg.code, label=cfg.label, currency=cfg.currency,
            perf_pct=perf.perf_pct, latest_date=perf.latest_date, anchor_date=perf.anchor_date,
            index_label=cfg.index_label,
        ))

    results.sort(key=lambda r: r.perf_pct)  # ascending only — no Top-N to select first
    return results
