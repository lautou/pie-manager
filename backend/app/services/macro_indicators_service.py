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

import math
import re
import statistics
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_indicator import MacroRegion
from app.models.system_setting import SystemSetting
from app.services.code_keyed_crud import make_code_keyed_crud
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

_region_crud = make_code_keyed_crud(
    model_cls=MacroRegion,
    code_re=_REGION_CODE_RE,
    invalid_code_message=lambda code: f"Invalid region code: {code!r} (lowercase letters/digits/underscore, 2-20 chars)",
    duplicate_message=lambda code: f"Region '{code}' already exists",
    last_row_guard_message="Cannot delete the last remaining region",
)


async def list_regions(db: AsyncSession) -> list[MacroRegion]:
    return await _region_crud.list(db)


async def create_region(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> MacroRegion:
    return await _region_crud.create(
        db, code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    )


async def update_region(
    db: AsyncSession, code: str, label: str, equity_ticker: str, bond_ticker: str,
    equity_label: str, bond_label: str,
) -> Optional[MacroRegion]:
    """`code` is immutable — it's the macro_series_prices series-key prefix."""
    return await _region_crud.update(
        db, code, label=label, equity_ticker=equity_ticker, bond_ticker=bond_ticker,
        equity_label=equity_label, bond_label=bond_label,
    )


async def delete_region(db: AsyncSession, code: str) -> Optional[bool]:
    """Raises ValueError if it's the last remaining region — the page must always have at
    least one to show."""
    return await _region_crud.delete(db, code)


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


# ---------------------------------------------------------------------------
# Growth/inflation quadrant classifier — informational only, see
# docs/ROADMAP.md's "Quadrant macro-économique" entry for the full design brief.
# Never drives Pool.target_pct or any rebalancing automation.
# ---------------------------------------------------------------------------

# growth "above" its MA = croissance, "below" = ralentissement.
# inflation "above" its MA = désinflation, "below" = inflation (see compute_ratio_indicator's
# own numerator/denominator convention: inflation ratio = bond/gold, so bonds outperforming
# gold — ratio above its MA — is the désinflation signal, not the inflation one).
QUADRANT_GOLDILOCKS = "goldilocks"       # croissance + désinflation
QUADRANT_OVERHEATING = "overheating"     # croissance + inflation
QUADRANT_DISINFL_SLOWDOWN = "disinflationary_slowdown"  # ralentissement + désinflation
QUADRANT_STAGFLATION = "stagflation"     # ralentissement + inflation

_QUADRANT_BY_STATUS: dict[tuple[str, str], str] = {
    ("above", "above"): QUADRANT_GOLDILOCKS,
    ("above", "below"): QUADRANT_OVERHEATING,
    ("below", "above"): QUADRANT_DISINFL_SLOWDOWN,
    ("below", "below"): QUADRANT_STAGFLATION,
}


def classify_quadrant(growth_status: Optional[str], inflation_status: Optional[str]) -> Optional[str]:
    """Combine the two independently-computed ratio statuses into one of the 4 named
    macro quadrants. Returns None if either status is unavailable (e.g. no price history
    yet for a freshly-added region)."""
    if growth_status not in ("above", "below") or inflation_status not in ("above", "below"):
        return None
    return _QUADRANT_BY_STATUS[(growth_status, inflation_status)]


def compute_confidence(ratio: list[float], moving_avg: list[float]) -> Optional[float]:
    """
    This app's own derived confidence measure (-1..+1) for how far the latest ratio sits
    from its moving average — NOT a reproduction of any third-party score. Method: a z-score
    of the latest (ratio - moving_avg) deviation against the historical standard deviation of
    that same deviation series, squashed into [-1, 1] via tanh so a handful of extreme outlier
    days can't blow the scale out unboundedly. Positive = latest deviation further above the MA
    than usual (stronger "above" signal); negative = further below than usual.

    Returns None if there isn't enough history to estimate a meaningful volatility (fewer than
    30 points, or a degenerate zero-variance series).
    """
    if len(ratio) < 30 or len(ratio) != len(moving_avg):
        return None
    deviations = [r - m for r, m in zip(ratio, moving_avg)]
    stdev = statistics.pstdev(deviations)
    if stdev == 0:
        return None
    z_score = deviations[-1] / stdev
    return math.tanh(z_score)


async def compute_quadrant(db: AsyncSession, region_code: str, ma_years: float) -> dict:
    """Growth + inflation ratios for one region, combined into a quadrant + confidence score.
    Reuses compute_ratio_indicator for both legs — no duplicated ratio/MA math.

    `overall_confidence` is the mean of the two axes' confidence *magnitudes* (0 = right at
    the crossover point on both axes, i.e. an ambiguous/borderline quadrant reading; 1 = both
    axes are strongly displaced from their own moving average, i.e. a clear-cut reading) —
    deliberately not signed, since "confidently above" and "confidently below" are equally
    decisive for how clear-cut the quadrant itself is."""
    growth = await compute_ratio_indicator(db, f"{region_code}_equity", "oil", ma_years)
    inflation = await compute_ratio_indicator(db, f"{region_code}_bond", "gold", ma_years)
    growth_confidence = compute_confidence(growth["ratio"], growth["moving_avg"])
    inflation_confidence = compute_confidence(inflation["ratio"], inflation["moving_avg"])
    overall_confidence = (
        (abs(growth_confidence) + abs(inflation_confidence)) / 2
        if growth_confidence is not None and inflation_confidence is not None
        else None
    )
    return {
        "quadrant": classify_quadrant(growth["status"], inflation["status"]),
        "growth_confidence": growth_confidence,
        "inflation_confidence": inflation_confidence,
        "overall_confidence": overall_confidence,
        "growth_status": growth["status"],
        "inflation_status": inflation["status"],
        "latest_date": growth["latest_date"] or inflation["latest_date"],
    }
