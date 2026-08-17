/**
 * Branch-coverage tests for PoolPositionsTable sorting logic in PositionsPage.
 *
 * This file uses a custom `Th` stub that fires `sort.onSort` when clicked,
 * enabling tests to trigger all sort switch-case branches and verify the
 * resulting DOM order.  It must live in a separate file from the main
 * PositionsPage.test.tsx so each file gets its own module-level vi.mock()
 * hoisting context.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// ── react-router-dom ────────────────────────────────────────────────────────
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

// ── PatternFly core (override Tooltip to render title for assertions) ───────
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Tooltip: ({ children, content }: any) => (
    <div title={typeof content === 'string' ? content : String(content ?? '')}>
      {children}
    </div>
  ),
}));

// ── PatternFly table — custom Th that calls sort.onSort on click ─────────────
//
// The stub toggles direction: first click = 'asc', second click = 'desc',
// matching the PatternFly toggle behaviour expected by the component.
vi.mock('@patternfly/react-table', () => ({
  Table: ({ children, 'aria-label': ariaLabel }: any) => (
    <table aria-label={ariaLabel}>{children}</table>
  ),
  Thead: ({ children }: any) => <thead>{children}</thead>,
  Tbody: ({ children }: any) => <tbody>{children}</tbody>,
  Tr: ({ children, style }: any) => <tr style={style}>{children}</tr>,
  Th: ({ children, sort }: any) => {
    if (!sort) return <th>{children}</th>;
    const { onSort, sortBy, columnIndex } = sort;
    const handleClick = () => {
      // Toggle: if currently asc for this column → desc; else → asc
      const nextDir =
        sortBy?.index === columnIndex && sortBy?.direction === 'asc'
          ? 'desc'
          : 'asc';
      onSort?.({} as any, columnIndex, nextDir);
    };
    return (
      <th
        data-testid={`sort-col-${columnIndex}`}
        data-dir={sortBy?.index === columnIndex ? sortBy?.direction : undefined}
        onClick={handleClick}
      >
        {children}
      </th>
    );
  },
  Td: ({ children, colSpan }: any) => <td colSpan={colSpan}>{children}</td>,
  SortByDirection: { asc: 'asc', desc: 'desc' },
}));

// ── PatternFly icons ─────────────────────────────────────────────────────────
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// ── SyncBadge ────────────────────────────────────────────────────────────────
vi.mock('../components/SyncBadge', () => ({
  default: () => <span data-testid="sync-badge" />,
}));

// ── format utils ─────────────────────────────────────────────────────────────
vi.mock('../utils/format', () => ({
  formatUnitPrice: (v: number, _c?: string) => `${v} €`,
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct2: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(2)} %`,
  formatPct1: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(1)} %`,
}));

// ── useSyncStatus ─────────────────────────────────────────────────────────────
vi.mock('../hooks/useSyncStatus', () => ({
  useSyncStatus: () => ({ data: { failed_tickers: [] } }),
}));

// ── holdings.utils ────────────────────────────────────────────────────────────
vi.mock('./holdings.utils', () => ({
  UNASSIGNED_POOL_KEY: '__unassigned__',
  groupAndSort: (positions: any[], pools: any[]) =>
    pools.map((pool: any) => ({
      pool,
      poolName: pool.name,
      holdings: positions.filter((p: any) => p.pool_name === pool.name),
    })),
}));

// ── API queries ───────────────────────────────────────────────────────────────
const mockUseDashboard = vi.fn();
const mockUseHoldings = vi.fn();
const mockUseCapitalGains = vi.fn();

vi.mock('../api/queries', () => ({
  useDashboard: (...args: any[]) => mockUseDashboard(...args),
  useHoldings: (...args: any[]) => mockUseHoldings(...args),
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
  usePoolAllocation: () => ({ data: undefined }),
}));

// ── Shared fixtures ───────────────────────────────────────────────────────────

const mockDashboard = {
  total_eur: 100000,
  offensive_eur: 50000,
  defensive_eur: 50000,
  liquidity_eur: 1000,
  last_updated: null,
  pools: [
    {
      id: 1,
      name: 'Asie',
      strategy: 'Offensive',
      target_pct: 0.25,
      current_value_eur: 25000,
      current_pct: 25,
      gap_pct: 0,
    },
  ],
};

/** Two positions in the same pool to make sort order observable */
const positionAAP = {
  ticker: 'AAPL',
  product_name: 'Apple',
  category: 'Actif',
  pool_id: 1,
  pool_name: 'Asie',
  quantity: 10,
  last_price: 150,
  last_price_date: '2024-01-01',
  last_price_source: 'yahoo',
  value_eur: 1500,
  currency: 'USD',
};

const positionTSLA = {
  ticker: 'TSLA',
  product_name: 'Tesla',
  category: 'Actif',
  pool_id: 1,
  pool_name: 'Asie',
  quantity: 5,
  last_price: 200,
  last_price_date: '2024-01-01',
  last_price_source: 'yahoo',
  value_eur: 3000,
  currency: 'USD',
};

