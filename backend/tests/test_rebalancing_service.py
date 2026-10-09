# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the rebalancing service.

Key invariants:
  1. Sum of hybrid_amounts equals total_apport (injection + liquidity).
  2. Increasing injection reduces sell amounts from overweight pools.
  3. With zero injection, hybrid_amounts match a pure "rebalance to target in current total".
     (hybrid always targets total_after, so with injection=0 it equals rebalance.)
  4. With injection large enough to cover all underweight needs, overweight pools sell nothing
     (or buy if total_after makes them underweight too).
  5. injection_amount (injection seule) never triggers sells.
  6. injection_amount is proportional to individual pool shortfalls — no 50/50 strategy constraint.
"""

import pytest

from app.models.system_setting import SystemSetting
from app.services.rebalancing_service import (
    DEFAULT_TOLERANCE_OK_PCT,
    PoolRebalanceInput,
    compute_injection_total_needed,
    compute_rebalancing,
    find_untargeted_pools_with_value,
    get_tolerance_ok_pct,
)


def _make_pools(values: list[tuple[str, str, float, float]]) -> list[PoolRebalanceInput]:
    """values = [(name, strategy, target_pct, current_value), ...]"""
    return [
        PoolRebalanceInput(id=i, name=n, strategy=s, target_pct=t, current_value=v)
        for i, (n, s, t, v) in enumerate(values)
    ]


# ---------------------------------------------------------------------------
# Basic sanity
# ---------------------------------------------------------------------------

def test_compute_rebalancing_returns_empty_when_total_after_zero():
    """
    If all pools have zero value AND no injection (total_after = 0),
    compute_rebalancing must return [] rather than dividing by zero.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 0.0),
        ("Energie", "Offensive", 0.25, 0.0),
        ("Or",      "Defensive", 0.25, 0.0),
        ("Yen",     "Defensive", 0.25, 0.0),
    ])
    result = compute_rebalancing(pools, liquidity_available=0.0, external_injection=0.0)
    assert result == []


def test_compute_rebalancing_returns_empty_when_injection_negative_and_offsets_total():
    """
    Negative injection larger than total current value → total_after ≤ 0 → returns [].
    (Edge case: withdrawal exceeds portfolio value.)
    """
    pools = _make_pools([("A", "Offensive", 1.0, 100.0)])
    result = compute_rebalancing(pools, liquidity_available=0.0, external_injection=-200.0)
    assert result == []


def test_hybrid_sum_equals_injection():
    """
    With any injection, sum of hybrid_amounts must equal total_apport.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 30_000),
        ("Energie", "Offensive", 0.25, 20_000),
        ("Or",      "Defensive", 0.25, 18_000),
        ("Yen",     "Defensive", 0.25, 32_000),
    ])
    for injection in [0, 1_000, 5_000, 10_000, 50_000]:
        results = compute_rebalancing(pools, liquidity_available=0.0, external_injection=float(injection))
        total_hybrid = sum(r.hybrid_amount for r in results)
        assert total_hybrid == pytest.approx(float(injection), abs=0.02), (
            f"injection={injection}: sum(hybrid)={total_hybrid} ≠ {injection}"
        )


def test_injection_amount_never_negative():
    """
    Contribution-only allocation never assigns negative amounts.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 40_000),  # overweight
        ("Energie", "Offensive", 0.25, 20_000),
        ("Or",      "Defensive", 0.25, 18_000),
        ("Yen",     "Defensive", 0.25, 22_000),
    ])
    results = compute_rebalancing(pools, 0.0, 5_000.0)
    assert all(r.injection_amount >= 0 for r in results)


