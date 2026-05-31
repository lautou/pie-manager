/**
 * Covers the default: return 0 cases in SyntheseComptesPage sort switches:
 * - Line 109: default in summary sort switch (summSortIndex outside 0-4)
 * - Line 245: default in acc position sort switch (accSortIndex outside 0,1,5)
 *
 * Strategy: use a Th mock that fires onSort with an invalid column index (99),
 * causing the switch in the sort comparator to fall through to the default case.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

vi.mock('@patternfly/react-core', () => pfCoreStubs);

// Special Th mock: on click, fires onSort with index 99 (invalid) to hit the default case
vi.mock('@patternfly/react-table', () => ({
  Table: ({ children, 'aria-label': ariaLabel }: any) => (
    <table aria-label={ariaLabel}>{children}</table>
  ),
  Thead: ({ children }: any) => <thead>{children}</thead>,
  Tbody: ({ children }: any) => <tbody>{children}</tbody>,
  Tr: ({ children, style }: any) => <tr style={style}>{children}</tr>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => (
    <th
      data-col-index={sort?.columnIndex}
      data-testid={sort ? `sort-col-${sort.columnIndex}` : 'th-nosort'}
      onClick={() => {
        if (sort?.onSort) {
          // Send an invalid column index (99) to force the default: return 0 branch
          sort.onSort({} as MouseEvent, 99, 'asc');
        }
      }}
    >
      {children}
    </th>
  ),
  Td: ({ children, colSpan }: any) => <td colSpan={colSpan}>{children}</td>,
  SortByDirection: { asc: 'asc', desc: 'desc' },
}));

vi.mock('@patternfly/react-icons', () => pfIconStubs);

vi.mock('../components/SyncBadge', () => ({
  default: () => <span data-testid="sync-badge" />,
}));

vi.mock('../utils/format', () => ({
  formatUnitPrice: (v: number, _c?: string) => `${v} €`,
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct2: (val: number, withSign?: boolean) => `${withSign && val > 0 ? '+' : ''}${val.toFixed(2)} %`,
}));

const mockUseAccountsSummary = vi.fn();
const mockUseCapitalGains = vi.fn();

vi.mock('../api/queries', () => ({
  useAccountsSummary: (...args: any[]) => mockUseAccountsSummary(...args),
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
}));

// Two accounts with multiple positions so sort comparators actually run comparisons
const account = {
  id: 1,
  name: 'Degiro',
  currency: 'EUR',
  cash_balance_eur: 1000,
  positions_value_eur: 9000,
  total_eur: 10000,
  positions: [
    {
      ticker: 'MSFT',
      product_name: 'Microsoft',
      category: 'Actif',
      quantity: 5,
      last_price: 300,
      last_price_date: '2024-01-01',
      last_price_source: 'yahoo',
      value_eur: 1500,
      currency: 'USD',
    },
    {
      ticker: 'AAPL',
      product_name: 'Apple',
      category: 'Actif',
      quantity: 10,
      last_price: 150,
      last_price_date: '2024-01-01',
      last_price_source: 'yahoo',
      value_eur: 1000,
      currency: 'USD',
    },
  ],
};

const account2 = {
  id: 2,
  name: 'Boursorama',
  currency: 'EUR',
  cash_balance_eur: 2000,
  positions_value_eur: 5000,
  total_eur: 7000,
  positions: [
    {
      ticker: 'TSLA',
      product_name: 'Tesla',
      category: 'Actif',
      quantity: 3,
      last_price: 200,
      last_price_date: '2024-01-01',
      last_price_source: 'yahoo',
      value_eur: 600,
      currency: 'USD',
    },
  ],
};

import AccountsSummaryPage from './AccountsSummaryPage';

describe('AccountsSummaryPage — default sort branch coverage (lines 109, 245)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    mockUseAccountsSummary.mockReturnValue({
      data: [account, account2],
      isLoading: false,
      isError: false,
    });
  });

  it('line 109: summary sort default — clicking any summary Th fires onSort with invalid index 99', async () => {
    // The Th mock sends index=99 to onSummSort.
    // The summary sort switch has cases 0-4; index 99 hits default: return 0.
    // Since we have 2 accounts, the sort comparator actually runs (a !== b).
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Find a summary table Th with sort handler
    const ths = Array.from(container.querySelectorAll('th[data-col-index]'));
    expect(ths.length).toBeGreaterThan(0);

    // Click the first sortable Th — the mock sends index=99 to onSummSort
    // SummSortIndex becomes 99 (cast to SummColIndex via `as`).
    // The sort comparator in sortedSummaries runs with switch(99) → default: return 0
    await user.click(ths[0]);

    // Page renders correctly with default sort (stable, return 0 = equal)
    expect(screen.getByText('Comptes')).toBeTruthy();
  });

  it('line 245: acc position sort default — clicking any acc Th fires onSort with invalid index 99', async () => {
    // The Th mock sends index=99 to onAccSort.
    // The acc sort switch has cases 0, 1, 5; index 99 hits default: return 0.
    // Since we have 2 positions in account, the sort comparator actually runs.
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Summary table Ths come first (col indices 0-4), then acc table Ths (col indices 0, 1, 5)
    const ths = Array.from(container.querySelectorAll('th[data-col-index]'));

    // Click ALL Ths — each triggers onSort with index=99
    // The first clicks trigger onSummSort (sets summSortIndex=99 → summary default: return 0)
    // The later clicks trigger onAccSort (sets accSortIndex=99 → acc default: return 0)
    for (const th of ths) {
      await user.click(th);
    }

    expect(screen.getByText('Comptes')).toBeTruthy();
  });
});
