// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { computeLossHarvestingPlan } from './lossHarvesting';
import type { FiscalLossCandidate } from '../api/queries';
import type { Broker, CommissionTier } from '../types';

function candidate(overrides: Partial<FiscalLossCandidate>): FiscalLossCandidate {
  return {
    account_id: 1,
    ticker: 'TICK.DE',
    product_name: 'Some ETF',
    qty_held: 100,
    cump: 10,
    current_value_eur: 900,
    unrealized_pv: -100,
    ...overrides,
  };
}

function broker(id: number, commission_schedule: CommissionTier[] | null): Broker {
  return {
    id,
    portfolio_ids: [1],
    name: `Broker ${id}`,
    currency: 'EUR',
    commission_schedule,
    allowed_tickers: null,
    withdrawal_fee_eur: 0,
    withdrawal_first_free: false,
    commission_profile: null,
    commission_sale_rate: 0,
    include_fees_in_cump: false,
    monthly_free_eur: null,
    above_monthly_rate: 0,
    weekend_rate: null,
  };
}

const FLAT_3E: CommissionTier[] = [{ type: 'flat', up_to: null, value: 3 }];
const IBKR_TIERED: CommissionTier[] = [
  { type: 'flat', up_to: 8333, value: 1.25 },
  { type: 'percent', up_to: 193333, value: 0.00015 },
  { type: 'flat', up_to: null, value: 29 },
];

const NO_BROKERS = new Map<number, Broker>();