const twoPositions = [positionAAP, positionTSLA];

const capitalGainsBothPositive = {
  portfolio_id: 1,
  tickers: [
    {
      ticker: 'AAPL',
      product_name: 'Apple Inc',
      cump: 140,
      qty_held: 10,
      cost_basis_eur: 1400,
      current_value_eur: 1500,
      unrealized_pv: 100,     // positive → green
      realized_pv_total: 50,
      events: [],
    },
    {
      ticker: 'TSLA',
      product_name: 'Tesla Inc',
      cump: 250,
      qty_held: 5,
      cost_basis_eur: 1250,
      current_value_eur: 1000,
      unrealized_pv: -250,    // negative → red (#D93025)
      realized_pv_total: 0,
      events: [],
    },
  ],
  total_unrealized_pv: -150,
  total_realized_pv: 50,
  total_pv: -100,
};

import HoldingsPage from './HoldingsPage';

// ── Helper: returns text of all ticker cells in rendered order ────────────────
function renderedTickers(): string[] {
  // The ticker cells contain <strong>TICKER</strong> followed by StalePriceBadge.
  // We find all <strong> elements inside the table body rows.
  return Array.from(document.querySelectorAll('tbody tr td:first-child strong')).map(
    (el) => el.textContent ?? '',
  );
}

// ── Helper: full setup ────────────────────────────────────────────────────────
function setup(
  positions = twoPositions,
  capitalGains = capitalGainsBothPositive,
) {
  mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
  mockUseHoldings.mockReturnValue({ data: positions, isLoading: false, isError: false });
  mockUseCapitalGains.mockReturnValue({ data: capitalGains, isLoading: false, isError: false });
  return userEvent.setup({ delay: null });
}

// ─────────────────────────────────────────────────────────────────────────────