def test_injection_amount_sum_equals_total_apport():
    """
    Sum of injection_amounts equals total_apport.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.50, 10_000),
        ("Or",      "Defensive", 0.50, 20_000),
    ])
    results = compute_rebalancing(pools, liquidity_available=2_000.0, external_injection=3_000.0)
    total_injection = sum(r.injection_amount for r in results)
    assert total_injection == pytest.approx(5_000.0, abs=0.02)


# ---------------------------------------------------------------------------
# Hybrid: sells decrease as injection increases
# ---------------------------------------------------------------------------

def test_hybrid_sells_decrease_with_more_injection():
    """
    Overweight pools must sell LESS when injection is larger.
    The bug was: sells were constant regardless of injection amount.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),  # overweight (60% of 50k)
        ("B", "Defensive", 0.50, 20_000),  # underweight (40% of 50k)
    ])

    def sell_amount(injection: float) -> float:
        results = compute_rebalancing(pools, 0.0, injection)
        sells = [r.hybrid_amount for r in results if r.hybrid_amount < 0]
        return sum(sells)  # negative number, more negative = more selling

    sell_1k = sell_amount(1_000)
    sell_5k = sell_amount(5_000)
    sell_10k = sell_amount(10_000)

    # More injection → less (or equal) selling required
    assert sell_1k <= sell_5k, (
        f"Injection 1k sells more ({sell_1k}) than injection 5k ({sell_5k}) — bug!"
    )
    assert sell_5k <= sell_10k, (
        f"Injection 5k sells more ({sell_5k}) than injection 10k ({sell_10k}) — bug!"
    )


def test_hybrid_exact_amounts_two_pool():
    """
    With two equal-target pools and clear overweight/underweight:
      Pool A target=50%  current=30k  (overweight vs 50k total, underweight vs 51k total_after)
      Pool B target=50%  current=20k  (underweight)
      injection = 1_000
      total_after = 51_000

    Expected:
      Pool A hybrid = 51k*0.5 - 30k = 25.5k - 30k = -4500  (sell 4500)
      Pool B hybrid = 51k*0.5 - 20k = 25.5k - 20k = +5500  (buy 5500)
      sum = 1000 ✓
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),
        ("B", "Defensive", 0.50, 20_000),
    ])
    results = compute_rebalancing(pools, 0.0, 1_000.0)
    by_name = {r.name: r for r in results}

    assert by_name["A"].hybrid_amount == pytest.approx(-4_500.0, abs=0.01)
    assert by_name["B"].hybrid_amount == pytest.approx(5_500.0, abs=0.01)


def test_hybrid_large_injection_no_sells():
    """
    If injection is large enough that even the formerly-overweight pool
    needs to buy to reach its target in total_after, hybrid must be positive.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),  # overweight vs current 50k
        ("B", "Defensive", 0.50, 20_000),
    ])
    # With injection = 100k, total_after = 150k. Target each = 75k.
    # A: 75k - 30k = +45k (buy), B: 75k - 20k = +55k (buy)
    results = compute_rebalancing(pools, 0.0, 100_000.0)
    assert all(r.hybrid_amount >= 0 for r in results), (
        f"Expected all buys with large injection, got: {[(r.name, r.hybrid_amount) for r in results]}"
    )


def test_hybrid_zero_injection_equals_rebalance_direction():
    """
    With zero injection, each pool's hybrid_amount should have the same sign
    as the rebalance_amount (overweight → sell, underweight → buy).
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),  # overweight
        ("B", "Defensive", 0.50, 20_000),  # underweight
    ])
    results = compute_rebalancing(pools, 0.0, 0.0)
    by_name = {r.name: r for r in results}

    assert by_name["A"].hybrid_amount < 0, "Overweight pool should sell in hybrid with no injection"
    assert by_name["B"].hybrid_amount > 0, "Underweight pool should buy in hybrid with no injection"
    assert by_name["A"].hybrid_amount == pytest.approx(by_name["A"].rebalance_amount, abs=0.01), (
        "With zero injection, hybrid must equal rebalance for overweight pool"
    )


# ---------------------------------------------------------------------------
# Four-pool realistic scenario
# ---------------------------------------------------------------------------

def test_four_pool_hybrid_regression():
    """
    Regression test for the exact scenario that exposed the bug:
    injection=1000 vs injection=5000 must produce different sell amounts.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 40_000),  # overweight
        ("Energie", "Offensive", 0.25, 30_000),  # overweight
        ("Or",      "Defensive", 0.25, 20_000),  # underweight
        ("Yen",     "Defensive", 0.25, 10_000),  # underweight
    ])

    def total_sells(injection: float) -> float:
        results = compute_rebalancing(pools, 0.0, injection)
        return sum(r.hybrid_amount for r in results if r.hybrid_amount < 0)

    sells_1k = total_sells(1_000)
    sells_5k = total_sells(5_000)

    assert sells_1k < sells_5k, (
        f"Bug present: sells_1k={sells_1k}, sells_5k={sells_5k} — should have sells_1k < sells_5k "
        f"(more negative = more selling = less than expected)"
    )


