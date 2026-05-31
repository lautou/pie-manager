/**
 * Centralized formatting utilities — always use fr-FR locale
 * regardless of browser/OS regional settings.
 */

const LOCALE = 'fr-FR';

const fmtEUR  = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'EUR' });
const fmtEUR3 = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'EUR', minimumFractionDigits: 3, maximumFractionDigits: 3 });
const fmtPct1 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmtPct2 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt  = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });

/** Format as EUR currency: 37 353,27 € */
export const formatEUR = (val: number): string => fmtEUR.format(val);

/**
 * Format unit prices: 3 decimal places normally, up to 6 for very small values (e.g. JPY rates).
 * 48.824 → "48,824 €"  |  0.00577 → "0,005770 €"
 */
export const formatEUR3 = (val: number): string => {
  if (val !== 0 && Math.abs(val) < 0.01) {
    return new Intl.NumberFormat(LOCALE, {
      style: 'currency', currency: 'EUR',
      minimumFractionDigits: 6, maximumFractionDigits: 6,
    }).format(val);
  }
  return fmtEUR3.format(val);
};

/** Format as percentage with 1 decimal: +27,6 % */
export const formatPct1 = (val: number, withSign = false): string => {
  const s = fmtPct1.format(val) + ' %';
  return withSign && val > 0 ? `+${s}` : s;
};

/** Format as percentage with 2 decimals: +8,44 % */
export const formatPct2 = (val: number, withSign = false): string => {
  const s = fmtPct2.format(val) + ' %';
  return withSign && val > 0 ? `+${s}` : s;
};

/** Format integer: 5 716 538 */
export const formatInt = (val: number): string => fmtInt.format(val);

/** Format quantity with sign: +3 637 or −6 776 953,854 */
export const formatQty = (val: number, maxDecimals = 6): string => {
  const fmt = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: maxDecimals });
  const abs = fmt.format(Math.abs(val));
  return val >= 0 ? `+${abs}` : `−${abs}`;  // use proper minus sign −
};

/** Format a number in native currency (e.g. 387 420,93 JPY).
 *  maxDecimals = upper bound; minDecimals defaults to maxDecimals (pass 0 for significant-only). */
export const formatNativeCurrency = (val: number, currency: string, maxDecimals = 3, minDecimals?: number): string => {
  const fmt = new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: minDecimals ?? maxDecimals,
    maximumFractionDigits: maxDecimals,
  });
  return `${fmt.format(val)} ${currency}`;
};

/** Format a price (unit price, varies in decimals) */
export const formatPrice = (val: number, currency = 'EUR', maxDecimals = 4): string => {
  if (currency === 'EUR') return formatEUR(val);
  const fmt = new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: maxDecimals,
  });
  return `${fmt.format(val)} ${currency}`;
};

/**
 * Format a unit price dropping trailing zeros: up to 4 decimal places.
 * 181.9600 → "181,96 €"  |  4.5608 → "4,5608 €"  |  469.2 → "469,2 €"
 * For non-EUR: appends the currency code instead of symbol.
 */
export const formatUnitPrice = (val: number, currency = 'EUR'): string => {
  const fmt = new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  if (currency === 'EUR') return `${fmt.format(val)} €`;
  return `${fmt.format(val)} ${currency}`;
};

/**
 * Returns today's date as YYYY-MM-DD in LOCAL timezone.
 * Never use new Date().toISOString().slice(0,10) — it returns UTC date
 * which can be the previous day at night in UTC+1/+2.
 */
export const localDateStr = (offset = 0): string => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return dateToLocalStr(d);
};

/** Convert any Date object to YYYY-MM-DD in LOCAL timezone (not UTC). */
export const dateToLocalStr = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Format YYYY-MM-DD date as DD/MM/YYYY for display */
export const formatDate = (iso: string): string => {
  if (!iso || iso.length < 10) return iso;
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
};
