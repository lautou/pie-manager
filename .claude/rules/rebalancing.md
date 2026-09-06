---
paths:
  - "backend/app/services/rebalancing_service.py"
  - "frontend/src/pages/RebalancingPage.tsx"
  - "frontend/src/pages/GlobalConfigPage.tsx"
---

## Rebalancing — "après %" denominator depends on simulation mode

`RebalancingPage.tsx` has 3 simulation modes: `contribution` (injection only), `hybrid`
(injection + sells if needed), `hard` (Rééquilibrage complet — sells overweight pools and
reinvests into underweight ones, **no external injection**). The displayed post-trade
percentage for a pool (`afterPct = afterValue / afterTotal * 100`) must use a
**mode-dependent denominator**:
- `contribution`/`hybrid`: `rebalData.total_after` (current + available liquidity + external
  injection) — correct, since these modes actually grow the portfolio total.
- `hard`: `total_current` — the backend's `rebalance_amount` for this mode is computed
  against `total_current` alone (no injection), so dividing by `total_after` instead (which
  still includes any leftover uninvested cash) inflates the denominator and makes every pool
  appear to land below its target even when the underlying trade amounts are correct (e.g.
  displaying 24.2% instead of 25.0% with a spurious "-0.8%" gap, for trades that were
  actually exactly on target).

Guard `afterTotal > 0 ? afterValue / afterTotal * 100 : 0` — a zero denominator (empty
portfolio with a pending injection) must fall back to 0%, not NaN/Infinity.

## Rebalancing — "capital insuffisant" needed-amount is backend-computed, not a frontend estimate

`compute_injection_total_needed` (`rebalancing_service.py`) answers "how much total capital
(liquidity + injection) would it take to bring every pool to at least its target via
injection alone, no selling" — returned as `injection_total_needed` in the rebalancing API
response and consumed as-is by `RebalancingPage.tsx`'s "Injection seule" sufficiency banner.
It solves by fixed-point iteration, not a single closed-form pass: growing the total pulls up
every pool's euro target, which can push an already near-target pool below its own target
even though it received no money — the underweight set is recomputed and grown until it
stabilizes. Returns `None` when even unlimited injection can't satisfy every pool (the
underweight set's combined target_pct reaches 100%).

**`None` is a common, expected real-world outcome — not just a defensive guard.** Correction
of an earlier (wrong) claim in this file: a "Legacy" pool with `target_pct=0` holding real
value (an old holding no longer part of the active strategy) makes `None` mathematically
*guaranteed*, not just possible, the moment its value exceeds one cent — proven via the
iteration's own conservation identity: with that pool as the sole remaining complement
member, its current value must equal `target_pct(=0) * total_after - legacy_value`, forcing
it into the underweight set at some iteration no matter how large `total_after` grows, since
the active pools already target 100% between them and can never fully absorb a total that
also includes the legacy pool's frozen, off-target money. `find_untargeted_pools_with_value`
(pools with `target_pct≈0` and `current_value > 0.01`) identifies the actual blocking pool(s),
returned as `injection_blocking_pools` in the API response — `RebalancingPage.tsx` names them
in the banner (`insufficientImpossibleWithCause`) instead of a vague "even with unlimited
capital" message. Only truly malformed input (e.g. a partial pool subset whose targets don't
sum to 1) hits this without an identifiable blocking pool, in which case the banner falls back
to the generic `insufficientImpossible` message.

**Why backend, not frontend:** an earlier frontend-only version (`computeRebalancingStatus`,
deleted) used a single-pass closed form completely decoupled from the actual allocation
algorithm and from the pool set it was fed (a filtered subset whose current values didn't sum
to the `totalCurrent` argument it was given) — it under-estimated the true needed amount in
exactly the flip-underweight scenario above, producing a "manque : 4 737€" banner alongside
"Acheter 5€/8€/8€" suggestions that looked contradictory to the user. Moving the computation
into the same service module as the real allocation algorithm removes the possibility of the
two drifting apart.

## Rebalancing — gap severity thresholds are configurable, not hardcoded

`rebalancing.tolerance_ok_pct` (default 1) and `rebalancing.tolerance_warning_pct` (default 2)
are `SystemSetting` rows edited via the "Rééquilibrage — seuils de tolérance" card in
Configuration générale (`GlobalConfigPage.tsx`), read in `RebalancingPage.tsx` via
`useSystemSetting`. A single absolute-value severity scale (`|gap| < ok` → green,
`ok ≤ |gap| < warning` → orange, `|gap| ≥ warning` → red) drives the per-pool label and both
the before/after allocation bars uniformly — previously these were three separate, mutually
inconsistent hardcoded thresholds (an asymmetric -0.5%/+1.5% window for the label, ±2% for the
before-bar, ±1.5% for the after-bar).

**The zero-action pool label is self-explanatory and severity-only, no over/under direction**
(`onTargetLabel`/`warningLabel`/`dangerLabel` in `RebalancingPage.tsx`, e.g. "Déséquilibre
léger (écart entre 1% et 2% — à surveiller)") — the actual configured `ok`/`warning` values are
interpolated into the text itself, never hardcoded, so the label stays accurate if those
settings change. This deliberately drops the earlier "Surpondéré"/"Sous-pondéré" distinction
from the *visible* label (a simplification, not an oversight) — but the underweight case
(`gapBefore < 0` and non-ok) still wraps the label in `underweightTooltip`, since "capital
insufficient to act" is real explanatory context a bare severity level can't convey.

## Rebalancing — banner/card copy conventions

Every "capital" banner (Injection seule and Hybride, sufficient/insufficient/partial/
impossible) appends `liquidityIncluded` ("Incluant liquidités à répartir : {{liquidity}}.") on
its own line, where `{{liquidity}}` is `total_apport` (liquidity + any typed injection) — not
liquidity alone. An earlier version showed just the liquidity portion, reasoning that naming
two separately-computed figures (liquidity vs. injected) risked one of them being wrong; user
feedback reversed this — the combined `total_apport` is what's actually being distributed in
the simulation, and splitting it back out added confusion, not clarity. The "impossible"
banner's own explanation and its "switch mode" call-to-action are two more separate lines
(`insufficientImpossible(WithCause)` / `switchModeHint`), not one run-on sentence. Each pool
card shows one visible "Cible : X%" label above the
Actuel/Après bars (shared by both, since the target doesn't change between them) and a
per-row `Écart actuel` / `Écart cible` label next to each bar instead of one combined line at
the bottom — the combined line used to sit far from the "Actuel" row it partly described.

## Rebalancing — "Contexte macro-économique" card

The card at the top of the page (region selector + `QuadrantCard`, defaulting to the first
`useMacroRegions()` entry) is the portfolio-scoped half of the growth/inflation quadrant
feature — see `.claude/rules/macro-indicators.md`'s "Growth/inflation quadrant classifier"
section for the full feature (classifier math, the global `/indicators` page's own
quadrant-only instance, and why this page passes an explicit `portfolioId` instead of the
`?from=` URL param the feature used to rely on). Purely informational, same as the rest of this
feature — never feeds into any rebalancing calculation on this page.

