# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Equity risk premium leaderboard: DB-only helpers (no HTTP) for the country CRUD and the
implied equity risk premium (Fed Model/Damodaran: earnings yield minus the 10-year
government bond yield) shown as the "Premium action" tab's bar chart on the Indicateurs page.

Unlike country_performance_service.py/sector_performance_service.py, this is a point-in-time
snapshot, not a trailing-window return — there's no anchor date, no FX leg (both legs are
same-country, same-currency dimensionless yields subtracted directly), and no TRAILING_WINDOW_DAYS.
Only `asof()` is reused from performance_math.py (its 3rd consumer).

CRUD mirrors macro_indicators_service.py's MacroRegion shape — including its "last remaining
row" delete guard, unlike CountryPerfConfig/SectorPerfConfig which have none — because an
emptied equity_premium_configs table would make this entire tab permanently blank, closer to
MacroRegion's situation (growth/inflation charts need at least one region) than to the other
two leaderboards (which still show a working, if empty, chart shell).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equity_premium import EquityPremiumConfig
from app.services.code_keyed_crud import make_code_keyed_crud
from app.services.macro_series_price_service import get_series
from app.services.performance_math import ASOF_TOLERANCE_DAYS, asof

# Matches CountryPerfConfig's code shape (2-3 lowercase letters) — country parity with the
# "Performance des actions" leaderboard, not MacroRegion's wider [a-z0-9_]{2,20}.
_PREMIUM_CODE_RE = re.compile(r"^[a-z]{2,3}$")


# ---------------------------------------------------------------------------
# Country CRUD — user-managed equity-risk-premium universe
# ---------------------------------------------------------------------------

_premium_crud = make_code_keyed_crud(
    model_cls=EquityPremiumConfig,
    code_re=_PREMIUM_CODE_RE,
    invalid_code_message=lambda code: f"Invalid country code: {code!r} (lowercase letters, 2-3 chars)",
    duplicate_message=lambda code: f"Country '{code}' already exists",
    last_row_guard_message="Cannot delete the last remaining equity premium country",
)


async def list_premium_configs(db: AsyncSession) -> list[EquityPremiumConfig]:
    return await _premium_crud.list(db)


async def create_premium_config(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> EquityPremiumConfig:
    return await _premium_crud.create(
        db, code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    )


async def update_premium_config(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> Optional[EquityPremiumConfig]:
    """`code` is immutable — it's the macro_series_prices series-key suffix."""
    return await _premium_crud.update(
        db, code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    )


async def delete_premium_config(db: AsyncSession, code: str) -> Optional[bool]:
    """Raises ValueError if it's the last remaining country — the tab must always have at
    least one to show."""
    return await _premium_crud.delete(db, code)


# ---------------------------------------------------------------------------
# Equity risk premium
# ---------------------------------------------------------------------------

@dataclass
class EquityPremiumResult:
    code: str
    label: str
    premium_pct: float
    equity_yield_pct: float
    bond_yield_pct: float
    equity_label: str
    bond_label: str
    asof_date: date


async def compute_equity_premiums(db: AsyncSession) -> list[EquityPremiumResult]:
    """
    Implied equity risk premium for every configured country — no Top-N truncation (only ever
    a handful of rows), sorted ascending for the bar chart's left-to-right display. A country
    missing either leg's snapshot within tolerance is excluded rather than plotting a guessed
    value — this also means a country whose bond leg is currently failing (or one of the
    known-gap countries, if a future contributor adds it) self-heals the moment both legs are
    present again, no special-casing needed.
    """
    configs = await list_premium_configs(db)
    if not configs:
        return []

    today = date.today()
    results: list[EquityPremiumResult] = []

    for cfg in configs:
        equity_series = await get_series(db, f"premium_{cfg.code}_equity_yield")
        bond_series = await get_series(db, f"premium_{cfg.code}_bond_yield")
        equity_latest = asof(equity_series, today, ASOF_TOLERANCE_DAYS)
        bond_latest = asof(bond_series, today, ASOF_TOLERANCE_DAYS)
        if equity_latest is None or bond_latest is None:
            continue

        premium_pct = (equity_latest[1] - bond_latest[1]) * 100
        results.append(EquityPremiumResult(
            code=cfg.code, label=cfg.label, premium_pct=premium_pct,
            equity_yield_pct=equity_latest[1] * 100, bond_yield_pct=bond_latest[1] * 100,
            equity_label=cfg.equity_label, bond_label=cfg.bond_label,
            asof_date=min(equity_latest[0], bond_latest[0]),
        ))

    results.sort(key=lambda r: r.premium_pct)  # ascending only — no Top-N to select first
    return results
