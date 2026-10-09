// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { parseNumericInput } from './numericInput';

describe('parseNumericInput', () => {
  it('parses "0" as 0, not as the NaN fallback', () => {
    expect(parseNumericInput('0')).toBe(0);
  });

  it('parses a positive decimal', () => {
    expect(parseNumericInput('12.5')).toBe(12.5);
  });

  it('parses a negative number', () => {
    expect(parseNumericInput('-3')).toBe(-3);
  });

  it('falls back to 0 for an empty string', () => {
    expect(parseNumericInput('')).toBe(0);
  });

  it('falls back to 0 for a non-numeric string', () => {
    expect(parseNumericInput('abc')).toBe(0);
  });
});
