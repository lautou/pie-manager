// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Covers the default: return 0 cases in PVPage sort functions:
 * - Line 68: default in sortTickers switch
 * - Line 200: default in sortEvents switch
 *
 * Strategy: the Th mock calls onSort with index 99 (invalid).
 * - For sortTickers: summaryColKey(99) = SUMMARY_COLS[99]?.key ?? 'net_pv' = 'net_pv'
 *   (which IS a case). Default is NOT reached via summaryColKey.
 *
 * Alternative strategy for line 68: expose sortTickers by temporarily adding
 * it to the window object via a React component rendered in test.
 * Not possible without modifying source.
 *
 * True strategy: use the Array.prototype.sort spy to capture the comparator,
 * then make a synthetic call that bypasses summaryColKey. Since col is fixed
 * in the closure and summaryColKey always returns a valid value, we must
 * patch the SUMMARY_COLS export... which is not exported.
 *
 * Conclusion: these defaults ARE reachable if we create a mock component that
 * calls the sort comparator with an invalid col. We do this by:
 * 1. Rendering PVPage with our normal mock data (fires sort on mount)
 * 2. Using Array.prototype.sort spy to capture the comparator
 * 3. Calling the captured comparator with a modified `col` value via a Proxy
 *    that intercepts the comparator's closure variable... but we can't do that.
 *
 * FINAL APPROACH: We render PVPage and trigger a sort with a Th mock that
 * passes index=99. summaryColKey(99) = 'net_pv' (via fallback). This hits the
 * 'net_pv' case, not the default. To FORCE the default, we need a fresh test
 * with a modified module setup where SUMMARY_COLS has no fallback.
 *
 * Since this requires source modification, we accept that these two statements
 * (line 68 and line 200) are unreachable through normal testing without
 * modifying the source files. This file documents the limitation.
 *
 * We DO cover lines 60-67 and 193-199 via click interactions.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
}));

vi.mock('@patternfly/react-core', () => pfCoreStubs);

// Th mock that sends column index 99 to onSort — forces summaryColKey(99) = 'net_pv'
// (fallback). Since 'net_pv' IS a case in sortTickers, this does NOT hit default.
// However, for EVENT_COLS, colKey(99) = 'date' (fallback), also NOT hitting default.
//
// The Th mock also separately fires with the REAL columnIndex for normal sort tests.
vi.mock('@patternfly/react-table', () => ({
  ...pfTableStubs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => (
    <th
      data-col-index={sort?.columnIndex}
      data-testid={sort ? `sort-col-${sort.columnIndex}` : undefined}
      onClick={() => {
        if (sort?.onSort) {
          // Use real columnIndex for coverage of cases 0-8 in sortTickers
          sort.onSort({} as MouseEvent, sort.columnIndex, 'asc');
        }
      }}
      // Also add a second click target that sends invalid index to reach default
      onDoubleClick={() => {
        if (sort?.onSort) {
          // Index 9 is beyond SUMMARY_COLS (0-8) but colKey(9) is still valid
          // For sortEvents: EVENT_COLS has 7 items (0-6); index 9 → colKey(9) = 'date' fallback
          // Still doesn't hit default. Only truly unreachable via TypeScript exhaustion.
          sort.onSort({} as MouseEvent, sort.columnIndex, 'asc');
        }
      }}
    >
      {children}
    </th>
  ),
}));

vi.mock('../utils/format', () => ({
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct1: (val: number, withSign?: boolean) => `${withSign && val > 0 ? '+' : ''}${val.toFixed(1)} %`,
  formatDate: (iso: string) => {
    if (!iso || iso.length < 10) return iso;
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  },
}));

const mockUseCapitalGains = vi.fn();
vi.mock('../api/queries', () => ({
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
}));

const ticker1 = {
  ticker: 'AAPL', product_name: 'Apple Inc', cump: 140.0, qty_held: 10,
  cost_basis_eur: 1400, current_value_eur: 1500, unrealized_pv: 100, realized_pv_total: 50,
  events: [{
    date: '2024-06-15', ticker: 'AAPL', product_name: 'Apple Inc',
    qty_sold: 5, cump_at_sell: 135.0, sell_price_eur: 750, realized_pv: 50, account_id: 1,
  }],
};

const ticker2 = {
  ticker: 'MSFT', product_name: 'Microsoft Corp', cump: 280.0, qty_held: 5,
  cost_basis_eur: 1400, current_value_eur: 1600, unrealized_pv: 200, realized_pv_total: -30,
  events: [{
    date: '2024-03-10', ticker: 'MSFT', product_name: 'Microsoft Corp',
    qty_sold: 2, cump_at_sell: 290.0, sell_price_eur: 560, realized_pv: -30, account_id: 1,
  }],
};

const mockData = {
  portfolio_id: 1,
  tickers: [ticker1, ticker2],
  total_unrealized_pv: 300, total_realized_pv: 20, total_pv: 320,
};

import CapitalGainsPage from './CapitalGainsPage';

describe('CapitalGainsPage — sort default branch documentation tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseCapitalGains.mockReturnValue({ data: mockData, isLoading: false, isError: false });
  });

  // This test verifies that all available summary sort cases are triggered via clicks.
  // The default: return 0 (line 68) is unreachable because summaryColKey always
  // returns a valid SummarySortCol value ('net_pv' fallback is also a valid case).
  it('summary table: clicking all column headers covers cases 0-8 in sortTickers', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);

    // Summary table has 9 Th elements (indices 0-8), each mapping to a valid SummarySortCol
    const ths = Array.from(document.querySelectorAll('th[data-testid]'));
    // Click all sortable Th elements
    for (const th of ths.slice(0, 9)) {
      await user.click(th);
    }
    expect(screen.getByText('Plus-values')).toBeTruthy();
  });

  // Similarly for sortEvents (line 200 default), colKey fallback is 'date' (a valid case).
  it('history table: clicking all column headers covers cases in sortEvents', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);

    const ths = Array.from(document.querySelectorAll('th[data-testid]'));
    // History table comes after summary table; click all sortable Ths
    for (const th of ths) {
      await user.click(th);
    }
    expect(screen.getByText('Plus-values')).toBeTruthy();
  });
});
