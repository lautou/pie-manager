// SPDX-License-Identifier: AGPL-3.0-or-later
import type { CommissionTier } from "../types";

export const TTF_RATE = 0.004;
export function computeCommission(amount: number, schedule: CommissionTier[]): number {
  for (const tier of schedule) {
    if (tier.up_to === null || amount <= tier.up_to) {
      return tier.type === "flat" ? tier.value : amount * tier.value;
    }
  }
  return 0;
}

/** True if the given date falls in a paid FX window:
 *  Friday 17:00 – Sunday 18:00 New York time. */
export function isWeekendNewYork(date: Date = new Date()): boolean {
  const ny = new Date(date.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = ny.getDay();
  const mins = ny.getHours() * 60 + ny.getMinutes();
  if (day === 6) return true;
  if (day === 5 && mins >= 17 * 60) return true;
  if (day === 0 && mins < 18 * 60) return true;
  return false;
}

/**
 * Generic monthly-limit FX commission.
 * Applies to any broker with a free monthly volume + rate beyond + optional weekend rate.
 *
 * @param amount           EUR value of this transaction
 * @param prevVolume       EUR volume already exchanged this month
 * @param weekend          whether current time is in paid FX window
 * @param monthlyFree      free monthly allowance in EUR (0 = always charged)
 * @param aboveRate        rate applied on volume exceeding monthly free allowance
 * @param weekendRate      rate applied on weekends (null = same as aboveRate)
 */
export function computeMonthlyLimitFXCommission(
  amount: number,
  prevVolume: number,
  weekend: boolean,
  monthlyFree: number,
  aboveRate: number,
  weekendRate: number | null,
): number {
  const effectiveWeekendRate = weekendRate ?? aboveRate;
  if (weekend) return Math.round(amount * effectiveWeekendRate * 100) / 100;
  const overLimit = Math.max(0, prevVolume + amount - monthlyFree);
  return Math.round(overLimit * aboveRate * 100) / 100;
}

// Keep backward-compatible alias for existing tests
/** @deprecated use computeMonthlyLimitFXCommission */
export const computeRevolutFXCommission = (
  amount: number, prevVolume: number, weekend: boolean
) => computeMonthlyLimitFXCommission(amount, prevVolume, weekend, 1000, 0.01, 0.01);
