// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { computeCommission, TTF_RATE, isWeekendNewYork, computeRevolutFXCommission, computeMonthlyLimitFXCommission } from './commission';
import type { CommissionTier } from '../types';

const DEGIRO: CommissionTier[] = [
  { up_to: null, type: 'flat', value: 3.0 },
];

const BOURSEDIRECT: CommissionTier[] = [
  { up_to: 198,  type: 'percent', value: 0.005 },
  { up_to: 500,  type: 'flat',    value: 0.99 },
  { up_to: 1000, type: 'flat',    value: 1.90 },
  { up_to: 2000, type: 'flat',    value: 2.90 },
  { up_to: 4400, type: 'flat',    value: 3.80 },
  { up_to: null, type: 'percent', value: 0.0009 },
];

const IBKR: CommissionTier[] = [
  { up_to: 8333,   type: 'flat',    value: 1.25 },
  { up_to: 193333, type: 'percent', value: 0.00015 },
  { up_to: null,   type: 'flat',    value: 29.0 },
];

describe('computeCommission', () => {
  describe('Degiro (flat 3€)', () => {
    it('returns 3.00 for any amount', () => {
      expect(computeCommission(100, DEGIRO)).toBe(3.0);
      expect(computeCommission(10000, DEGIRO)).toBe(3.0);
      expect(computeCommission(0.01, DEGIRO)).toBe(3.0);
    });
  });

  describe('BourseDirect PEA (6 tiers)', () => {
    it('≤198€ uses 0.5%', () => {
      expect(computeCommission(100, BOURSEDIRECT)).toBeCloseTo(0.5, 5);
      expect(computeCommission(198, BOURSEDIRECT)).toBeCloseTo(0.99, 5);
    });
    it('≤500€ uses flat 0.99€', () => {
      expect(computeCommission(199, BOURSEDIRECT)).toBe(0.99);
      expect(computeCommission(500, BOURSEDIRECT)).toBe(0.99);
    });
    it('≤1000€ uses flat 1.90€', () => {
      expect(computeCommission(501, BOURSEDIRECT)).toBe(1.90);
      expect(computeCommission(1000, BOURSEDIRECT)).toBe(1.90);
    });
    it('≤2000€ uses flat 2.90€', () => {
      expect(computeCommission(1001, BOURSEDIRECT)).toBe(2.90);
      expect(computeCommission(2000, BOURSEDIRECT)).toBe(2.90);
    });
    it('≤4400€ uses flat 3.80€', () => {
      expect(computeCommission(2001, BOURSEDIRECT)).toBe(3.80);
      expect(computeCommission(4400, BOURSEDIRECT)).toBe(3.80);
    });
    it('>4400€ uses 0.09%', () => {
      expect(computeCommission(4401, BOURSEDIRECT)).toBeCloseTo(4401 * 0.0009, 5);
      expect(computeCommission(10000, BOURSEDIRECT)).toBeCloseTo(9.0, 5);
    });
  });

  describe('IBKR (clamp 0.015%, min 1.25€, max 29€)', () => {
    it('≤8333€ uses flat 1.25€ (floor)', () => {
      expect(computeCommission(100, IBKR)).toBe(1.25);
      expect(computeCommission(8333, IBKR)).toBe(1.25);
    });
    it('8334–193333€ uses 0.015%', () => {
      expect(computeCommission(10000, IBKR)).toBeCloseTo(1.5, 5);
      expect(computeCommission(50000, IBKR)).toBeCloseTo(7.5, 5);
    });
    it('>193333€ uses flat 29€ (ceiling)', () => {
      expect(computeCommission(193334, IBKR)).toBe(29.0);
      expect(computeCommission(500000, IBKR)).toBe(29.0);
    });
  });

  describe('empty schedule', () => {
    it('returns 0 for empty schedule', () => {
      expect(computeCommission(1000, [])).toBe(0);
    });
  });
});

describe('TTF_RATE', () => {
  it('is 0.4%', () => {
    expect(TTF_RATE).toBe(0.004);
  });
});

describe('isWeekendNewYork', () => {
  it('Saturday is always weekend', () => {
    // Saturday 2026-05-23 12:00 NY
    const sat = new Date('2026-05-23T12:00:00-04:00');
    expect(isWeekendNewYork(sat)).toBe(true);
  });

  it('Friday before 17:00 NY is not weekend', () => {
    const fri_before = new Date('2026-05-22T16:59:00-04:00');
    expect(isWeekendNewYork(fri_before)).toBe(false);
  });

  it('Friday at 17:00 NY is weekend', () => {
    const fri_at = new Date('2026-05-22T17:00:00-04:00');
    expect(isWeekendNewYork(fri_at)).toBe(true);
  });

  it('Sunday before 18:00 NY is weekend', () => {
    const sun_before = new Date('2026-05-24T17:59:00-04:00');
    expect(isWeekendNewYork(sun_before)).toBe(true);
  });

  it('Sunday at 18:00 NY is not weekend', () => {
    const sun_at = new Date('2026-05-24T18:00:00-04:00');
    expect(isWeekendNewYork(sun_at)).toBe(false);
  });

  it('Monday is not weekend', () => {
    const mon = new Date('2026-05-25T10:00:00-04:00');
    expect(isWeekendNewYork(mon)).toBe(false);
  });
});

describe('computeRevolutFXCommission', () => {
  it('weekday, below limit → free', () => {
    expect(computeRevolutFXCommission(300, 500, false)).toBe(0); // 500+300=800 < 1000
  });

  it('weekday, crosses limit → 1% on portion above 1000€', () => {
    expect(computeRevolutFXCommission(300, 800, false)).toBe(1.00); // (800+300-1000)*0.01 = 1
  });

  it('weekday, fully above limit → 1% on overLimit portion', () => {
    // prev=1200, amount=200 → overLimit = (1200+200-1000) = 400 → 400*0.01 = 4
    expect(computeRevolutFXCommission(200, 1200, false)).toBe(4.00);
  });

  it('weekday, already over limit → full 1%', () => {
    // prev=1100, amount=200 → (1100+200-1000)*0.01 = 300*0.01 = 3
    expect(computeRevolutFXCommission(200, 1100, false)).toBe(3.00);
  });

  it('weekend → always 1% regardless of monthly volume', () => {
    expect(computeRevolutFXCommission(500, 0, true)).toBe(5.00);
    expect(computeRevolutFXCommission(500, 200, true)).toBe(5.00);
  });
});

describe('computeMonthlyLimitFXCommission', () => {
  it('null weekendRate falls back to aboveRate on a weekend', () => {
    // No dedicated weekend rate configured → weekend trades use the standard above-limit rate
    expect(computeMonthlyLimitFXCommission(500, 0, true, 1000, 0.02, null))
      .toBe(computeMonthlyLimitFXCommission(500, 0, true, 1000, 0.02, 0.02));
  });
});