# ---------------------------------------------------------------------------
# Injection seule: proportional to individual shortfalls, no 50/50 constraint
# ---------------------------------------------------------------------------

def test_injection_proportional_to_individual_shortfalls():
    """
    Injection seule must distribute capital proportionally to each pool's
    individual shortfall vs total_after, regardless of strategy grouping.

    Pools: Asie (OFF, 25%, 20k), Energie (OFF, 25%, 30k), Or (DEF, 25%, 20k), Yen (DEF, 25%, 30k)
    Offensive total = 50k, Defensive total = 50k (balanced strategies)
    Injection = 20k, total_after = 120k
    Each target = 30k
    Shortfalls: Asie=10k, Energie=0, Or=10k, Yen=0 → total=20k
    Expected injection: Asie=10k, Energie=0, Or=10k, Yen=0
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 20_000),  # underweight
        ("Energie", "Offensive", 0.25, 30_000),  # at target
        ("Or",      "Defensive", 0.25, 20_000),  # underweight
        ("Yen",     "Defensive", 0.25, 30_000),  # at target
    ])
    results = compute_rebalancing(pools, liquidity_available=0.0, external_injection=20_000.0)
    by_name = {r.name: r for r in results}

    assert by_name["Asie"].injection_amount == pytest.approx(10_000.0, abs=0.02)
    assert by_name["Energie"].injection_amount == pytest.approx(0.0, abs=0.02)
    assert by_name["Or"].injection_amount == pytest.approx(10_000.0, abs=0.02)
    assert by_name["Yen"].injection_amount == pytest.approx(0.0, abs=0.02)


def test_injection_no_50_50_constraint():
    """
    Without the 50/50 rule, an underweight pool receives injection even when its
    strategy side is globally overweight.

    Asie (OFF 25%, 20k underweight) and Energie (OFF 25%, 40k overweight).
    Offensive side total = 60k > target 50k for a 100k portfolio.
    Under the old 50/50 rule, Asie would receive 0 (OFF side overweight).
    Under the new individual-shortfall rule, Asie must receive its proportional share.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 20_000),  # underweight despite OFF overweight
        ("Energie", "Offensive", 0.25, 40_000),  # overweight
        ("Or",      "Defensive", 0.25, 25_000),  # at target
        ("Yen",     "Defensive", 0.25, 15_000),  # underweight
    ])
    # total_current=100k, injection=10k, total_after=110k
    # Targets: each pool 27.5k
    # Shortfalls: Asie=7.5k, Energie=0, Or=2.5k, Yen=12.5k → total=22.5k
    # Asie injection = 7.5/22.5 * 10k ≈ 3333.33
    results = compute_rebalancing(pools, liquidity_available=0.0, external_injection=10_000.0)
    by_name = {r.name: r for r in results}

    # Asie must receive a positive injection (old 50/50 rule would give 0)
    assert by_name["Asie"].injection_amount > 0, (
        "Asie is individually underweight and must receive injection even if Offensive side is overweight"
    )
    assert by_name["Asie"].injection_amount == pytest.approx(10_000 * 7.5 / 22.5, abs=0.02)
    assert by_name["Energie"].injection_amount == pytest.approx(0.0, abs=0.02)
    assert by_name["Or"].injection_amount == pytest.approx(10_000 * 2.5 / 22.5, abs=0.02)
    assert by_name["Yen"].injection_amount == pytest.approx(10_000 * 12.5 / 22.5, abs=0.02)


# ---------------------------------------------------------------------------
# Fee / commission calculations
# ---------------------------------------------------------------------------

