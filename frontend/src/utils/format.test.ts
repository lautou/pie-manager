// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Non-regression tests for format.ts utilities.
 *
 * All functions are pure and locale-locked to fr-FR, so output is
 * deterministic regardless of the test environment's regional settings.
 */
import { describe, it, expect, test } from 'vitest'
import {
  formatEUR,
  formatEUR3,
  formatPct1,
  formatPct2,
  formatQty,
  formatNativeCurrency,
  formatInt,
  formatDate,
  formatPrice,
  formatUnitPrice,
} from './format'

// ---------------------------------------------------------------------------
// formatEUR — standard EUR currency formatting (2 decimals)
// ---------------------------------------------------------------------------
describe('formatEUR', () => {
  it('formats a positive amount and includes the € symbol', () => {
    const result = formatEUR(1234.56)
    expect(result).toContain('1')
    expect(result).toContain('€')
  })

  it('formats zero correctly', () => {
    const result = formatEUR(0)
    expect(result).toContain('0')
    expect(result).toContain('€')
  })

  it('formats a large amount with thousands separator', () => {
    const result = formatEUR(37353.27)
    // fr-FR uses non-breaking space as thousands separator
    expect(result).toMatch(/37/)
    expect(result).toMatch(/353/)
  })

  it('formats negative amounts', () => {
    const result = formatEUR(-500)
    expect(result).toContain('500')
    // fr-FR places the minus sign before the digits
    expect(result).toMatch(/-/)
  })
})

// ---------------------------------------------------------------------------
// formatEUR3 — 3 decimals normally, 6 for very small values
// ---------------------------------------------------------------------------
describe('formatEUR3', () => {
  it('formats normal values with 3 decimal places', () => {
    const result = formatEUR3(48.824)
    expect(result).toContain('48')
    // Should show 3 decimals: 48,824
    expect(result).toMatch(/824/)
  })

  it('switches to 6 decimals for values below 0.01 (e.g. JPY rate)', () => {
    const result = formatEUR3(0.005796)
    // fr-FR decimal separator is comma
    expect(result).toMatch(/0,005/)
    expect(result).toContain('€')
  })

  it('does NOT switch to 6 decimals for exactly 0.01', () => {
    const result = formatEUR3(0.01)
    // 0.01 is not < 0.01, so uses 3-decimal formatter
    expect(result).toMatch(/0,010/)
  })

  it('uses 3 decimals for values >= 0.01', () => {
    const result = formatEUR3(1.5)
    expect(result).toMatch(/1,500/)
  })
})

// ---------------------------------------------------------------------------
// formatPct1 — percentage with 1 decimal place
// ---------------------------------------------------------------------------
describe('formatPct1', () => {
  it('formats a percentage with 1 decimal place', () => {
    expect(formatPct1(24.8)).toBe('24,8 %')
  })

  it('does not add + sign by default', () => {
    expect(formatPct1(2.4)).toBe('2,4 %')
  })

  it('adds + sign for positive values when withSign=true', () => {
    expect(formatPct1(2.4, true)).toBe('+2,4 %')
  })

  it('does not add + sign for negative values even when withSign=true', () => {
    const result = formatPct1(-7.3, true)
    expect(result).not.toContain('+')
    expect(result).toContain('7,3')
    expect(result).toContain('%')
  })

  it('does not add + sign for zero even when withSign=true', () => {
    expect(formatPct1(0, true)).toBe('0,0 %')
  })

  it('rounds to 1 decimal place', () => {
    expect(formatPct1(16.9502)).toBe('17,0 %')
  })
})

// ---------------------------------------------------------------------------
// formatPct2 — percentage with 2 decimal places
// ---------------------------------------------------------------------------
describe('formatPct2', () => {
  it('formats with 2 decimal places', () => {
    expect(formatPct2(8.44)).toBe('8,44 %')
  })

  it('adds + sign for positive values when withSign=true', () => {
    expect(formatPct2(3.14, true)).toBe('+3,14 %')
  })

  it('does not add + sign for zero', () => {
    expect(formatPct2(0, true)).toBe('0,00 %')
  })
})

// ---------------------------------------------------------------------------
// formatQty — signed quantity (uses Unicode minus sign for negatives)
// ---------------------------------------------------------------------------
describe('formatQty', () => {
  it('prefixes positive quantities with +', () => {
    const result = formatQty(17)
    expect(result).toContain('+')
    expect(result).toContain('17')
  })

  it('uses the Unicode minus sign (−) for negative quantities', () => {
    const result = formatQty(-3)
    // Unicode minus '−' (U+2212), not ASCII '-'
    expect(result).toContain('−')
    expect(result).toContain('3')
  })

  it('prefixes zero with +', () => {
    const result = formatQty(0)
    expect(result).toContain('+')
  })

  it('respects maxDecimals parameter', () => {
    const result = formatQty(1.123456789, 2)
    // Should show at most 2 decimals
    expect(result).not.toMatch(/\d{3,}/)  // no more than 2 decimal digits
  })
})

