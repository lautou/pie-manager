# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Rebalancing calculator.

Logic:
  - "Injection seule": inject proportionally to individual pool shortfalls vs
    total_AFTER. No per-strategy budget constraint — the Offensive/Defensive
    ratio emerges naturally from each pool's target allocation.
  - "Hybride": injection first, then sell overweight pools if needed.
  - "Full rebalance": buy/sell within current total to hit targets exactly.
"""

from dataclasses import dataclass
from app.services.price_service import r2


@dataclass
class PoolRebalanceInput:
    id: int
    name: str
    strategy: str       # "Offensive" | "Defensive"
    target_pct: float   # 0.25 = 25%
    current_value: float


@dataclass
class PoolRebalanceResult:
    id: int
    name: str
    strategy: str
    target_pct: float
    current_value: float
    current_pct: float
    target_value_after: float
    injection_amount: float   # how much new capital goes here (injection seule)
    rebalance_amount: float   # buy/sell without new capital (negative = sell)
    hybrid_amount: float      # combination of both
    # Fee estimates (0.0 when no commission configured)
    injection_fee: float = 0.0
    rebalance_fee: float = 0.0
    hybrid_fee: float = 0.0
    # Net amounts after fee deduction (preserving sign)
    injection_net: float = 0.0
    rebalance_net: float = 0.0
    hybrid_net: float = 0.0


def _compute_fee(amount: float, commission_pct: float, commission_min: float) -> float:
    """Return estimated fee for a trade of the given amount (0 if amount is 0)."""
    if amount == 0.0:
        return 0.0
    return r2(max(commission_min, abs(amount) * commission_pct / 100))


def find_untargeted_pools_with_value(pools: list[PoolRebalanceInput]) -> list[PoolRebalanceInput]:
    """
    Pools with (near-)zero target_pct that still hold real value (e.g. a
    "Legacy" pool no longer part of the active strategy). Any such pool
    holding more than a cent structurally guarantees compute_injection_total_needed
    returns None: since it can never receive or give up money via injection alone,
    it permanently occupies a share of total_after that the other pools (whose
    targets already sum to 100%) can never fully absorb, no matter how much is
    injected. Used to explain *why* full injection-only convergence is impossible.
    """
    return [p for p in pools if p.target_pct < 0.0001 and p.current_value > 0.01]


def compute_injection_total_needed(pools: list[PoolRebalanceInput]) -> float | None:
    """
    Minimum total capital (liquidity + external injection) needed so every pool
    reaches at least its target_pct, injecting only into pools currently
    underweight vs total_current — no selling, matching "injection seule".

    Growing the total pulls up every pool's euro target (target_pct * total_after),
    which can push an already near-target pool below its own target even though it
    never received a cent. Solved by fixed-point iteration: start from the pools
    underweight vs total_current, solve the closed-form total for that set, then
    check whether any pool outside the set now falls under its target at the
    resulting total_after; if so, add it and resolve. The underweight set only
    grows, so this converges in at most len(pools) rounds.

    Returns None when even an unlimited injection can't satisfy every pool (the
    underweight set's combined target_pct reaches 100%) — selling is required,
    see the Hybride/Rééquilibrage complet modes instead.
    """
    total_current = sum(p.current_value for p in pools)
    underweight_ids = {p.id for p in pools if p.current_value < total_current * p.target_pct - 0.01}

    total_needed = 0.0
    for _ in range(len(pools)):
        target_pct_uw = sum(p.target_pct for p in pools if p.id in underweight_ids)
        if target_pct_uw >= 0.9999:
            return None

        shortfall_uw = sum(
            p.target_pct * total_current - p.current_value
            for p in pools if p.id in underweight_ids
        )
        total_needed = shortfall_uw / (1 - target_pct_uw)
        total_after = total_current + total_needed

        newly_underweight = {
            p.id for p in pools
            if p.id not in underweight_ids and p.current_value < total_after * p.target_pct - 0.01
        }
        if not newly_underweight:
            break
        underweight_ids |= newly_underweight

    return r2(total_needed)


def compute_rebalancing(
    pools: list[PoolRebalanceInput],
    liquidity_available: float,  # LIQUIDITE.EURO balance
    external_injection: float,   # additional cash to inject (user input)
    commission_pct: float = 0.0,  # broker commission percentage (e.g. 0.1 = 0.1%)
    commission_min: float = 0.0,  # minimum fee per trade in EUR
) -> list[PoolRebalanceResult]:
    total_apport = liquidity_available + external_injection
    total_current = sum(p.current_value for p in pools)
    total_after = total_current + total_apport

    if total_after <= 0:
        return []

    # --- Per-pool shortfall vs total_after (injection seule) ---
    # Shortfall = how far below its target each pool will be after injection.
    # Proportional allocation: each pool receives (shortfall / total_shortfall) * total_apport.
    shortfalls: dict[int, float] = {
        p.id: max(0.0, total_after * p.target_pct - p.current_value)
        for p in pools
    }
    total_shortfall = sum(shortfalls.values())

    # --- Rebalance without injection (full rebalancing within current holdings) ---
    # Buy/sell within current total to reach target allocation.
    rebalance_amounts: dict[int, float] = {
        p.id: total_current * p.target_pct - p.current_value  # negative = sell
        for p in pools
    }

    results = []
    for p in pools:
        shortfall = shortfalls[p.id]

        # Injection seule: proportional to individual shortfall, no strategy constraint
        mon_apport = (shortfall / total_shortfall * total_apport) if total_shortfall > 0 else 0.0

        rebalance = rebalance_amounts[p.id]

        # Hybride: each pool reaches its target in the post-injection portfolio.
        # Overweight pools sell less as injection grows (target_after > target_before).
        hybrid = total_after * p.target_pct - p.current_value

        current_pct = (p.current_value / total_current * 100) if total_current > 0 else 0.0
        target_value_after = total_after * p.target_pct

        inj_rounded = r2(mon_apport)
        reb_rounded = r2(rebalance)
        hyb_rounded = r2(hybrid)

        inj_fee = _compute_fee(float(inj_rounded), commission_pct, commission_min)
        reb_fee = _compute_fee(float(reb_rounded), commission_pct, commission_min)
        hyb_fee = _compute_fee(float(hyb_rounded), commission_pct, commission_min)

        # Net = amount minus fee, preserving sign (buy: amount - fee; sell: amount + fee)
        def _net(amount: float, fee: float) -> float:
            if amount == 0.0:
                return 0.0
            return r2(amount - fee if amount > 0 else amount + fee)

        results.append(PoolRebalanceResult(
            id=p.id,
            name=p.name,
            strategy=p.strategy,
            target_pct=p.target_pct,
            current_value=r2(p.current_value),
            current_pct=round(current_pct, 2),
            target_value_after=r2(target_value_after),
            injection_amount=inj_rounded,
            rebalance_amount=reb_rounded,
            hybrid_amount=hyb_rounded,
            injection_fee=inj_fee,
            rebalance_fee=reb_fee,
            hybrid_fee=hyb_fee,
            injection_net=_net(float(inj_rounded), float(inj_fee)),
            rebalance_net=_net(float(reb_rounded), float(reb_fee)),
            hybrid_net=_net(float(hyb_rounded), float(hyb_fee)),
        ))

    return results
