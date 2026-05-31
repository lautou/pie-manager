/**
 * Tests for pure logic extracted from PositionsPage.
 *
 * groupAndSort:  groups positions by pool name, respects pool order, sorts by value
 * computeRebalancingStatus: minimum injection needed, capital gap, sufficiency flag
 */
import { describe, it, expect } from 'vitest'
import { groupAndSort, computeRebalancingStatus } from './holdings.utils'
import type { HoldingGroup } from './holdings.utils'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pos(overrides: Partial<{
  ticker: string; pool_name: string | null; value_eur: number;
  product_name: string; quantity: number; last_price: number;
  last_price_date: string | null; last_price_source: string; currency: string;
  pool_id: number | null;
}>): any {
  return {
    ticker: 'TICK.PA',
    pool_name: 'Asie',
    pool_id: 1,
    value_eur: 1000,
    product_name: 'Test product',
    quantity: 10,
    last_price: 100,
    last_price_date: '2025-01-01',
    last_price_source: 'yfinance',
    currency: 'EUR',
    ...overrides,
  }
}

let _nextId = 1
function pool(name: string, strategy = 'Offensive', target_pct = 0.25, current_pct = 25): any {
  return { id: _nextId++, name, strategy, target_pct, current_pct, current_value_eur: 0, gap_pct: 0 }
}

// ---------------------------------------------------------------------------
// groupAndSort
// ---------------------------------------------------------------------------

describe('groupAndSort', () => {
  it('groups holdings by pool_name', () => {
    const positions = [
      pos({ ticker: 'A', pool_name: 'Asie', value_eur: 1000 }),
      pos({ ticker: 'B', pool_name: 'Asie', value_eur: 500 }),
      pos({ ticker: 'C', pool_name: 'Or', value_eur: 2000 }),
    ]
    const groups = groupAndSort(positions, [pool('Asie'), pool('Or', 'Defensive')])
    expect(groups).toHaveLength(2)
    expect(groups[0].poolName).toBe('Asie')
    expect(groups[0].holdings).toHaveLength(2)
    expect(groups[1].poolName).toBe('Or')
    expect(groups[1].holdings).toHaveLength(1)
  })

  it('sorts positions alphabetically by product_name within each pool', () => {
    const positions = [
      pos({ ticker: 'C', pool_name: 'Asie', product_name: 'Zebra Fund', value_eur: 5000 }),
      pos({ ticker: 'A', pool_name: 'Asie', product_name: 'Alpha Fund', value_eur: 100 }),
      pos({ ticker: 'B', pool_name: 'Asie', product_name: 'Middle Fund', value_eur: 2000 }),
    ]
    const groups = groupAndSort(positions, [pool('Asie')])
    const names = groups[0].holdings.map((p: any) => p.product_name)
    expect(names).toEqual(['Alpha Fund', 'Middle Fund', 'Zebra Fund'])
  })

  it('respects pool order from the pools array', () => {
    const positions = [
      pos({ ticker: 'X', pool_name: 'Or', value_eur: 1000 }),
      pos({ ticker: 'Y', pool_name: 'Asie', value_eur: 500 }),
    ]
    const groups = groupAndSort(positions, [pool('Asie'), pool('Or')])
    expect(groups[0].poolName).toBe('Asie')
    expect(groups[1].poolName).toBe('Or')
  })

  it('places positions with null pool_name into unassigned key after known pools', () => {
    const positions = [
      pos({ ticker: 'KNOWN', pool_name: 'Asie', value_eur: 1000 }),
      pos({ ticker: 'ORPHAN', pool_name: null, value_eur: 500 }),
    ]
    const groups = groupAndSort(positions, [pool('Asie')])
    expect(groups).toHaveLength(2)
    expect(groups[0].poolName).toBe('Asie')
    expect(groups[1].poolName).toBe('__unassigned__')
    expect(groups[1].pool).toBeNull()
  })

  it('places positions with an unknown pool_name (not in pools) after known pools', () => {
    const positions = [pos({ pool_name: 'OldPool', value_eur: 999 })]
    const groups = groupAndSort(positions, [])
    expect(groups).toHaveLength(1)
    expect(groups[0].poolName).toBe('OldPool')
    expect(groups[0].pool).toBeNull()
  })

  it('sorts unassigned-pool positions alphabetically (exercises second sort comparator)', () => {
    const positions = [
      pos({ ticker: 'Z', pool_name: 'Legacy', product_name: 'Zebra Fund', value_eur: 5000 }),
      pos({ ticker: 'A', pool_name: 'Legacy', product_name: 'Alpha Fund', value_eur: 100 }),
    ]
    const groups = groupAndSort(positions, [])
    const names = groups[0].holdings.map((p: any) => p.product_name)
    expect(names).toEqual(['Alpha Fund', 'Zebra Fund'])
  })

  it('returns one group per pool even if a pool has no positions', () => {
    const groups = groupAndSort([], [pool('Asie'), pool('Or')])
    expect(groups).toHaveLength(2)
    expect(groups.every((g: HoldingGroup) => g.holdings.length === 0)).toBe(true)
  })

  it('attaches the pool object to the group for known pools', () => {
    const knownPool = pool('Asie')
    const positions = [pos({ pool_name: 'Asie' })]
    const groups = groupAndSort(positions, [knownPool])
    expect(groups[0].pool).toBe(knownPool)
  })
})

