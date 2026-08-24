# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Country stock-market performance leaderboard: DB-only helpers (no HTTP) for the curated
country universe CRUD and the trailing-1-year, EUR-adjusted Top-N ranking shown on the
"Performance des marchés" tab of the Indicateurs page.

Split from app/tasks/country_performance.py the same way macro_indicators_service.py is
split from tasks/macro_indicators.py: this module owns DB reads/writes and the ranking
computation, the task module owns the Yahoo HTTP fetching and PgQueuer scheduling.

Deliberately NOT a variant of macro_indicators_service.compute_ratio_indicator — that
function computes a continuous rebased ratio between two inner-joined series (for a line
chart with a moving average); this one only needs two point-in-time snapshots per country
(now and ~1 year ago) to rank a leaderboard, so the computation shape is unrelated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.country_performance import CountryPerfConfig
from app.models.system_setting import SystemSetting
from app.services.code_keyed_crud import make_code_keyed_crud
from app.services.macro_series_price_service import get_series
from app.services.performance_math import ASOF_TOLERANCE_DAYS, TRAILING_WINDOW_DAYS, compute_trailing_performance

_COUNTRY_CODE_RE = re.compile(r"^[a-z]{2,3}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

DEFAULT_TOP_N = 15
TOP_N_SETTING_KEY = "country_perf.top_n"

# TRAILING_WINDOW_DAYS / ASOF_TOLERANCE_DAYS now live in performance_math.py (shared with
# sector_performance_service.py) — re-imported above so this module's own public constants
# are unchanged for anything already importing them qualified as
# country_performance_service.TRAILING_WINDOW_DAYS / .ASOF_TOLERANCE_DAYS.


# ---------------------------------------------------------------------------
# Country CRUD — user-managed leaderboard universe. No "last remaining row" guard, unlike
# MacroRegion's CRUD — an emptied-out universe simply yields an empty leaderboard, a valid
# (if degenerate) state, not a broken page.
# ---------------------------------------------------------------------------

_country_crud = make_code_keyed_crud(
    model_cls=CountryPerfConfig,
    code_re=_COUNTRY_CODE_RE,
    invalid_code_message=lambda code: f"Invalid country code: {code!r} (lowercase letters, 2-3 chars)",
    duplicate_message=lambda code: f"Country '{code}' already exists",
    field_validators={
        "currency": (_CURRENCY_RE, lambda v: f"Invalid currency: {v!r} (uppercase ISO 4217, 3 letters)"),
    },
)


async def list_country_configs(db: AsyncSession) -> list[CountryPerfConfig]:
    return await _country_crud.list(db)


async def create_country_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> CountryPerfConfig:
    return await _country_crud.create(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def update_country_config(
    db: AsyncSession, code: str, label: str, index_ticker: str, currency: str, index_label: str,
) -> Optional[CountryPerfConfig]:
    """`code` is immutable — it's the macro_series_prices series-key suffix."""
    return await _country_crud.update(
        db, code, label=label, index_ticker=index_ticker, currency=currency, index_label=index_label,
    )


async def delete_country_config(db: AsyncSession, code: str) -> Optional[bool]:
    return await _country_crud.delete(db, code)


# ---------------------------------------------------------------------------
# Top-N setting
# ---------------------------------------------------------------------------

async def get_top_n(db: AsyncSession) -> int:
    """Reads country_perf.top_n from SystemSetting, falling back to DEFAULT_TOP_N when
    unset, unparsable, or non-positive."""
    setting = await db.get(SystemSetting, TOP_N_SETTING_KEY)
    if setting is None:
        return DEFAULT_TOP_N
    try:
        value = int(setting.value)
    except (TypeError, ValueError):
        return DEFAULT_TOP_N
    return value if value > 0 else DEFAULT_TOP_N


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

@dataclass
class CountryPerformanceResult:
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: date
    anchor_date: date
    index_label: str


async def compute_country_performance(
    db: AsyncSession, top_n: Optional[int] = None,
) -> list[CountryPerformanceResult]:
    """
    Ranks every configured country by trailing-1-year, EUR-adjusted performance and returns
    only the top `top_n` (best performers), sorted ascending (worst of the top group first,
    best last) for the bar chart's left-to-right display.

    perf_pct = (index_latest * fx_latest) / (index_anchor * fx_anchor) - 1) * 100 —
    multiplicative, never additive: a market's local-currency move and its FX move against
    EUR compound, they don't simply add. A country whose currency is EUR skips the FX
    factor entirely (factor = 1.0). FX series are shared across countries with the same
    currency (fx_{currency}), fetched from get_series at most once per currency.

    A country with insufficient/stale index or FX history (no snapshot within
    ASOF_TOLERANCE_DAYS of "today" or of "~1 year ago") is excluded from the ranking rather
    than distorting it with a guessed value. If fewer than top_n countries have valid data,
    fewer are returned — no padding.
    """
    configs = await list_country_configs(db)
    if not configs:
        return []
    if top_n is None:
        top_n = await get_top_n(db)

    today = date.today()
    anchor_target = today - timedelta(days=TRAILING_WINDOW_DAYS)
    fx_cache: dict[str, dict[date, float]] = {}
    results: list[CountryPerformanceResult] = []

    for cfg in configs:
        index_series = await get_series(db, f"country_{cfg.code}_equity")

        fx_series = None
        if cfg.currency != "EUR":
            if cfg.currency not in fx_cache:
                fx_cache[cfg.currency] = await get_series(db, f"fx_{cfg.currency.lower()}")
            fx_series = fx_cache[cfg.currency]

        perf = compute_trailing_performance(index_series, fx_series, today, anchor_target, ASOF_TOLERANCE_DAYS)
        if perf is None:
            continue

        results.append(CountryPerformanceResult(
            code=cfg.code, label=cfg.label, currency=cfg.currency,
            perf_pct=perf.perf_pct, latest_date=perf.latest_date, anchor_date=perf.anchor_date,
            index_label=cfg.index_label,
        ))

    results.sort(key=lambda r: r.perf_pct, reverse=True)  # rank all, best first
    top = results[:top_n]
    top.sort(key=lambda r: r.perf_pct)  # re-sort ascending for chart display
    return top
