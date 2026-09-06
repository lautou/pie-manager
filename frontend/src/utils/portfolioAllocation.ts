// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Holding } from '../types';

/**
 * The 4 broad asset categories used by the growth/inflation quadrant's favorable/unfavorable
 * read-out (see docs/ROADMAP.md's "Quadrant macro-économique" entry) — deliberately coarser
 * than Product.instrument_type: ETF/SICAV-FCP/Action are all grouped under "actions" since
 * this app doesn't distinguish equity-oriented funds from bond-oriented ones at the
 * instrument_type level, and the quadrant framework only needs the 4-asset split anyway.
 */
export type AllocationCategory = 'actions' | 'obligations' | 'or' | 'cash';

const CATEGORY_BY_INSTRUMENT_TYPE: Record<string, AllocationCategory> = {
  'ETF': 'actions',
  'SICAV/FCP': 'actions',
  'Action': 'actions',
  'Obligation': 'obligations',
  'Or physique': 'or',
  'Cash': 'cash',
};

/** {category: percentage of total portfolio value}, e.g. {actions: 62.5, ...}. Holdings with
 * an unrecognized/missing instrument_type or zero value are excluded from both the numerator
 * and the total, rather than silently miscategorized. Returns {} for an empty/all-zero portfolio. */
export function computeAllocationByCategory(holdings: Holding[]): Record<AllocationCategory, number> {
  const totals: Record<AllocationCategory, number> = { actions: 0, obligations: 0, or: 0, cash: 0 };
  let grandTotal = 0;
  for (const h of holdings) {
    const category = h.instrument_type ? CATEGORY_BY_INSTRUMENT_TYPE[h.instrument_type] : undefined;
    if (!category || h.value_eur <= 0) continue;
    totals[category] += h.value_eur;
    grandTotal += h.value_eur;
  }
  if (grandTotal === 0) return { actions: 0, obligations: 0, or: 0, cash: 0 };
  return {
    actions: (totals.actions / grandTotal) * 100,
    obligations: (totals.obligations / grandTotal) * 100,
    or: (totals.or / grandTotal) * 100,
    cash: (totals.cash / grandTotal) * 100,
  };
}
