// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for FrDatePicker pure date-conversion helpers.
 *
 * All helpers work on Date objects and strings — no DOM, no PatternFly.
 * Key regression: parsing and formatting at noon (12:00:00) to avoid
 * timezone shifts that would flip the displayed day by ±1.
 */
import { describe, it, expect } from 'vitest'
import { dateFormat, dateParse, isoToDisplay, dateToISO } from './FrDatePicker.utils'

// ---------------------------------------------------------------------------
// dateToISO — Date → "YYYY-MM-DD"
// ---------------------------------------------------------------------------

describe('dateToISO', () => {
  it('formats a date to YYYY-MM-DD', () => {
    // Use noon to avoid any possible local-time edge cases in the test itself
    expect(dateToISO(new Date(2025, 0, 15, 12))).toBe('2025-01-15')  // Jan 15
    expect(dateToISO(new Date(2025, 11, 31, 12))).toBe('2025-12-31') // Dec 31
    expect(dateToISO(new Date(2025, 1, 1, 12))).toBe('2025-02-01')   // Feb 1
  })

  it('pads single-digit month and day with a leading zero', () => {
    expect(dateToISO(new Date(2025, 2, 5, 12))).toBe('2025-03-05')
    expect(dateToISO(new Date(2025, 8, 9, 12))).toBe('2025-09-09')
  })

  it('handles leap day', () => {
    expect(dateToISO(new Date(2024, 1, 29, 12))).toBe('2024-02-29')
  })
})

// ---------------------------------------------------------------------------
// dateParse — "dd/mm/yyyy" → Date (at noon)
// ---------------------------------------------------------------------------

describe('dateParse', () => {
  it('parses dd/mm/yyyy and returns a valid Date', () => {
    const d = dateParse('15/01/2025')
    expect(isNaN(d.getTime())).toBe(false)
    expect(d.getFullYear()).toBe(2025)
    expect(d.getMonth()).toBe(0)  // January = 0
    expect(d.getDate()).toBe(15)
  })

  it('parses at noon to avoid DST/timezone shift', () => {
    const d = dateParse('31/12/2025')
    expect(d.getHours()).toBe(12)
  })

  it('returns invalid date for empty string', () => {
    expect(isNaN(dateParse('').getTime())).toBe(true)
  })

  it('returns invalid date for malformed input', () => {
    expect(isNaN(dateParse('not-a-date').getTime())).toBe(true)
    expect(isNaN(dateParse('01/01').getTime())).toBe(true)       // missing year
    expect(isNaN(dateParse('01/01/25').getTime())).toBe(true)    // 2-digit year
  })

  it('rejects partial/invalid intermediate values — prevents wrong date computation while typing', () => {
    // Regression: "0/05/2026" (day=0 while typing "08") must NOT compute 30/04/2026
    expect(isNaN(dateParse('0/05/2026').getTime())).toBe(true)  // day=0 invalid
    expect(isNaN(dateParse('00/05/2026').getTime())).toBe(true) // day=0 invalid
    expect(isNaN(dateParse('15/0/2026').getTime())).toBe(true)  // month=0 invalid
    expect(isNaN(dateParse('15/13/2026').getTime())).toBe(true) // month>12 invalid
    expect(isNaN(dateParse('32/05/2026').getTime())).toBe(true) // day>31 invalid
    expect(isNaN(dateParse('08/05/1800').getTime())).toBe(true) // year<1900 invalid
  })

  it('round-trips with dateToISO', () => {
    const cases = ['01/01/2025', '15/06/2024', '31/12/2023', '29/02/2024']
    for (const display of cases) {
      const parsed = dateParse(display)
      const [dd, mm, yyyy] = display.split('/')
      expect(dateToISO(parsed)).toBe(`${yyyy}-${mm}-${dd}`)
    }
  })
})

// ---------------------------------------------------------------------------
// isoToDisplay — "YYYY-MM-DD" → "dd/mm/yyyy"
// ---------------------------------------------------------------------------

describe('isoToDisplay', () => {
  it('returns empty string for empty input', () => {
    expect(isoToDisplay('')).toBe('')
  })

  it('returns empty string for input shorter than 10 chars', () => {
    expect(isoToDisplay('2025-01')).toBe('')
    expect(isoToDisplay('short')).toBe('')
  })

  it('returns empty string for invalid ISO', () => {
    expect(isoToDisplay('not-a-real-date')).toBe('')
  })

  it('round-trips with dateParse + dateToISO', () => {
    // We cannot assert the exact display string without hardcoding locale output,
    // but we can verify the round-trip: isoToDisplay → dateParse → dateToISO
    const cases = ['2025-01-15', '2024-06-30', '2023-12-31', '2024-02-29']
    for (const iso of cases) {
      const displayed = isoToDisplay(iso)
      expect(displayed).not.toBe('')
      const reparsed = dateParse(displayed)
      expect(dateToISO(reparsed)).toBe(iso)
    }
  })

  it('parses at noon to avoid timezone shift (2025-01-15 stays 2025-01-15)', () => {
    // This is the key regression: UTC midnight ISO dates would shift to the
    // previous day in UTC+ timezones. Noon parsing prevents this.
    const displayed = isoToDisplay('2025-01-15')
    const reparsed = dateParse(displayed)
    expect(dateToISO(reparsed)).toBe('2025-01-15')
  })
})

// ---------------------------------------------------------------------------
// dateFormat — Date → "dd/mm/yyyy" (fr-FR locale)
// ---------------------------------------------------------------------------

describe('dateFormat', () => {
  it('formats a date using dateParse as source (round-trip consistency)', () => {
    // We test that dateFormat is consistent with dateParse:
    // parsing "15/01/2025" and re-formatting gives back something parseable
    const d = dateParse('15/01/2025')
    const formatted = dateFormat(d)
    const reparsed = dateParse(formatted)
    expect(dateToISO(reparsed)).toBe('2025-01-15')
  })

  it('output contains expected year, month and day components', () => {
    const d = new Date(2025, 5, 20, 12) // June 20, 2025
    const formatted = dateFormat(d)
    expect(formatted).toContain('20')
    expect(formatted).toContain('06')
    expect(formatted).toContain('2025')
  })
})
