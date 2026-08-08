/**
 * Tests for pure logic extracted from HoldingsPage.
 *
 * groupAndSort: groups positions by pool name, respects pool order, sorts by value
 */
import { describe, it, expect } from 'vitest'
import { groupAndSort } from './holdings.utils'
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