// ---------------------------------------------------------------------------
// computeRebalancingStatus
// ---------------------------------------------------------------------------

describe('computeRebalancingStatus', () => {
  it('returns totalNeeded=0 when all pools are at their target', () => {
    const pools = [
      { target_pct: 0.25, current_value: 25000, current_pct: 25 },
      { target_pct: 0.25, current_value: 25000, current_pct: 25 },
      { target_pct: 0.25, current_value: 25000, current_pct: 25 },
      { target_pct: 0.25, current_value: 25000, current_pct: 25 },
    ]
    const { totalNeeded, isFullyRebalanced } = computeRebalancingStatus(pools, 100000, 1000)
    expect(totalNeeded).toBeCloseTo(0, 0)
    expect(isFullyRebalanced).toBe(true)
  })

  it('detects insufficient capital when underweight pools need more than budget', () => {
    // Pool A: 25% target at 20% → underweight by 5 000 €
    const totalCurrent = 100000
    const pools = [
      { target_pct: 0.25, current_value: 30000, current_pct: 30 },  // overweight
      { target_pct: 0.25, current_value: 20000, current_pct: 20 },  // underweight
    ]
    const budget = 1000  // far too small
    const { isFullyRebalanced, capitalGap, totalNeeded } = computeRebalancingStatus(pools, totalCurrent, budget)
    expect(totalNeeded).toBeGreaterThan(budget)
    expect(capitalGap).toBeCloseTo(totalNeeded - budget, 1)
    expect(isFullyRebalanced).toBe(false)
  })

  it('computes totalNeeded via the shortfall / (1 - sumTargetPct) formula', () => {
    // Pool A: 25% target, current 20 000 (20%) → underweight
    // Pool B: 25% target, current 30 000 (30%) → overweight (excluded)
    // totalCurrent = 100 000, budget = 0
    // shortfall = 0.25 * 100 000 - 20 000 = 5 000
    // sumTargetPct_underweight = 0.25
    // totalNeeded = 5 000 / (1 - 0.25) = 6 666.67
    const pools = [
      { target_pct: 0.25, current_value: 20000, current_pct: 20 },
      { target_pct: 0.25, current_value: 30000, current_pct: 30 },
    ]
    const { totalNeeded } = computeRebalancingStatus(pools, 100000, 0)
    expect(totalNeeded).toBeCloseTo(6666.67, 0)
  })

  it('isFullyRebalanced uses 0.50€ floating-point tolerance', () => {
    const pools = [{ target_pct: 0.25, current_value: 20000, current_pct: 20 }]
    const { totalNeeded } = computeRebalancingStatus(pools, 100000, 0)
    // Budget exactly equal to totalNeeded → should be fully rebalanced
    const { isFullyRebalanced } = computeRebalancingStatus(pools, 100000, totalNeeded)
    expect(isFullyRebalanced).toBe(true)
    // Budget 1€ below → not rebalanced (gap > 0.5€ tolerance)
    const { isFullyRebalanced: notEnough } = computeRebalancingStatus(pools, 100000, totalNeeded - 1)
    expect(notEnough).toBe(false)
  })

  it('handles empty pool list gracefully', () => {
    const { totalNeeded, capitalGap, isFullyRebalanced } = computeRebalancingStatus([], 100000, 5000)
    expect(totalNeeded).toBe(0)
    expect(capitalGap).toBeCloseTo(-5000, 0)  // surplus
    expect(isFullyRebalanced).toBe(true)
  })

  it('handles edge case where all pools are underweight (sumTargetPct ≈ 1)', () => {
    // If all pools are underweight and target_pct sums to ~1, use sumShortfalls directly
    const pools = [
      { target_pct: 0.5, current_value: 0, current_pct: 0 },
      { target_pct: 0.5, current_value: 0, current_pct: 0 },
    ]
    // sumTargetPct = 1.0 ≥ 0.9999 → totalNeeded = sumShortfalls directly
    // shortfall for each: 0.5 * 100000 - 0 = 50000, total = 100000
    const { totalNeeded } = computeRebalancingStatus(pools, 100000, 0)
    expect(totalNeeded).toBeCloseTo(100000, 0)
  })

  it('capitalGap is negative when budget exceeds totalNeeded (surplus)', () => {
    const pools = [{ target_pct: 0.25, current_value: 20000, current_pct: 20 }]
    const { totalNeeded } = computeRebalancingStatus(pools, 100000, 0)
    const { capitalGap } = computeRebalancingStatus(pools, 100000, totalNeeded + 1000)
    expect(capitalGap).toBeCloseTo(-1000, 0)
  })
})