// ---------------------------------------------------------------------------
// formatNativeCurrency — amount with currency code appended
// ---------------------------------------------------------------------------
describe('formatNativeCurrency', () => {
  it('appends the currency code', () => {
    const result = formatNativeCurrency(387420.93, 'JPY')
    expect(result).toContain('JPY')
    expect(result).toContain('387')
  })

  it('respects maxDecimals', () => {
    const result = formatNativeCurrency(1.1234567, 'USD', 2)
    // Should not have more than 2 decimal digits
    const numPart = result.replace(' USD', '').trim()
    const decimals = numPart.split(',')[1] ?? ''
    expect(decimals.length).toBeLessThanOrEqual(2)
  })

  it('uses minDecimals when specified', () => {
    // minDecimals=0 means no forced trailing zeros
    const result = formatNativeCurrency(100, 'GBP', 3, 0)
    expect(result).toContain('GBP')
  })
})

// ---------------------------------------------------------------------------
// formatInt — integer with thousands separator, no decimals
// ---------------------------------------------------------------------------
describe('formatInt', () => {
  it('formats large integers without decimals', () => {
    const result = formatInt(5716538)
    expect(result).toMatch(/5/)
    expect(result).toMatch(/716/)
    expect(result).not.toContain(',')  // no decimal comma
  })

  it('formats zero', () => {
    expect(formatInt(0)).toBe('0')
  })
})

// ---------------------------------------------------------------------------
// formatDate — YYYY-MM-DD → DD/MM/YYYY
// ---------------------------------------------------------------------------
describe('formatDate', () => {
  it('converts ISO date to French format', () => {
    expect(formatDate('2025-03-15')).toBe('15/03/2025')
  })

  it('handles another date correctly', () => {
    expect(formatDate('2024-12-01')).toBe('01/12/2024')
  })

  it('returns the input unchanged for short/invalid strings', () => {
    expect(formatDate('')).toBe('')
    expect(formatDate('bad')).toBe('bad')
  })
})

// ---------------------------------------------------------------------------
// formatPrice — delegates to formatEUR for EUR, otherwise appends code
// ---------------------------------------------------------------------------
describe('formatPrice', () => {
  it('formats EUR prices like formatEUR', () => {
    const result = formatPrice(42.5, 'EUR')
    expect(result).toContain('€')
  })

  it('formats non-EUR prices with currency code', () => {
    const result = formatPrice(150, 'USD')
    expect(result).toContain('USD')
    expect(result).toContain('150')
  })
})

// ---------------------------------------------------------------------------
// formatUnitPrice — drops trailing zeros, EUR or currency code (lines 79-84)
// ---------------------------------------------------------------------------
describe('formatUnitPrice', () => {
  it('formats EUR values with € symbol and no trailing zeros', () => {
    const result = formatUnitPrice(181.96, 'EUR')
    expect(result).toContain('€')
    expect(result).toContain('181')
  })

  it('formats non-EUR values with currency code instead of €', () => {
    const result = formatUnitPrice(150.5, 'USD')
    // Non-EUR path: appends currency code, not €
    expect(result).toContain('USD')
    expect(result).toContain('150')
    expect(result).not.toContain('€')
  })

  it('drops trailing zeros (e.g. 181.9600 → "181,96 €")', () => {
    const result = formatUnitPrice(181.9600, 'EUR')
    // should not have more than 2 meaningful decimals for this value
    expect(result).toContain('181')
  })

  it('keeps up to 4 decimals for values needing them', () => {
    const result = formatUnitPrice(4.5608, 'EUR')
    expect(result).toContain('4')
    expect(result).toContain('5608')
  })
})

// ---------------------------------------------------------------------------
// Solo+accumulate legend filter logic (matches PerformancePage.tsx soloToggle)
// ---------------------------------------------------------------------------

function soloToggle(
  prev: Set<string> | null,
  name: string,
): Set<string> | null {
  if (prev === null) return new Set([name]);
  if (prev.has(name)) {
    const next = new Set(prev);
    next.delete(name);
    return next.size === 0 ? null : next;
  }
  return new Set([...prev, name]);
}

describe('soloToggle legend filter', () => {
  test('all visible + click X → solo X', () => {
    const result = soloToggle(null, 'Asie');
    expect(result).toEqual(new Set(['Asie']));
  });

  test('solo X + click Y (hidden) → {X, Y}', () => {
    const result = soloToggle(new Set(['Asie']), 'Energie');
    expect(result).toEqual(new Set(['Asie', 'Energie']));
  });

  test('solo X + click X (only one) → reset all (null)', () => {
    const result = soloToggle(new Set(['Asie']), 'Asie');
    expect(result).toBeNull();
  });

  test('{X,Y} + click X → {Y} (keep Y visible)', () => {
    const result = soloToggle(new Set(['Asie', 'Energie']), 'Asie');
    expect(result).toEqual(new Set(['Energie']));
  });

  test('{X,Y,Z} + click Y → {X,Z}', () => {
    const result = soloToggle(new Set(['Asie', 'Energie', 'Or']), 'Energie');
    expect(result).toEqual(new Set(['Asie', 'Or']));
  });

  test('deselect last remaining → null (reset)', () => {
    const result = soloToggle(new Set(['Or']), 'Or');
    expect(result).toBeNull();
  });

  test('null (all visible) + multiple clicks accumulate correctly', () => {
    let state: Set<string> | null = null;
    state = soloToggle(state, 'Asie');    // solo Asie
    state = soloToggle(state, 'Energie'); // add Energie
    state = soloToggle(state, 'Or');      // add Or
    expect(state).toEqual(new Set(['Asie', 'Energie', 'Or']));
  });
});
