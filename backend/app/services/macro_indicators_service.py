# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Global macro indicators: DB-only helpers (no HTTP) for storing daily Yahoo Finance series
values and computing the growth (equity/oil) and inflation (government bond/gold) ratio
indicators, per region (US / France / Monde).

Split from app/tasks/macro_indicators.py the same way price_service.py is split from
tasks/prices.py: this module owns DB reads/writes and business logic, the task module owns
the Yahoo HTTP fetching and PgQueuer scheduling.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_indicator import MacroRegion
from app.models.system_setting import SystemSetting
from app.services.macro_series_price_service import get_series

# Regions (US/France/Monde/...) are user-managed rows in `macro_regions` — see the CRUD
# functions below. Only the shared oil/gold pair stays as simple default tickers here.
DEFAULT_TICKERS: dict[str, str] = {
    "oil": "CL=F",    # shared across every region's growth ratio
    "gold": "GC=F",   # shared across every region's inflation ratio
}
# Human-readable names for the shared oil/gold tickers, shown in chart legends instead of
# the raw ticker — same "nothing hardcoded" rule as the tickers: overridable via SystemSetting.
DEFAULT_TICKER_LABELS: dict[str, str] = {
    "oil": "Pétrole (WTI)",
    "gold": "Or",
}
DEFAULT_MA_YEARS = 7.0
_DAYS_PER_YEAR = 365.25
_REGION_CODE_RE = re.compile(r"^[a-z0-9_]{2,20}$")


async def get_macro_settings(db: AsyncSession) -> dict[str, str | float]:
    """Reads the macro.* SystemSetting keys (oil/gold tickers + labels + ma_years), falling
    back to defaults for any that are unset. Used by both the fetch task and the ratio
    computation. Returns e.g. {"oil": "CL=F", "oil_label": "Pétrole (WTI)", ...}."""
    ticker_keys = [f"macro.ticker.{series}" for series in DEFAULT_TICKERS]
    label_keys = [f"macro.ticker.{series}.label" for series in DEFAULT_TICKER_LABELS]
    keys = ticker_keys + label_keys + ["macro.ma_years"]
    result = await db.execute(select(SystemSetting).where(SystemSetting.key.in_(keys)))
    stored = {row.key: row.value for row in result.scalars().all()}

    settings: dict[str, str | float] = {
        series: stored.get(f"macro.ticker.{series}", default)
        for series, default in DEFAULT_TICKERS.items()
    }
    for series, default in DEFAULT_TICKER_LABELS.items():
        settings[f"{series}_label"] = stored.get(f"macro.ticker.{series}.label", default)
    settings["ma_years"] = float(stored.get("macro.ma_years", DEFAULT_MA_YEARS))
    return settings


# ---------------------------------------------------------------------------
# Region CRUD — user-managed growth/inflation regions
# ---------------------------------------------------------------------------

async def list_regions(db: AsyncSession) -> list[MacroRegion]:
    result = await db.execute(select(MacroRegion).order_by(MacroRegion.code))
    return list(result.scalars().all())


async def create_region(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> MacroRegion:
    """Raises ValueError (client-facing message) on an invalid code or a duplicate."""
    if not _REGION_CODE_RE.match(code):
        raise ValueError(f"Invalid region code: {code!r} (lowercase letters/digits/underscore, 2-20 chars)")
    if await db.get(MacroRegion, code) is not None:
        raise ValueError(f"Region '{code}' already exists")
    region = MacroRegion(
        code=code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    )
    db.add(region)
    await db.commit()
    await db.refresh(region)
    return region


async def update_region(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> Optional[MacroRegion]:
    """`code` is immutable — it's the macro_series_prices series-key prefix. Returns None if
    the region doesn't exist."""
    region = await db.get(MacroRegion, code)
    if region is None:
        return None
    region.label = label
    region.equity_ticker = equity_ticker
    region.bond_ticker = bond_ticker
    region.equity_label = equity_label
    region.bond_label = bond_label
    await db.commit()
    await db.refresh(region)
    return region


async def delete_region(db: AsyncSession, code: str) -> Optional[bool]:
    """Returns None if the region doesn't exist, True on success. Raises ValueError if it's
    the last remaining region — the page must always have at least one to show."""
    region = await db.get(MacroRegion, code)
    if region is None:
        return None
    total = await db.scalar(select(func.count()).select_from(MacroRegion))
    if total is not None and total <= 1:
        raise ValueError("Cannot delete the last remaining region")
    await db.delete(region)
    await db.commit()
    return True


def _rolling_average(dates: list[date], values: list[float], window_years: float) -> list[float]:
    """Time-based (not point-count-based) rolling average — a fixed N-point window would be
    imprecise for "N years" once holidays/weekends/missing days create gaps. O(n) two-pointer
    sliding window: as the right pointer advances, drop left-pointer points older than
    `date - window_years` from the running sum."""
    window = timedelta(days=window_years * _DAYS_PER_YEAR)
    averages: list[float] = []
    running_sum = 0.0
    left = 0
    for right, d in enumerate(dates):
        running_sum += values[right]
        while dates[left] < d - window:
            running_sum -= values[left]
            left += 1
        averages.append(running_sum / (right - left + 1))
    return averages


_EMPTY_RATIO_INDICATOR: dict = {
    "dates": [], "ratio": [], "moving_avg": [], "ma_years": None, "status": None, "latest_date": None,
}


async def compute_ratio_indicator(
    db: AsyncSession, numerator_series: str, denominator_series: str, ma_years: float,
) -> dict:
    """
    Shared computation for both indicators, for any region (growth = equity/oil, inflation =
    bond/gold — see the MacroRegion table and its CRUD functions above) — same rebase-to-100 +
    rolling-average logic, only the series keys differ.

    Dates are inner-joined (only where both series have data) — this naturally clips a ratio
    to whichever series has the shorter history (e.g. a bond ETF's 2012+ start vs. an equity
    index's much longer history).
    """
    numerator = await get_series(db, numerator_series)
    denominator = await get_series(db, denominator_series)
    common_dates = sorted(set(numerator) & set(denominator))
    if not common_dates:
        return dict(_EMPTY_RATIO_INDICATOR)

    raw_ratio = [numerator[d] / denominator[d] for d in common_dates]
    base = raw_ratio[0]
    ratio = [r * 100 / base for r in raw_ratio]
    moving_avg = _rolling_average(common_dates, ratio, ma_years)

    return {
        "dates": [d.isoformat() for d in common_dates],
        "ratio": ratio,
        "moving_avg": moving_avg,
        "ma_years": ma_years,
        "status": "above" if ratio[-1] >= moving_avg[-1] else "below",
        "latest_date": common_dates[-1].isoformat(),
    }
