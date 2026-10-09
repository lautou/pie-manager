// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Parse a raw <input type="number"> string into a number, falling back to 0
 * only when the string doesn't parse at all (empty, a bare "-", etc).
 *
 * `parseFloat(raw) || 0` looks equivalent but isn't: it also replaces a
 * genuinely parsed 0 with 0 via the fallback, which is harmless on its own —
 * the bug is on the display side, where a sibling `value={state || ''}`
 * collapses that 0 back to an empty string, making "0" (and by extension any
 * "0.x" value typed digit-by-digit) impossible to type into the field.
 */
export function parseNumericInput(raw: string): number {
  const parsed = parseFloat(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}