def test_fee_zero_when_no_commission():
    """
    With commission_pct=0 and commission_min=0, all fee fields must be 0
    and net fields must equal gross amounts.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),
        ("B", "Defensive", 0.50, 20_000),
    ])
    results = compute_rebalancing(pools, 0.0, 1_000.0, commission_pct=0.0, commission_min=0.0)
    for r in results:
        assert r.injection_fee == 0.0
        assert r.rebalance_fee == 0.0
        assert r.hybrid_fee == 0.0
        assert r.injection_net == pytest.approx(r.injection_amount, abs=0.01)
        assert r.rebalance_net == pytest.approx(r.rebalance_amount, abs=0.01)
        assert r.hybrid_net == pytest.approx(r.hybrid_amount, abs=0.01)


def test_fee_percentage_applied_correctly():
    """
    commission_pct=0.5, commission_min=1.0
    For a pool with injection_amount=4000:
      fee = max(1.0, 4000 * 0.5 / 100) = max(1.0, 20.0) = 20.0
      net = 4000 - 20 = 3980 (buy: net < gross)
    For a pool with rebalance_amount=-5000 (sell):
      fee = max(1.0, 5000 * 0.5 / 100) = 25.0
      net = -5000 + 25 = -4975 (sell: |net| < |gross|, sign preserved)
    """
    pools = _make_pools([
        ("A", "Offensive", 0.50, 30_000),  # overweight → sell in rebalance
        ("B", "Defensive", 0.50, 20_000),  # underweight → buy
    ])
    # With no injection, hybrid == rebalance
    results = compute_rebalancing(pools, 0.0, 0.0, commission_pct=0.5, commission_min=1.0)
    by_name = {r.name: r for r in results}

    # A sells 5000 in rebalance (30k - 25k = 5k overweight → sell 5k)
    a = by_name["A"]
    assert a.rebalance_amount == pytest.approx(-5_000.0, abs=0.01)
    expected_fee_a = max(1.0, 5_000 * 0.5 / 100)  # = 25.0
    assert a.rebalance_fee == pytest.approx(expected_fee_a, abs=0.01)
    assert a.rebalance_net == pytest.approx(-5_000.0 + expected_fee_a, abs=0.01)  # -4975

    # B buys 5000 in rebalance
    b = by_name["B"]
    assert b.rebalance_amount == pytest.approx(5_000.0, abs=0.01)
    expected_fee_b = max(1.0, 5_000 * 0.5 / 100)  # = 25.0
    assert b.rebalance_fee == pytest.approx(expected_fee_b, abs=0.01)
    assert b.rebalance_net == pytest.approx(5_000.0 - expected_fee_b, abs=0.01)  # 4975


def test_fee_minimum_applied_when_trade_small():
    """
    commission_pct=0.5, commission_min=1.0
    For a trade of 100€: fee = max(1.0, 100 * 0.5 / 100) = max(1.0, 0.5) = 1.0
    """
    pools = _make_pools([
        ("A", "Offensive", 1.0, 100.0),
    ])
    results = compute_rebalancing(pools, 0.0, 1_000.0, commission_pct=0.5, commission_min=1.0)
    r = results[0]
    # injection_amount = 1000 → fee = max(1.0, 1000 * 0.5/100) = max(1.0, 5.0) = 5.0
    assert r.injection_fee == pytest.approx(5.0, abs=0.01)
    assert r.injection_net == pytest.approx(r.injection_amount - r.injection_fee, abs=0.01)


def test_fee_zero_amount_gives_zero_fee():
    """
    Pools with zero amounts must have zero fee and zero net.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.25, 25_000),  # exactly at target → injection=0
        ("B", "Offensive", 0.25, 25_000),
        ("C", "Defensive", 0.25, 25_000),
        ("D", "Defensive", 0.25, 25_000),
    ])
    # All pools at exact target → all amounts = 0 → fees = 0
    results = compute_rebalancing(pools, 0.0, 0.0, commission_pct=0.5, commission_min=1.0)
    for r in results:
        assert r.injection_fee == 0.0
        assert r.rebalance_fee == 0.0
        assert r.hybrid_fee == 0.0
        assert r.injection_net == 0.0
        assert r.rebalance_net == 0.0
        assert r.hybrid_net == 0.0