describe('computeLossHarvestingPlan', () => {
  it('returns an empty plan when target is zero or negative', () => {
    expect(computeLossHarvestingPlan([candidate({})], 0, false, NO_BROKERS)).toEqual({ lines: [], covered: 0, shortfall: 0 });
    expect(computeLossHarvestingPlan([candidate({})], -5, false, NO_BROKERS)).toEqual({ lines: [], covered: 0, shortfall: 0 });
  });

  it('uses a single candidate whose full loss exactly covers the target, never touching a later one (no broker on file -> zero fee)', () => {
    const candidates = [
      candidate({ ticker: 'A', unrealized_pv: -100, qty_held: 100 }),
      candidate({ ticker: 'B', unrealized_pv: -50, qty_held: 100 }),
    ];
    const plan = computeLossHarvestingPlan(candidates, 100, false, NO_BROKERS);
    expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 100 }]);
    expect(plan.covered).toBe(100);
    expect(plan.shortfall).toBe(0);
  });

  it('fully consumes an earlier candidate then cuts off partially on the next, rounding up when not fractionable', () => {
    const candidates = [
      candidate({ ticker: 'A', unrealized_pv: -100, qty_held: 100 }), // per-unit loss 1
      candidate({ ticker: 'B', unrealized_pv: -50, qty_held: 100 }), // per-unit loss 0.5
    ];
    const plan = computeLossHarvestingPlan(candidates, 110, false, NO_BROKERS);
    expect(plan.lines).toEqual([
      { account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 100 },
      { account_id: 1, ticker: 'B', product_name: 'Some ETF', qty: 20, estimated_loss: 10 }, // exact 10/0.5=20, no rounding needed
    ]);
    expect(plan.covered).toBe(110);
    expect(plan.shortfall).toBe(0);
  });

  it('rounds the cutoff quantity up to a whole unit when fractionable is false', () => {
    // per-unit loss = 100/100 = 1; remaining after nothing else = 50.4 -> ceil(50.4) = 51
    const plan = computeLossHarvestingPlan([candidate({ ticker: 'A', unrealized_pv: -100, qty_held: 100 })], 50.4, false, NO_BROKERS);
    expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 51, estimated_loss: 51 }]);
    expect(plan.covered).toBe(50.4);
    expect(plan.shortfall).toBe(0);
  });

  it('uses the exact fractional quantity when fractionable is true', () => {
    const plan = computeLossHarvestingPlan([candidate({ ticker: 'A', unrealized_pv: -100, qty_held: 100 })], 50.4, true, NO_BROKERS);
    expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 50.4, estimated_loss: 50.4 }]);
    expect(plan.covered).toBe(50.4);
    expect(plan.shortfall).toBe(0);
  });

  it('takes the whole position when rounding the cutoff pushes past qty_held, and stops (no true residual)', () => {
    // per-unit loss = 1; target 99.5 -> ceil(99.5) = 100 = qty_held, so the whole position is taken
    const plan = computeLossHarvestingPlan([candidate({ ticker: 'A', unrealized_pv: -100, qty_held: 100 })], 99.5, false, NO_BROKERS);
    expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 100 }]);
    expect(plan.covered).toBe(99.5);
    expect(plan.shortfall).toBe(0);
  });

  it('reports a shortfall when every candidate combined cannot cover the target', () => {
    const candidates = [
      candidate({ ticker: 'A', unrealized_pv: -30, qty_held: 100 }),
      candidate({ ticker: 'B', unrealized_pv: -20, qty_held: 100 }),
    ];
    const plan = computeLossHarvestingPlan(candidates, 100, false, NO_BROKERS);
    expect(plan.lines).toEqual([
      { account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 30 },
      { account_id: 1, ticker: 'B', product_name: 'Some ETF', qty: 100, estimated_loss: 20 },
    ]);
    expect(plan.covered).toBe(50);
    expect(plan.shortfall).toBe(50);
  });

  describe('real broker commission is folded into the estimated loss', () => {
    it('adds the flat Degiro-style fee to a fully-consumed line', () => {
      // unrealized_pv=-100, current_value_eur=900 -> fee = flat 3 regardless of amount
      const brokers = new Map([[1, broker(1, FLAT_3E)]]);
      const plan = computeLossHarvestingPlan([candidate({ ticker: 'A' })], 103, false, brokers);
      expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 103 }]);
      expect(plan.covered).toBe(103);
      expect(plan.shortfall).toBe(0);
    });

    it('solves the cutoff quantity net of the flat fee, converging in one correction', () => {
      // per-unit gross loss = 1, price/unit = 9 (900/100). Full line net loss would be 103,
      // but target 53 needs a partial: qty=50 gross=50, +3 flat fee = 53 exactly.
      const brokers = new Map([[1, broker(1, FLAT_3E)]]);
      const plan = computeLossHarvestingPlan([candidate({ ticker: 'A' })], 53, false, brokers);
      expect(plan.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 50, estimated_loss: 53 }]);
      expect(plan.covered).toBe(53);
      expect(plan.shortfall).toBe(0);
    });

    it('converges for a tiered (IBKR-style) schedule whose fee itself depends on the traded amount', () => {
      // qty_held=10000, current_value_eur=100000 (price/unit=10), unrealized_pv=-20000 (per-unit loss 2).
      // Full-line fee sits in the percent tier (100000 -> 15€), full net loss = 20015.
      const brokers = new Map([[1, broker(1, IBKR_TIERED)]]);
      const big = candidate({ ticker: 'A', qty_held: 10000, current_value_eur: 100000, unrealized_pv: -20000 });

      const full = computeLossHarvestingPlan([big], 20015, false, brokers);
      expect(full.lines).toEqual([{ account_id: 1, ticker: 'A', product_name: 'Some ETF', qty: 10000, estimated_loss: 20015 }]);
      expect(full.covered).toBe(20015);
      expect(full.shortfall).toBe(0);

      // Cutoff case: target picked so the fee-ignorant first guess and the fee-aware
      // converged quantity land in different commission tiers (percent vs. flat) —
      // this only lands exactly on target if the iterative refinement actually re-derives
      // the fee at the converged quantity, not just at the naive first guess.
      const partial = computeLossHarvestingPlan([big], 1667.5, false, brokers);
      expect(partial.shortfall).toBe(0);
      expect(partial.covered).toBeCloseTo(1667.5, 6);
      expect(partial.lines).toHaveLength(1);
      expect(partial.lines[0].qty).toBeLessThan(big.qty_held);
    });

    it('gives each candidate its own fee from its own account/broker, even for the same ticker', () => {
      const brokers = new Map([
        [1, broker(1, FLAT_3E)],
        [2, broker(2, IBKR_TIERED)],
      ]);
      const candidates = [
        candidate({ account_id: 1, ticker: 'SHARED.DE', unrealized_pv: -100, qty_held: 100, current_value_eur: 900 }),
        candidate({ account_id: 2, ticker: 'SHARED.DE', unrealized_pv: -50, qty_held: 100, current_value_eur: 900 }),
      ];
      // Target covered entirely by the first (worse) candidate's full net loss (100 + 3 = 103).
      const plan = computeLossHarvestingPlan(candidates, 103, false, brokers);
      expect(plan.lines).toEqual([
        { account_id: 1, ticker: 'SHARED.DE', product_name: 'Some ETF', qty: 100, estimated_loss: 103 },
      ]);
      expect(plan.covered).toBe(103);
    });

    it('falls back to a zero fee when the candidate account has no broker on file, instead of crashing', () => {
      const plan = computeLossHarvestingPlan([candidate({ ticker: 'A', account_id: 999 })], 100, false, NO_BROKERS);
      expect(plan.lines).toEqual([{ account_id: 999, ticker: 'A', product_name: 'Some ETF', qty: 100, estimated_loss: 100 }]);
    });
  });
});