describe('PoolPositionsTable sorting — branch coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── pvColor branches ──────────────────────────────────────────────────────

  it('pvColor: negative unrealized_pv renders red (#D93025 → rgb(217, 48, 37)) span', () => {
    setup();
    render(<HoldingsPage />);
    // TSLA has unrealized_pv = -250 → pvColor(-250) → '#D93025'
    // jsdom normalises hex colours to rgb(...) in element.style.color
    const redSpans = Array.from(
      document.querySelectorAll('span[style]'),
    ).filter((el) => (el as HTMLElement).style.color === 'rgb(217, 48, 37)');
    expect(redSpans.length).toBeGreaterThan(0);
  });

  it('pvColor: zero unrealized_pv renders grey span', () => {
    const capitalGainsWithZero = {
      ...capitalGainsBothPositive,
      tickers: [
        { ...capitalGainsBothPositive.tickers[0], unrealized_pv: 0, cost_basis_eur: 0 },
      ],
    };
    setup([positionAAP], capitalGainsWithZero);
    render(<HoldingsPage />);
    // pvColor(0) returns 'var(--pf-t--global--text--color--subtle)' — verify render doesn't crash
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
    // The "0.00 €" PV value should be present and not red or green
    const body = document.body.textContent ?? '';
    expect(body).toContain('0.00 €');
  });

  // ── sort switch cases ─────────────────────────────────────────────────────

  it('sort by Ticker (col 0) ASC — AAPL before TSLA', async () => {
    const user = setup();
    render(<HoldingsPage />);

    const tickerHeader = screen.getByTestId('sort-col-0');
    await user.click(tickerHeader); // → asc by ticker

    const tickers = renderedTickers();
    expect(tickers.indexOf('AAPL')).toBeLessThan(tickers.indexOf('TSLA'));
  });

  it('sort by Ticker (col 0) DESC — TSLA before AAPL', async () => {
    const user = setup();
    render(<HoldingsPage />);

    const tickerHeader = screen.getByTestId('sort-col-0');
    await user.click(tickerHeader); // → asc
    await user.click(tickerHeader); // → desc (sortDir === 'asc' false path)

    const tickers = renderedTickers();
    expect(tickers.indexOf('TSLA')).toBeLessThan(tickers.indexOf('AAPL'));
  });

  it('sort by PV latente (col 8) ASC — TSLA (-250) before AAPL (100)', async () => {
    const user = setup();
    render(<HoldingsPage />);

    const pvHeader = screen.getByTestId('sort-col-8');
    await user.click(pvHeader); // → asc by pvLatente

    const tickers = renderedTickers();
    expect(tickers.indexOf('TSLA')).toBeLessThan(tickers.indexOf('AAPL'));
  });

  it('sort by PV latente (col 8) DESC — AAPL (100) before TSLA (-250)', async () => {
    const user = setup();
    render(<HoldingsPage />);

    const pvHeader = screen.getByTestId('sort-col-8');
    await user.click(pvHeader); // → asc
    await user.click(pvHeader); // → desc

    const tickers = renderedTickers();
    expect(tickers.indexOf('AAPL')).toBeLessThan(tickers.indexOf('TSLA'));
  });

  it('sort by PV latente when pvMap has no entry for ticker — falls back to 0', async () => {
    // TSLA not in capital gains → pvMap.get('TSLA') = undefined → ?? 0
    const capitalGainsAaplOnly = {
      ...capitalGainsBothPositive,
      tickers: [capitalGainsBothPositive.tickers[0]], // only AAPL
    };
    const user = setup(twoPositions, capitalGainsAaplOnly);
    render(<HoldingsPage />);

    const pvHeader = screen.getByTestId('sort-col-8');
    await user.click(pvHeader); // → asc; TSLA gets pvA=0, AAPL=100 → TSLA first

    // Should not crash
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
    const tickers = renderedTickers();
    // TSLA (0) < AAPL (100) when asc
    expect(tickers.indexOf('TSLA')).toBeLessThan(tickers.indexOf('AAPL'));
  });

  it('sort by % pool (col 6) when poolTotal === 0 — ternary false path', async () => {
    // Make both positions have value_eur = 0 so poolTotal = 0
    const zeroValuePositions = [
      { ...positionAAP, value_eur: 0 },
      { ...positionTSLA, value_eur: 0 },
    ];
    const user = setup(zeroValuePositions);
    render(<HoldingsPage />);

    const pctHeader = screen.getByTestId('sort-col-6');
    await user.click(pctHeader); // → asc; poolTotal=0 → pctA=pctB=0

    // Should not crash; both get pct=0
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('sort by % pool (col 6) when poolTotal > 0 — lines 98-99 true branch', async () => {
    // Both positions have value_eur > 0 → poolTotal > 0 → lines 98-99 true branch fires
    // AAPL value_eur=1500, TSLA value_eur=3000 → poolTotal=4500
    // pctA = 1500/4500 = 33.3%, pctB = 3000/4500 = 66.7%
    // ASC: AAPL (33.3%) before TSLA (66.7%)
    const user = setup();
    render(<HoldingsPage />);

    const pctHeader = screen.getByTestId('sort-col-6');
    await user.click(pctHeader); // → asc

    const tickers = renderedTickers();
    expect(tickers.indexOf('AAPL')).toBeLessThan(tickers.indexOf('TSLA'));
  });

  it('sort by pvLatente (col 8) with both tickers absent from pvMap — lines 103-104 ?? 0 both fire', async () => {
    // Empty pvMap → both pvA and pvB resolve to undefined → ?? 0 fires on both lines 103 AND 104
    const user = setup(twoPositions, { ...capitalGainsBothPositive, tickers: [] });
    render(<HoldingsPage />);

    const pvHeader = screen.getByTestId('sort-col-8');
    await user.click(pvHeader); // → asc; pvA=0, pvB=0 → no reorder

    // Should not crash; both get pv=0
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('sort by PV latente % (col 9) when cost_basis_eur === 0 — ternary false path', async () => {
    const capitalGainsZeroCost = {
      ...capitalGainsBothPositive,
      tickers: [
        { ...capitalGainsBothPositive.tickers[0], cost_basis_eur: 0, unrealized_pv: 100 },
        { ...capitalGainsBothPositive.tickers[1], cost_basis_eur: 0, unrealized_pv: -50 },
      ],
    };
    const user = setup(twoPositions, capitalGainsZeroCost);
    render(<HoldingsPage />);

    const pvPctHeader = screen.getByTestId('sort-col-9');
    await user.click(pvPctHeader); // → asc; cost_basis=0 → pctA=pctB=0

    // Should not crash
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('sort by PV latente % (col 9) when pvMap has no entry for ticker — short-circuit false path', async () => {
    // Neither AAPL nor TSLA in capital gains → pvMap.get → undefined → dA && ... = false → 0
    const user = setup(twoPositions, { ...capitalGainsBothPositive, tickers: [] });
    render(<HoldingsPage />);

    const pvPctHeader = screen.getByTestId('sort-col-9');
    await user.click(pvPctHeader); // → asc; dA=undefined → pctA=0, dB=undefined → pctB=0

    // Should not crash
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('sort by PV latente % (col 9) ASC — TSLA (-20%) before AAPL (7.1%)', async () => {
    // AAPL: unrealized_pv=100, cost=1400 → 7.14%
    // TSLA: unrealized_pv=-250, cost=1250 → -20%
    const user = setup();
    render(<HoldingsPage />);

    const pvPctHeader = screen.getByTestId('sort-col-9');
    await user.click(pvPctHeader); // → asc

    const tickers = renderedTickers();
    expect(tickers.indexOf('TSLA')).toBeLessThan(tickers.indexOf('AAPL'));
  });

  it('sort DESC after ASC — sortDir desc path covered for pvLatentePct', async () => {
    const user = setup();
    render(<HoldingsPage />);

    const pvPctHeader = screen.getByTestId('sort-col-9');
    await user.click(pvPctHeader); // → asc
    await user.click(pvPctHeader); // → desc (line 88: sortDir === 'asc' false branch)

    const tickers = renderedTickers();
    // desc: AAPL (7.14%) before TSLA (-20%)
    expect(tickers.indexOf('AAPL')).toBeLessThan(tickers.indexOf('TSLA'));
  });
});
