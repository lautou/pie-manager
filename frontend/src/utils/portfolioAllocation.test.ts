// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { computeAllocationByCategory } from './portfolioAllocation';
import type { Holding } from '../types';

function makeHolding(overrides: Partial<Holding>): Holding {
  return {
    ticker: 'X', product_name: 'X', category: 'Actif', instrument_type: 'ETF',
    pool_id: null, pool_name: null, quantity: 1, last_price: 1, last_price_date: null,
    last_price_source: 'manual', value_eur: 100, currency: 'EUR',
    ...overrides,
  };
}

describe('computeAllocationByCategory', () => {
  it('returns all-zero for an empty holdings list', () => {
    expect(computeAllocationByCategory([])).toEqual({ actions: 0, obligations: 0, or: 0, cash: 0 });
  });

  it('groups ETF/SICAV-FCP/Action under actions', () => {
    const holdings = [
      makeHolding({ instrument_type: 'ETF', value_eur: 50 }),
      makeHolding({ instrument_type: 'SICAV/FCP', value_eur: 30 }),
      makeHolding({ instrument_type: 'Action', value_eur: 20 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({ actions: 100, obligations: 0, or: 0, cash: 0 });
  });

  it('splits across all 4 categories proportionally', () => {
    const holdings = [
      makeHolding({ instrument_type: 'ETF', value_eur: 40 }),
      makeHolding({ instrument_type: 'Obligation', value_eur: 30 }),
      makeHolding({ instrument_type: 'Or physique', value_eur: 20 }),
      makeHolding({ instrument_type: 'Cash', value_eur: 10 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({
      actions: 40, obligations: 30, or: 20, cash: 10,
    });
  });

  it('excludes a holding with an unrecognized instrument_type', () => {
    const holdings = [
      makeHolding({ instrument_type: 'ETF', value_eur: 50 }),
      makeHolding({ instrument_type: 'Unknown', value_eur: 50 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({ actions: 100, obligations: 0, or: 0, cash: 0 });
  });

  it('excludes a holding with a missing instrument_type', () => {
    const holdings = [
      makeHolding({ instrument_type: 'ETF', value_eur: 50 }),
      makeHolding({ instrument_type: null, value_eur: 50 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({ actions: 100, obligations: 0, or: 0, cash: 0 });
  });

  it('excludes a holding with zero or negative value_eur', () => {
    const holdings = [
      makeHolding({ instrument_type: 'ETF', value_eur: 100 }),
      makeHolding({ instrument_type: 'Obligation', value_eur: 0 }),
      makeHolding({ instrument_type: 'Cash', value_eur: -5 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({ actions: 100, obligations: 0, or: 0, cash: 0 });
  });

  it('returns all-zero when every holding is excluded (grand total zero)', () => {
    const holdings = [
      makeHolding({ instrument_type: 'Unknown', value_eur: 50 }),
      makeHolding({ instrument_type: 'ETF', value_eur: 0 }),
    ];
    expect(computeAllocationByCategory(holdings)).toEqual({ actions: 0, obligations: 0, or: 0, cash: 0 });
  });
});
