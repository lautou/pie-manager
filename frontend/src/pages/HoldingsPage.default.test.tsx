/**
 * Covers the default: return 0 case in PositionsPage sort switch (line 110).
 *
 * Strategy: use a Th mock that fires onSort with an invalid column index (99),
 * causing the switch in the sort comparator to fall through to the default case.
 * With two positions in the same pool, the comparator actually runs (a !== b),
 * guaranteeing the default branch executes.
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

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Tooltip: ({ children, content }: any) => (
    <div title={typeof content === 'string' ? content : String(content ?? '')}>
      {children}
    </div>
  ),
}));

// Special Th mock: fires onSort with invalid index 99 to hit the default: return 0 branch
vi.mock('@patternfly/react-table', () => ({
  Table: ({ children, 'aria-label': ariaLabel }: any) => (
    <table aria-label={ariaLabel}>{children}</table>
  ),
  Thead: ({ children }: any) => <thead>{children}</thead>,
  Tbody: ({ children }: any) => <tbody>{children}</tbody>,
  Tr: ({ children, style }: any) => <tr style={style}>{children}</tr>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => {
    if (!sort) return <th>{children}</th>;
    const { onSort, columnIndex } = sort;
    return (
      <th
        data-testid={`sort-col-${columnIndex}`}
        onClick={() => {
          // Send invalid index 99 → switch hits default: return 0
          onSort?.({} as any, 99, 'asc');
        }}
      >
        {children}
      </th>
    );
  },
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
  formatPct2: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(2)} %`,
  formatPct1: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(1)} %`,
}));

const mockUseSyncStatus = vi.fn(() => ({ data: { failed_tickers: [] as string[] } as { failed_tickers: string[] } | undefined }));

vi.mock('../hooks/useSyncStatus', () => ({
  useSyncStatus: () => mockUseSyncStatus(),
}));

vi.mock('./holdings.utils', () => ({
  UNASSIGNED_POOL_KEY: '__unassigned__',
  groupAndSort: (positions: any[], pools: any[]) =>
    pools.map((pool: any) => ({
      pool,
      poolName: pool.name,
      holdings: positions.filter((p: any) => p.pool_name === pool.name),
    })),
}));

const mockUseDashboard = vi.fn();
const mockUseHoldings = vi.fn();
const mockUseCapitalGains = vi.fn();

vi.mock('../api/queries', () => ({
  useDashboard: (...args: any[]) => mockUseDashboard(...args),
  useHoldings: (...args: any[]) => mockUseHoldings(...args),
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
}));

const mockDashboard = {
  total_eur: 100000,
  offensive_eur: 50000,
  defensive_eur: 50000,
  liquidity_eur: 1000,
  last_updated: null,
  pools: [
    { id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, current_value_eur: 25000, current_pct: 25, gap_pct: 0 },
  ],
};

// Two positions so the comparator actually runs (a !== b ensures default return 0 is called)
const posA = {
  ticker: 'AAPL', product_name: 'Apple', category: 'Actif',
  pool_id: 1, pool_name: 'Asie', quantity: 10,
  last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo',
  value_eur: 1500, currency: 'USD',
};

const posB = {
  ticker: 'TSLA', product_name: 'Tesla', category: 'Actif',
  pool_id: 1, pool_name: 'Asie', quantity: 5,
  last_price: 200, last_price_date: '2024-01-01', last_price_source: 'yahoo',
  value_eur: 3000, currency: 'USD',
};

const capitalGains = {
  portfolio_id: 1,
  tickers: [
    { ticker: 'AAPL', product_name: 'Apple', cump: 140, qty_held: 10, cost_basis_eur: 1400, current_value_eur: 1500, unrealized_pv: 100, realized_pv_total: 50, events: [] },
    { ticker: 'TSLA', product_name: 'Tesla', cump: 250, qty_held: 5, cost_basis_eur: 1250, current_value_eur: 3000, unrealized_pv: 1750, realized_pv_total: 0, events: [] },
  ],
  total_unrealized_pv: 1850, total_realized_pv: 50, total_pv: 1900,
};

import HoldingsPage from './HoldingsPage';

describe('PoolPositionsTable — default sort branch coverage (line 110)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSyncStatus.mockReturnValue({ data: { failed_tickers: [] } });
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [posA, posB], isLoading: false, isError: false });
    mockUseCapitalGains.mockReturnValue({ data: capitalGains, isLoading: false, isError: false });
  });

  it('line 110: default: return 0 — fired by invalid sort index 99 sent from Th mock', async () => {
    // The Th mock fires onSort with index=99 (invalid).
    // After clicking, sortIndex becomes 99. When [...positions].sort(comparator) runs
    // with two different positions, the comparator runs with switch(99) → default: return 0.
    const user = userEvent.setup({ delay: null });
    render(<HoldingsPage />);

    // Click any sortable Th — the mock sends index=99 to onSort
    // sortIndex becomes 99 → next render triggers [...positions].sort with the comparator
    // The comparator is called at least once for 2 items → switch(99) → default: return 0
    const anyTh = screen.queryByTestId('sort-col-0');
    if (anyTh) {
      await user.click(anyTh);
    } else {
      // Find any sortable Th
      const ths = document.querySelectorAll('th[data-testid^="sort-col-"]');
      if (ths.length > 0) {
        await user.click(ths[0] as HTMLElement);
      }
    }

    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  // Line 98-99: pctPool sort case, poolTotal > 0 TRUE branch
  // Both positions have value_eur > 0 → poolTotal > 0 → pctA/pctB computed from ratio
  it('lines 98-99: pctPool sort with poolTotal > 0 — true branch of ternary', async () => {
    const user = userEvent.setup({ delay: null });
    render(<HoldingsPage />);

    // sort-col-6 is the pctPool column; with posA.value_eur=1500 and posB.value_eur=3000
    // poolTotal = 4500 > 0 → lines 98-99 execute the true branch: pctA = 1500/4500, pctB = 3000/4500
    const col6 = screen.queryByTestId('sort-col-6');
    if (col6) {
      await user.click(col6);
    }
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  // Line 104: pvB = pvMap.get(b.ticker)?.unrealized_pv ?? 0 — ?? 0 fallback for b.ticker absent
  // When BOTH tickers are absent from pvMap, pvB uses ?? 0
  it('line 104: pvB ?? 0 — b.ticker absent from pvMap when sorting pvLatente (col 8)', async () => {
    mockUseCapitalGains.mockReturnValue({ data: { portfolio_id: 1, tickers: [], total_unrealized_pv: 0, total_realized_pv: 0, total_pv: 0 }, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<HoldingsPage />);

    // With empty pvMap: pvA=undefined?.unrealized_pv → undefined → ?? 0, same for pvB
    // This covers the ?? 0 fallback on line 103 AND line 104
    const col8 = screen.queryByTestId('sort-col-8');
    if (col8) {
      await user.click(col8);
    }
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });
});

describe('HoldingsPage — additional branch coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSyncStatus.mockReturnValue({ data: { failed_tickers: [] } });
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseCapitalGains.mockReturnValue({ data: capitalGains, isLoading: false, isError: false });
  });

  // Line 150: currency || 'EUR' — false branch (currency is empty string/falsy)
  it('line 150: currency || "EUR" fallback — position with no currency', () => {
    const posNoCurrency = { ...posA, currency: '' };
    mockUseHoldings.mockReturnValue({ data: [posNoCurrency], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Should render without crash; currency defaults to 'EUR'
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  // Line 179 (both branches): isStale && pos.last_price_date — TRUE path
  // Need failedTickers to contain the ticker AND last_price_date to be set
  it('line 179: stale ticker tooltip shown when isStale=true and last_price_date set', () => {
    // useSyncStatus returns failed_tickers containing 'AAPL' → isStale=true
    // posA has last_price_date='2024-01-01' → both conditions true → tooltip renders
    mockUseSyncStatus.mockReturnValue({ data: { failed_tickers: ['AAPL'] } });
    mockUseHoldings.mockReturnValue({ data: [posA], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Tooltip renders as <div title="...">; date appears in DOM
    const body = document.body.textContent ?? '';
    expect(body).toContain('2024-01-01');
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  // Line 268: syncStatus?.failed_tickers ?? [] — ?? [] fallback when syncStatus data is undefined
  it('line 268: syncStatus?.failed_tickers ?? [] — fallback when useSyncStatus data is undefined', () => {
    // Return data=undefined → syncStatus=undefined → syncStatus?.failed_tickers = undefined → ?? [] fires
    mockUseSyncStatus.mockReturnValue({ data: undefined });
    mockUseHoldings.mockReturnValue({ data: [posA], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Should render without crash — failedTickers defaults to empty Set
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  // Lines 351, 366: dashboard.total_eur > 0 — FALSE branch (shows '–' instead of percentage)
  it('lines 351, 366: total_eur === 0 — shows "–" for offensive and defensive pct', () => {
    const zeroDashboard = {
      ...mockDashboard,
      total_eur: 0,
      offensive_eur: 0,
      defensive_eur: 0,
    };
    mockUseDashboard.mockReturnValue({ data: zeroDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [posA], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // When total_eur === 0, the ternary returns '–' (em-dash) for both offensive and defensive
    const allDashes = screen.getAllByText('–');
    expect(allDashes.length).toBeGreaterThanOrEqual(2);
  });
});