def test_fee_four_pool_with_injection():
    """
    Integration: 4-pool scenario with injection and commission.
    Verify all fee fields are non-negative and net amounts have correct signs.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 20_000),  # underweight
        ("Energie", "Offensive", 0.25, 30_000),  # at target
        ("Or",      "Defensive", 0.25, 20_000),  # underweight
        ("Yen",     "Defensive", 0.25, 30_000),  # at target
    ])
    results = compute_rebalancing(
        pools, 0.0, 20_000.0, commission_pct=0.5, commission_min=1.0
    )
    by_name = {r.name: r for r in results}

    for r in results:
        # Fees are always non-negative
        assert r.injection_fee >= 0.0
        assert r.rebalance_fee >= 0.0
        assert r.hybrid_fee >= 0.0

    # For pools with positive injection_amount, net < gross (fee deducted)
    asie = by_name["Asie"]
    assert asie.injection_amount > 0
    assert asie.injection_fee > 0
    assert asie.injection_net < asie.injection_amount  # net < gross for buys

    # Energie receives 0 → fee = 0
    energie = by_name["Energie"]
    assert energie.injection_amount == pytest.approx(0.0, abs=0.02)
    assert energie.injection_fee == 0.0
    assert energie.injection_net == pytest.approx(0.0, abs=0.02)


# ---------------------------------------------------------------------------
# Tolerance-aware trade suppression — a gap smaller than tolerance_ok_pct must
# not propose a cosmetic trade, in any of the 3 modes.
# ---------------------------------------------------------------------------

def test_tolerance_suppresses_tiny_injection_and_redistributes_to_real_shortfall():
    """
    4 pools, each within 1% of its 25% target except one (Or) that is
    meaningfully underweight. With tolerance_ok_pct=1, the 3 near-target pools
    must receive 0 injection and the entire injection must go to Or alone —
    reproducing the real-world case (Énergie/Or showing "Acheter X€" despite
    being within the "En cible" tolerance already shown on screen).
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 25_000),   # exactly on target
        ("Energie", "Offensive", 0.25, 24_900),   # 0.1% under — within tolerance
        ("Yen",     "Defensive", 0.25, 25_100),   # 0.1% over — within tolerance
        ("Or",      "Defensive", 0.25, 20_000),   # meaningfully underweight
    ])
    results = compute_rebalancing(
        pools, liquidity_available=0.0, external_injection=5_000.0, tolerance_ok_pct=1.0
    )
    by_name = {r.name: r for r in results}

    assert by_name["Asie"].injection_amount == 0.0
    assert by_name["Energie"].injection_amount == 0.0
    assert by_name["Yen"].injection_amount == 0.0
    # Or alone absorbs the full injection instead of a quarter of it.
    assert by_name["Or"].injection_amount == pytest.approx(5_000.0, abs=0.02)


def test_tolerance_suppresses_hybrid_and_rebalance_amounts_symmetrically():
    """
    Same near-target pool, both overweight-within-tolerance (Yen) and
    underweight-within-tolerance (Energie) must get 0 in hybride AND in
    rééquilibrage complet (rebalance_amount), not just in injection seule.
    """
    pools = _make_pools([
        ("Energie", "Offensive", 0.25, 24_900),   # within tolerance (under)
        ("Yen",     "Defensive", 0.25, 25_100),   # within tolerance (over)
        ("Or",      "Defensive", 0.25, 20_000),   # meaningfully underweight
        ("Asie",    "Offensive", 0.25, 30_000),   # meaningfully overweight
    ])
    results = compute_rebalancing(
        pools, liquidity_available=0.0, external_injection=0.0, tolerance_ok_pct=1.0
    )
    by_name = {r.name: r for r in results}

    assert by_name["Energie"].hybrid_amount == 0.0
    assert by_name["Energie"].rebalance_amount == 0.0
    assert by_name["Yen"].hybrid_amount == 0.0
    assert by_name["Yen"].rebalance_amount == 0.0
    # The genuinely off-target pools are unaffected.
    assert by_name["Or"].hybrid_amount > 0
    assert by_name["Asie"].hybrid_amount < 0


