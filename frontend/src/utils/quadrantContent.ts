// SPDX-License-Identifier: AGPL-3.0-or-later
import type { MacroQuadrant } from '../types';
import type { AllocationCategory } from './portfolioAllocation';

/**
 * Favorable/unfavorable read-out per quadrant per asset category — this app's own reasoning
 * about standard growth/inflation quadrant macro logic (a widely-taught framework, see e.g.
 * Bridgewater's "All Weather"/Fidelity's business-cycle guide), written independently. Per
 * docs/ROADMAP.md's explicit instruction, this is NOT sourced from or a paraphrase of Charles
 * Gave's "Maîtriser les quatre quadrants" material — no numeric return figures, no specific
 * wording from that source.
 */
export type Favorability = 'favorable' | 'defavorable';

export const QUADRANT_FAVORABILITY: Record<MacroQuadrant, Record<AllocationCategory, Favorability>> = {
  // Croissance + désinflation: earnings grow while discount rates ease — the classic
  // "everything works" backdrop for both equities and bonds. Gold has no inflation-hedge
  // case here and cash is a pure opportunity cost.
  goldilocks: { actions: 'favorable', obligations: 'favorable', or: 'defavorable', cash: 'defavorable' },
  // Croissance + inflation: nominal growth still supports equities, but rising rates hurt
  // bond prices and gold earns its keep as an inflation hedge; cash loses real value.
  overheating: { actions: 'favorable', obligations: 'defavorable', or: 'favorable', cash: 'defavorable' },
  // Ralentissement + désinflation: weak earnings hurt equities, but falling growth and
  // inflation both push rates down further — bonds rally, cash is a safe (if unexciting)
  // place to sit, gold has no clear catalyst either way.
  disinflationary_slowdown: { actions: 'defavorable', obligations: 'favorable', or: 'defavorable', cash: 'favorable' },
  // Ralentissement + inflation (stagflation): the worst case for both equities (weak growth,
  // margin pressure) and nominal bonds (inflation erodes real return) — gold is the classic
  // hedge, cash at least preserves nominal capital while the others fall.
  stagflation: { actions: 'defavorable', obligations: 'defavorable', or: 'favorable', cash: 'favorable' },
};

export const QUADRANT_ORDER: MacroQuadrant[] = [
  'goldilocks', 'overheating', 'disinflationary_slowdown', 'stagflation',
];

export const CATEGORY_ORDER: AllocationCategory[] = ['actions', 'obligations', 'or', 'cash'];
