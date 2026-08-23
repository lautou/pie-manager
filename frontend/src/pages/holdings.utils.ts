// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Holding, PoolDashboard } from '../types'

// Sentinel value for holdings that belong to no pool.
// The actual UI label is translated at the render site via t('holdings.unassigned').
export const UNASSIGNED_POOL_KEY = '__unassigned__'

export interface HoldingGroup {
  pool: PoolDashboard | null
  poolName: string
  holdings: Holding[]
}

export function groupAndSort(holdings: Holding[], pools: PoolDashboard[]): HoldingGroup[] {
  const byPool = new Map<string, Holding[]>()
  for (const h of holdings) {
    const key = h.pool_name ?? UNASSIGNED_POOL_KEY
    if (!byPool.has(key)) byPool.set(key, [])
    byPool.get(key)!.push(h)
  }

  const groups: HoldingGroup[] = []

  // Pools in dashboard order first
  for (const pool of pools) {
    const holdingsInPool = byPool.get(pool.name) ?? []
    holdingsInPool.sort((a, b) => a.product_name.localeCompare(b.product_name))
    groups.push({ pool, poolName: pool.name, holdings: holdingsInPool })
    byPool.delete(pool.name)
  }

  // Remaining holdings (unknown or null pool_name)
  for (const [key, holdingsInPool] of byPool.entries()) {
    holdingsInPool.sort((a, b) => a.product_name.localeCompare(b.product_name))
    groups.push({
      pool: null,
      poolName: key,
      holdings: holdingsInPool,
    })
  }

  return groups
}