def test_tolerance_all_pools_within_band_recommends_nothing():
    """
    A well-balanced portfolio where every pool is already within tolerance:
    no mode should propose any trade — the leftover cash simply stays
    unallocated rather than being split into cosmetic micro-trades. Shape
    (not the figures) matches what live testing against real portfolio data
    surfaced: a small residual liquidity sweep on an already-balanced
    4-pool portfolio.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 25_000),
        ("Yen",     "Defensive", 0.25, 25_150),
        ("Energie", "Offensive", 0.25, 24_950),
        ("Or",      "Defensive", 0.25, 24_900),
    ])
    results = compute_rebalancing(
        pools, liquidity_available=10.0, external_injection=0.0, tolerance_ok_pct=1.0
    )
    assert all(r.injection_amount == 0.0 for r in results)
    assert all(r.hybrid_amount == 0.0 for r in results)
    assert all(r.rebalance_amount == 0.0 for r in results)


def test_tolerance_meaningful_apport_still_distributed_even_if_every_gap_rounds_to_ok():
    """
    Found via live testing against real production data: injecting a sum
    comparable to a few percent of an already well-balanced portfolio moves
    no single pool's gap past 1% of the new total, so per-pool suppression
    alone would leave the ENTIRE apport unallocated — a real, deliberate
    injection silently vanishing into "do nothing" recommendations. The
    fallback must kick in here (apport is clearly meaningful relative to the
    portfolio), unlike the tiny-leftover-cash case above.
    """
    pools = _make_pools([
        ("Asie",    "Offensive", 0.25, 25_000),
        ("Yen",     "Defensive", 0.25, 25_150),
        ("Energie", "Offensive", 0.25, 24_950),
        ("Or",      "Defensive", 0.25, 24_900),
    ])
    results = compute_rebalancing(
        pools, liquidity_available=10.0, external_injection=2_000.0, tolerance_ok_pct=1.0
    )
    total_injection = sum(r.injection_amount for r in results)
    total_hybrid = sum(r.hybrid_amount for r in results)
    assert total_injection == pytest.approx(2_010.0, abs=0.02)
    assert total_hybrid == pytest.approx(2_010.0, abs=0.02)


def test_tolerance_does_not_suppress_sole_pool_far_below_its_own_target():
    """
    Regression guard for the edge case that rules out gating tolerance on
    "today's gap vs total_current": a single pool targeting 100% of the
    portfolio is *always* exactly 100% of total_current by construction
    (there is nowhere else for the money to currently be), so gating on that
    would wrongly read as "already on target" even when it's genuinely far
    below its target vs total_after. Gating on total_after/total_current
    (the mode's own basis) instead must still recommend the full injection.
    """
    pools = _make_pools([("A", "Offensive", 1.0, 100.0)])
    results = compute_rebalancing(
        pools, liquidity_available=0.0, external_injection=1_000.0, tolerance_ok_pct=1.0
    )
    assert results[0].injection_amount == pytest.approx(1_000.0, abs=0.02)


# ---------------------------------------------------------------------------
# get_tolerance_ok_pct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tolerance_ok_pct_default_when_unset(db_session):
    assert await get_tolerance_ok_pct(db_session) == DEFAULT_TOLERANCE_OK_PCT


@pytest.mark.asyncio
async def test_get_tolerance_ok_pct_reads_valid_override(db_session):
    db_session.add(SystemSetting(key="rebalancing.tolerance_ok_pct", value="2.5"))
    await db_session.flush()
    assert await get_tolerance_ok_pct(db_session) == 2.5


@pytest.mark.asyncio
async def test_get_tolerance_ok_pct_falls_back_on_unparsable_value(db_session):
    db_session.add(SystemSetting(key="rebalancing.tolerance_ok_pct", value="not-a-number"))
    await db_session.flush()
    assert await get_tolerance_ok_pct(db_session) == DEFAULT_TOLERANCE_OK_PCT


# ---------------------------------------------------------------------------
# compute_injection_total_needed: minimum capital to reach all targets via
# injection alone (no selling), replacing the old frontend closed-form that
# didn't handle a near-target pool flipping underweight as the total grows.
# ---------------------------------------------------------------------------

def test_injection_total_needed_zero_when_all_pools_at_target():
    pools = _make_pools([
        ("Asie", "Offensive", 0.25, 25_000),
        ("Or", "Defensive", 0.25, 25_000),
        ("Yen", "Defensive", 0.25, 25_000),
        ("Energie", "Offensive", 0.25, 25_000),
    ])
    assert compute_injection_total_needed(pools) == pytest.approx(0.0, abs=0.01)


def test_injection_total_needed_empty_pools_returns_zero():
    assert compute_injection_total_needed([]) == pytest.approx(0.0, abs=0.01)


def test_injection_total_needed_single_iteration_matches_closed_form():
    """
    3 pools underweight by 2 500 each vs total_current=90 000, 1 pool ("Or")
    comfortably overweight enough to never flip underweight once the total
    grows to close the other three's gap (single-round convergence).
    """
    pools = _make_pools([
        ("Or", "Defensive", 0.25, 30_000),      # overweight, stays out
        ("Asie", "Offensive", 0.25, 20_000),    # underweight
        ("Energie", "Offensive", 0.25, 20_000),  # underweight
        ("Yen", "Defensive", 0.25, 20_000),     # underweight
    ])
    # shortfall = (22500-20000)*3 = 7500; sumTargetPct_uw = 0.75
    # total_needed = 7500 / (1 - 0.75) = 30000
    assert compute_injection_total_needed(pools) == pytest.approx(30_000.0, abs=0.5)


def test_injection_total_needed_cascades_when_pool_flips_underweight():
    """
    A pool comfortably at/above target vs total_current (D=50 000 vs a 25 000
    target on a 100 000 total) can still fall under ITS OWN target once the
    total grows enough to close the other three pools' gaps — the closed-form
    single-pass formula misses this; the iterative version must not.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.25, 5_000),
        ("B", "Offensive", 0.25, 15_000),
        ("C", "Defensive", 0.25, 30_000),
        ("D", "Defensive", 0.25, 50_000),
    ])
    # Round 1: underweight={A,B}, total_needed=60000, total_after=160000 → C (target 40000) flips in.
    # Round 2: underweight={A,B,C}, total_needed=100000, total_after=200000 → D (target 50000) stays
    # exactly at the boundary (not strictly below) → converges at 100000.
    assert compute_injection_total_needed(pools) == pytest.approx(100_000.0, abs=0.5)


