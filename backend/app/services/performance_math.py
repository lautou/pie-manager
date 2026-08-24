# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared pure-math core for every trailing-window, EUR-adjusted performance calculation in
this app — extracted from country_performance_service.py (its original, sole owner) when
sector_performance_service.py needed the identical computation for a second, unrelated
universe (4 commodities vs ~20 countries). Deliberately holds ONLY the pure per-row math and
the as-of lookup helper; CRUD, Top-N truncation/ranking, and per-currency FX-series
caching/dedup stay in each service module, since those differ (country ranks + truncates to
Top N, sector doesn't rank at all — just returns all configured rows ascending).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

TRAILING_WINDOW_DAYS = 365
# How stale a series' nearest snapshot may be and still count — covers weekends/holidays
# around the target date, and excludes a row whose fetch has been failing for a while.
ASOF_TOLERANCE_DAYS = 10


def asof(series: dict[date, float], target: date, tolerance_days: int) -> Optional[tuple[date, float]]:
    """Latest (date, value) at or before `target`, only if within `tolerance_days` of it."""
    candidates = [(d, v) for d, v in series.items() if d <= target and (target - d).days <= tolerance_days]
    return max(candidates, key=lambda dv: dv[0]) if candidates else None


@dataclass
class TrailingPerformanceResult:
    perf_pct: float
    latest_date: date
    anchor_date: date


def compute_trailing_performance(
    index_series: dict[date, float],
    fx_series: Optional[dict[date, float]],
    today: date,
    anchor_target: date,
    tolerance_days: int,
) -> Optional[TrailingPerformanceResult]:
    """
    perf_pct = ((index_latest/index_anchor) * (fx_latest/fx_anchor) - 1) * 100 —
    multiplicative, never additive: a local-currency move and an FX move against EUR
    compound, they don't simply add. Pass fx_series=None for an EUR-denominated row (skips
    the FX factor entirely, factor_fx=1.0) — the caller decides EUR-vs-not and resolves/
    caches the fx series itself; this function only does the math once both series are in
    hand. Returns None if the index (or, when fx_series is given, the fx series) has no
    as-of snapshot within tolerance_days of `today` or `anchor_target`, or if either anchor
    value is zero (zero-division guard) — the caller excludes that row entirely rather than
    plotting a guessed value.
    """
    index_latest = asof(index_series, today, tolerance_days)
    index_anchor = asof(index_series, anchor_target, tolerance_days)
    if index_latest is None or index_anchor is None or index_anchor[1] == 0:
        return None
    factor_index = index_latest[1] / index_anchor[1]

    if fx_series is None:
        factor_fx = 1.0
    else:
        fx_latest = asof(fx_series, today, tolerance_days)
        fx_anchor = asof(fx_series, anchor_target, tolerance_days)
        if fx_latest is None or fx_anchor is None or fx_anchor[1] == 0:
            return None
        factor_fx = fx_latest[1] / fx_anchor[1]

    perf_pct = (factor_index * factor_fx - 1) * 100
    return TrailingPerformanceResult(
        perf_pct=perf_pct, latest_date=index_latest[0], anchor_date=index_anchor[0],
    )
