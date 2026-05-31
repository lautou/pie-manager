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

from app.services.rebalancing_service import PoolRebalanceInput, compute_rebalancing


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
