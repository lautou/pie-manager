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

export interface RebalancingPoolInput {
  target_pct: number
  current_value: number
  current_pct: number
}

export interface RebalancingStatus {
  totalNeeded: number
  capitalGap: number
  isFullyRebalanced: boolean
}

/**
 * Compute minimum injection needed to bring all underweight pools to target,
 * and whether the current budget is sufficient.
 *
 * Formula: X = shortfall / (1 - sumTargetPct_underweight)
 * This is injection-independent — it depends only on current allocations.
 */
export function computeRebalancingStatus(
  pools: RebalancingPoolInput[],
  totalCurrent: number,
  budget: number,
): RebalancingStatus {
  const underweightPools = pools.filter(
    (p) => p.current_value < totalCurrent * p.target_pct - 0.01,
  )
  const sumUnderweightTargetPct = underweightPools.reduce((s, p) => s + p.target_pct, 0)
  const sumShortfalls = underweightPools.reduce(
    (s, p) => s + (p.target_pct * totalCurrent - p.current_value),
    0,
  )
  const totalNeeded =
    sumUnderweightTargetPct < 0.9999
      ? sumShortfalls / (1 - sumUnderweightTargetPct)
      : sumShortfalls
  const capitalGap = totalNeeded - budget
  const isFullyRebalanced = budget >= totalNeeded - 0.5
  return { totalNeeded, capitalGap, isFullyRebalanced }
}
