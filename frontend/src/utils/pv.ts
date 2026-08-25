// SPDX-License-Identifier: AGPL-3.0-or-later
/** Color for a profit/value figure: green if positive, red if negative, neutral otherwise. */
export function pvColor(val: number): string {
  if (val > 0) return '#137333';
  if (val < 0) return '#D93025';
  return 'var(--pf-t--global--text--color--subtle)';
}
