# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the TWRR (Time-Weighted Rate of Return) computation.

Key invariants:
  1. First day with positive value → index = 100.
  2. No external flow: index tracks pure price performance (V_t / V_{t-1}).
  3. External inflow (F > 0) neutralised: r_t = V_t / (V_{t-1} + F).
  4. External outflow (F < 0) neutralised: r_t = V_t / (V_{t-1} + F).
  5. Days before first positive value are omitted from output.
  6. Empty or all-zero series returns [].
  7. TWRR is multiplicatively chained across sub-periods.
  8. Identical sub-period returns compound correctly.
"""

import pytest
from datetime import date

from app.api.routers.snapshots import _compute_twrr


def d(s: str) -> date:
    return date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_single_day_returns_100():
    result = _compute_twrr([(d("2024-01-02"), 10_000.0)], {})
    assert len(result) == 1
    assert result[0] == {"date": "2024-01-02", "index": 100.0}


def test_empty_series_returns_empty():
    assert _compute_twrr([], {}) == []


def test_all_zero_values_returns_empty():
    series = [(d("2024-01-02"), 0.0), (d("2024-01-03"), 0.0)]
    assert _compute_twrr(series, {}) == []


def test_leading_zeros_skipped_until_first_positive():
    series = [
        (d("2024-01-01"), 0.0),
        (d("2024-01-02"), 0.0),
        (d("2024-01-03"), 10_000.0),
        (d("2024-01-04"), 11_000.0),
    ]
    result = _compute_twrr(series, {})
    assert len(result) == 2
    assert result[0]["date"] == "2024-01-03"
    assert result[0]["index"] == 100.0


# ---------------------------------------------------------------------------
# No-flow price performance
# ---------------------------------------------------------------------------

def test_10pct_gain_without_flow():
    """10% portfolio gain → index goes from 100 to 110."""
    series = [(d("2024-01-02"), 10_000.0), (d("2024-01-03"), 11_000.0)]
    result = _compute_twrr(series, {})
    assert result[0]["index"] == 100.0
    assert result[1]["index"] == pytest.approx(110.0, rel=1e-4)


def test_10pct_loss_without_flow():
    series = [(d("2024-01-02"), 10_000.0), (d("2024-01-03"), 9_000.0)]
    result = _compute_twrr(series, {})
    assert result[1]["index"] == pytest.approx(90.0, rel=1e-4)


def test_flat_performance_stays_at_100():
    series = [
        (d("2024-01-02"), 10_000.0),
        (d("2024-01-03"), 10_000.0),
        (d("2024-01-04"), 10_000.0),
    ]
    result = _compute_twrr(series, {})
    assert all(r["index"] == pytest.approx(100.0) for r in result)


# ---------------------------------------------------------------------------
# External flow neutralisation
# ---------------------------------------------------------------------------

def test_inflow_neutralised():
    """
    Day 1: V=10_000, Day 2: add 5_000 (inflow), positions unchanged → total 15_000.
    Without TWRR: 15_000/10_000 = +50% (wrong).
    With TWRR: 15_000 / (10_000 + 5_000) = 1.0 → index stays 100.
    """
    series = [(d("2024-01-02"), 10_000.0), (d("2024-01-03"), 15_000.0)]
    flows = {d("2024-01-03"): 5_000.0}
    result = _compute_twrr(series, flows)
    assert result[1]["index"] == pytest.approx(100.0, abs=0.05)


def test_outflow_neutralised():
    """
    Day 1: V=10_000, Day 2: withdraw 3_000 (outflow F=-3_000) → 7_000 remaining (flat performance).
    TWRR: 7_000 / (10_000 + (-3_000)) = 7_000/7_000 = 1.0 → index stays 100.
    """
    series = [(d("2024-01-02"), 10_000.0), (d("2024-01-03"), 7_000.0)]
    flows = {d("2024-01-03"): -3_000.0}
    result = _compute_twrr(series, flows)
    assert result[1]["index"] == pytest.approx(100.0, abs=0.05)


def test_inflow_plus_gain():
    """
    Day 1: V=10_000
    Day 2: inflow 5_000 + 10% gain on original positions → V = 11_000 + 5_000 = 16_000.
    TWRR sub-period: 16_000 / (10_000 + 5_000) = 16/15 → index = 100 × 16/15 ≈ 106.67.
    """
    series = [(d("2024-01-02"), 10_000.0), (d("2024-01-03"), 16_000.0)]
    flows = {d("2024-01-03"): 5_000.0}
    result = _compute_twrr(series, flows)
    expected = 100.0 * (16_000.0 / 15_000.0)
    assert result[1]["index"] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Multiplicative chaining
# ---------------------------------------------------------------------------

def test_two_equal_gains_compound():
    """Two consecutive +10% gains → index = 100 × 1.10 × 1.10 = 121."""
    series = [
        (d("2024-01-02"), 10_000.0),
        (d("2024-01-03"), 11_000.0),
        (d("2024-01-04"), 12_100.0),
    ]
    result = _compute_twrr(series, {})
    assert result[2]["index"] == pytest.approx(121.0, rel=1e-3)


def test_gain_then_loss_returns_to_start():
    """
    +10% then -9.09% → 100 × 1.10 × (1/1.10) = 100 (exactly back).
    """
    series = [
        (d("2024-01-02"), 10_000.0),
        (d("2024-01-03"), 11_000.0),
        (d("2024-01-04"), 10_000.0),
    ]
    result = _compute_twrr(series, {})
    assert result[2]["index"] == pytest.approx(100.0, abs=0.01)


def test_flow_in_middle_of_chain():
    """
    Day 1: 10_000 → Day 2: 11_000 (+10%, no flow)
    Day 3: 16_500 (inflow 5_000 + old positions up 0.9%, new flat)
    TWRR chain: 110 × (16_500 / (11_000 + 5_000)) = 110 × (16_500/16_000)
    """
    series = [
        (d("2024-01-02"), 10_000.0),
        (d("2024-01-03"), 11_000.0),
        (d("2024-01-04"), 16_500.0),
    ]
    flows = {d("2024-01-04"): 5_000.0}
    result = _compute_twrr(series, flows)
    idx_day2 = 100.0 * (11_000 / 10_000)
    idx_day3 = idx_day2 * (16_500 / 16_000)
    assert result[1]["index"] == pytest.approx(idx_day2, rel=1e-4)
    assert result[2]["index"] == pytest.approx(idx_day3, rel=1e-4)


# ---------------------------------------------------------------------------
# Legacy pool scenario: partial liquidation neutralised
# ---------------------------------------------------------------------------

def test_partial_liquidation_does_not_tank_index():
    """
    Simulates the Portfolio 2 Legacy pool: partial sale removes 40% of capital.
    The sale is recorded as an outflow (F < 0 to portfolio, but the pool
    value drops by the sold amount → TWRR should show near-flat performance).

    Before sale: V=50_000
    After sale: positions worth 30_000, outflow = -20_000
    r = 30_000 / (50_000 + (-20_000)) = 30_000 / 30_000 = 1.0 → no performance change.
    """
    series = [
        (d("2025-10-14"), 50_000.0),
        (d("2025-10-15"), 30_000.0),  # 20k sold out
    ]
    flows = {d("2025-10-15"): -20_000.0}  # capital left the pool
    result = _compute_twrr(series, flows)
    assert result[1]["index"] == pytest.approx(100.0, abs=0.1)


def test_full_liquidation_last_point_zero():
    """After full liquidation (V=0), the series ends naturally."""
    series = [
        (d("2026-03-04"), 30_000.0),
        (d("2026-03-05"), 0.0),  # full liquidation
    ]
    flows = {d("2026-03-05"): -30_000.0}
    result = _compute_twrr(series, flows)
    # V=0, denom=0 → division skipped, index unchanged
    assert result[1]["index"] == pytest.approx(100.0, abs=0.1)




# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

def test_output_contains_date_and_index_keys():
    series = [(d("2024-06-01"), 5_000.0), (d("2024-06-02"), 5_250.0)]
    result = _compute_twrr(series, {})
    for point in result:
        assert "date" in point
        assert "index" in point
        assert isinstance(point["date"], str)
        assert isinstance(point["index"], float)


def test_dates_are_iso_format():
    series = [(d("2024-12-31"), 1_000.0)]
    result = _compute_twrr(series, {})
    assert result[0]["date"] == "2024-12-31"


# ---------------------------------------------------------------------------
# Dividends excluded from TWRR flows (price return, not total return)
# ---------------------------------------------------------------------------

def test_dividend_excluded_from_flows_does_not_distort_index():
    """
    TWRR is a price return: dividends (type='Revenu') are excluded from the
    pool-flow SQL (filter t.type = 'Actif'). If a dividend were included as
    a flow, it would inflate the denominator and produce a fake performance drop.

    This test verifies _compute_twrr directly: with a 0 flow on a dividend day
    the index correctly tracks the pool value change. The SQL exclusion is tested
    implicitly by the integration tests in test_snapshots_router.py.
    """
    # Pool value goes from 10k to 10.5k (+5%) on the dividend day.
    # No flow → TWRR correctly shows +5%.
    series = [(d("2025-06-01"), 10_000.0), (d("2025-06-02"), 10_500.0)]
    result = _compute_twrr(series, {})  # flow = 0 (dividend excluded by SQL)
    assert result[1]["index"] == pytest.approx(105.0, rel=1e-3)

    # If dividend were incorrectly included as a flow (+500 inflow):
    flows_wrong = {d("2025-06-02"): 500.0}
    result_wrong = _compute_twrr(series, flows_wrong)
    # denom = 10000 + 500 = 10500, r = 10500/10500 = 1.0 → index stays at 100
    # This is wrong: the pool genuinely gained 5%, but dividend inclusion hides it.
    assert result_wrong[1]["index"] == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Cash ticker sign convention (JPYEUR=X / Yen pool)
# ---------------------------------------------------------------------------

def test_cash_deposit_is_inflow_not_outflow():
    """
    For Cash tickers (JPYEUR=X), a deposit has total_amount_eur > 0.
    The flow must be +amount (inflow), NOT -amount (which would make
    the TWRR denominator collapse and spike the index to ~33000x).

    pool_flows is already computed with the corrected sign in the endpoint;
    here we verify _compute_twrr handles a positive flow correctly.
    """
    # Day 1: pool = 30k (XJSE.DE only)
    # Day 2: deposit 30k JPY equivalent — pool = 60k, flow = +30k (inflow)
    series = [(d("2024-09-02"), 30_000.0), (d("2024-09-03"), 60_000.0)]
    flows = {d("2024-09-03"): 30_000.0}  # positive = inflow (Cash convention)
    result = _compute_twrr(series, flows)
    # 60k / (30k + 30k) = 1.0 → index stays at 100
    assert result[1]["index"] == pytest.approx(100.0, abs=0.1)


def test_cash_withdrawal_is_outflow():
    """
    A Cash withdrawal has total_amount_eur < 0 → flow = negative (outflow).
    Pool value decreases by withdrawal amount → TWRR stays flat.
    """
    series = [(d("2025-01-02"), 30_000.0), (d("2025-01-03"), 20_000.0)]
    flows = {d("2025-01-03"): -10_000.0}  # negative = outflow
    result = _compute_twrr(series, flows)
    # 20k / (30k - 10k) = 1.0 → flat
    assert result[1]["index"] == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Weekend/holiday flow remapping (Portfolio 2 Yen pool Feb 2026 regression)
# ---------------------------------------------------------------------------

def test_weekend_outflow_remapped_to_next_trading_day():
    """
    Regression: JPY was sold on Saturday 15/02/2026 (no snapshot) and
    XJSE.DE was bought on Monday 16/02/2026. Without remapping, the Monday
    XJSE.DE inflow was applied to a denominator that hadn't been reduced by
    the Saturday JPY outflow → fake -30% drop.

    The remap_flows helper merges Saturday's outflow into Monday, so both
    flows apply to the same snapshot period and cancel → index ≈ flat.
    """
    # Simulate: Friday prev_v=28k, Saturday JPY sell -11.8k (no snapshot),
    # Monday XJSE.DE buy +11.8k, Monday pool value ≈ 28k (rotation, flat).
    #
    # After remapping Saturday's outflow to Monday:
    #   net Monday flow = -11.8k (out) + 11.8k (in) = 0
    #   r = 28k / 28k = 1.0 → flat ✓
    #
    # Without remapping:
    #   Monday flow = +11.8k only
    #   denom = 28k + 11.8k = 39.8k, r = 28k / 39.8k = 0.70 → fake -30% ✗
    series = [
        (d("2026-02-13"), 27_850.0),   # Friday
        (d("2026-02-16"), 27_835.0),   # Monday (Saturday/Sunday skipped)
    ]
    # After correct remapping, Monday receives net flow ≈ 0
    flows_correct = {d("2026-02-16"): 0.0}   # -11809 + 11799 ≈ 0
    result = _compute_twrr(series, flows_correct)
    assert result[1]["index"] == pytest.approx(100.0, abs=1.0)

    # Without remapping (wrong): only +11799 applied → fake drop
    flows_wrong = {d("2026-02-16"): 11_799.0}
    result_wrong = _compute_twrr(series, flows_wrong)
    assert result_wrong[1]["index"] < 80.0  # would show ~70