def test_injection_total_needed_none_when_targets_overcommitted():
    """
    Defensive guard against malformed/degenerate input (e.g. a partial pool
    subset whose targets don't sum to 1): two pools both targeting 60% (sum
    120%, invalid for a real portfolio) and both genuinely underweight vs
    that inflated target — the >=0.9999 check fires immediately.
    """
    pools = _make_pools([
        ("A", "Offensive", 0.6, 10.0),
        ("B", "Defensive", 0.6, 10.0),
    ])
    assert compute_injection_total_needed(pools) is None


def test_injection_total_needed_none_when_untargeted_pool_holds_value():
    """
    A real, common, well-formed scenario (targets summing to exactly 1 across
    the active pools) still returns None: a "Legacy" pool with target_pct=0
    holding real money. Proof it's not a corner case but a mathematical
    certainty: with complement={last active pool, Legacy} at any round, the
    conservation identity forces current_P + legacy_value == target_P *
    total_after exactly — so current_P is *always* legacy_value below what a
    legacy-free portfolio would need, i.e. current_P < target_P*total_after
    by exactly legacy_value, which exceeds the 0.01 tolerance for any legacy
    holding above one cent. So the last active pool always gets pulled into
    the underweight set eventually, and None is inevitable, not incidental.
    This is the exact real-world shape that originally looked like a bug.
    """
    pools = _make_pools([
        ("Energie", "Offensive", 0.25, 35_583.15),
        ("Or", "Defensive", 0.25, 36_816.35),
        ("Yen", "Defensive", 0.25, 35_415.95),
        ("Legacy", "Offensive", 0.0, 242.94),
        ("Asie", "Offensive", 0.25, 35_420.48),
    ])
    assert compute_injection_total_needed(pools) is None


def test_injection_total_needed_finite_when_untargeted_pool_holds_negligible_value():
    """
    Mirror of the above with the untargeted pool's value below the 0.01
    tolerance: it must NOT block convergence (negligible dust shouldn't flip
    a real answer into "impossible").
    """
    pools = _make_pools([
        ("A", "Offensive", 0.5, 40_000.0),
        ("B", "Defensive", 0.5, 50_000.0),
        ("Dust", "Offensive", 0.0, 0.005),
    ])
    assert compute_injection_total_needed(pools) is not None


# ---------------------------------------------------------------------------
# find_untargeted_pools_with_value
# ---------------------------------------------------------------------------

def test_find_untargeted_pools_with_value_returns_only_zero_target_nonzero_value():
    pools = _make_pools([
        ("Asie", "Offensive", 0.25, 35_420.48),   # real target, excluded
        ("Legacy", "Offensive", 0.0, 242.94),     # zero target, real value — included
        ("Empty", "Defensive", 0.0, 0.0),         # zero target, zero value — excluded
        ("Dust", "Defensive", 0.0, 0.005),        # zero target, negligible value — excluded
    ])
    blocking = find_untargeted_pools_with_value(pools)
    assert [p.name for p in blocking] == ["Legacy"]


def test_find_untargeted_pools_with_value_empty_when_all_pools_targeted():
    pools = _make_pools([
        ("A", "Offensive", 0.5, 10_000.0),
        ("B", "Defensive", 0.5, 10_000.0),
    ])
    assert find_untargeted_pools_with_value(pools) == []
