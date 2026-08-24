# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the shared trailing-performance math
(app/services/performance_math.py), extracted from
country_performance_service.py when sector_performance_service.py needed the identical
computation for a second, unrelated universe. Pure functions — no DB, no event loop.
"""
from datetime import date, timedelta

import pytest

from app.services.performance_math import ASOF_TOLERANCE_DAYS, asof, compute_trailing_performance

TODAY = date(2026, 7, 19)
ANCHOR_TARGET = TODAY - timedelta(days=365)


# ---------------------------------------------------------------------------
# asof
# ---------------------------------------------------------------------------

def test_asof_empty_series_returns_none():
    assert asof({}, TODAY, ASOF_TOLERANCE_DAYS) is None


def test_asof_picks_max_date_candidate_at_or_before_target():
    series = {
        TODAY - timedelta(days=5): 100.0,
        TODAY - timedelta(days=2): 110.0,
        TODAY + timedelta(days=1): 999.0,  # after target — must never be picked
    }
    result = asof(series, TODAY, ASOF_TOLERANCE_DAYS)
    assert result == (TODAY - timedelta(days=2), 110.0)


def test_asof_boundary_within_tolerance_included():
    boundary = ANCHOR_TARGET - timedelta(days=ASOF_TOLERANCE_DAYS)
    series = {boundary: 100.0}
    assert asof(series, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) == (boundary, 100.0)


def test_asof_boundary_beyond_tolerance_excluded():
    beyond = ANCHOR_TARGET - timedelta(days=ASOF_TOLERANCE_DAYS + 1)
    series = {beyond: 100.0}
    assert asof(series, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


# ---------------------------------------------------------------------------
# compute_trailing_performance
# ---------------------------------------------------------------------------

def test_compute_trailing_performance_eur_skips_fx_factor():
    index_series = {ANCHOR_TARGET: 100.0, TODAY: 150.0}
    result = compute_trailing_performance(index_series, None, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS)
    assert result is not None
    assert result.perf_pct == pytest.approx(50.0)
    assert result.latest_date == TODAY
    assert result.anchor_date == ANCHOR_TARGET


def test_compute_trailing_performance_non_eur_applies_fx_factor():
    index_series = {ANCHOR_TARGET: 100.0, TODAY: 110.0}
    fx_series = {ANCHOR_TARGET: 0.9, TODAY: 0.95}
    result = compute_trailing_performance(index_series, fx_series, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS)
    assert result is not None
    expected = ((110.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert result.perf_pct == pytest.approx(expected)


def test_compute_trailing_performance_dates_come_from_index_series_not_fx():
    """The fx series can have snapshots on different dates than the index series — the
    returned latest_date/anchor_date must reflect the index series's own as-of dates."""
    index_series = {ANCHOR_TARGET: 100.0, TODAY - timedelta(days=1): 110.0}
    fx_series = {ANCHOR_TARGET - timedelta(days=2): 0.9, TODAY: 0.95}
    result = compute_trailing_performance(index_series, fx_series, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS)
    assert result is not None
    assert result.latest_date == TODAY - timedelta(days=1)
    assert result.anchor_date == ANCHOR_TARGET


def test_compute_trailing_performance_excludes_missing_index_latest():
    index_series = {ANCHOR_TARGET: 100.0}
    assert compute_trailing_performance(index_series, None, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


def test_compute_trailing_performance_excludes_missing_index_anchor():
    index_series = {TODAY: 150.0}
    assert compute_trailing_performance(index_series, None, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


def test_compute_trailing_performance_excludes_zero_index_anchor():
    index_series = {ANCHOR_TARGET: 0.0, TODAY: 150.0}
    assert compute_trailing_performance(index_series, None, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


def test_compute_trailing_performance_excludes_missing_fx_latest():
    index_series = {ANCHOR_TARGET: 100.0, TODAY: 110.0}
    fx_series = {ANCHOR_TARGET: 0.9}
    assert compute_trailing_performance(index_series, fx_series, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


def test_compute_trailing_performance_excludes_missing_fx_anchor():
    index_series = {ANCHOR_TARGET: 100.0, TODAY: 110.0}
    fx_series = {TODAY: 0.95}
    assert compute_trailing_performance(index_series, fx_series, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None


def test_compute_trailing_performance_excludes_zero_fx_anchor():
    index_series = {ANCHOR_TARGET: 100.0, TODAY: 110.0}
    fx_series = {ANCHOR_TARGET: 0.0, TODAY: 0.95}
    assert compute_trailing_performance(index_series, fx_series, TODAY, ANCHOR_TARGET, ASOF_TOLERANCE_DAYS) is None
