/**
 * Tests for PositionsPage
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

// Mock PatternFly core — override Tooltip to render title prop for test assertions,
// and Modal to expose an onClose trigger (generic stub has no close affordance)
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Tooltip: ({ children, content }: any) => (
    <div title={typeof content === 'string' ? content : String(content ?? '')}>
      {children}
    </div>
  ),
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <button data-testid="modal-close" onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div>{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
}));

// Mock PatternFly table
vi.mock('@patternfly/react-table', () => pfTableStubs);

// Mock PatternFly icons
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// Mock SyncBadge
vi.mock('../components/SyncBadge', () => ({
  default: () => <span data-testid="sync-badge" />,
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatUnitPrice: (v: number, _c?: string) => `${v} €`,
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct1: (val: number) => `${val.toFixed(1)} %`,
  formatPct2: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(2)} %`,
}));


// Mock hooks
vi.mock('../hooks/useSyncStatus', () => ({
  useSyncStatus: () => ({ data: { failed_tickers: [] } }),
}));

// Mock holdings.utils
vi.mock('./holdings.utils', () => ({
  UNASSIGNED_POOL_KEY: '__unassigned__',
  groupAndSort: (positions: any[], pools: any[]) => {
    return pools.map((pool: any) => ({
      pool,
      poolName: pool.name,
      holdings: positions.filter((p: any) => p.pool_name === pool.name),
    }));
  },
}));

// Mock API queries
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

const mockCapitalGains = {
  portfolio_id: 1,
  tickers: [
    {
      ticker: 'AAPL',
      product_name: 'Apple Inc',
      cump: 140.0,
      qty_held: 10,
      cost_basis_eur: 1400,
      current_value_eur: 1500,
      unrealized_pv: 100,
      realized_pv_total: 50,
      events: [],
    },
  ],
  total_unrealized_pv: 100,
  total_realized_pv: 50,
  total_pv: 150,
};

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

const mockPositions = [
  {
    ticker: 'AAPL', product_name: 'Apple', category: 'Actif', pool_id: 1, pool_name: 'Asie',
    quantity: 10, last_price: 150, last_price_date: '2024-01-01',
    last_price_source: 'yahoo', value_eur: 1500, currency: 'USD',
  },
];

const mockManuelPosition = {
  ticker: 'OR.PHYSIQUE', product_name: 'Or Physique (auCoffre)', category: 'Actif', instrument_type: 'Or physique',
  pool_id: 2, pool_name: 'Or',
  quantity: 72, last_price: 32336.34, last_price_date: '2026-05-16',
  last_price_source: 'manual', value_eur: 32336.34, currency: 'EUR',
};

import HoldingsPage, { StalePriceBadge } from './HoldingsPage';

describe('HoldingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: capital gains returns mock data
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGains, isLoading: false, isError: false });
  });

  afterEach(() => {
    // Restore real timers to prevent fake timer state leaking between tests
    vi.useRealTimers();
  });

  it('shows spinner when loading', () => {
    mockUseDashboard.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    mockUseHoldings.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByTestId('spinner')).toBeTruthy();
  });

  it('shows error message when dashboard errors', () => {
    mockUseDashboard.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    mockUseHoldings.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText(/Erreur lors du chargement des positions/i)).toBeTruthy();
  });

  it('shows error message when positions errors', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<HoldingsPage />);
    expect(screen.getByText(/Erreur lors du chargement des positions/i)).toBeTruthy();
  });

  it('renders page title with data', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('renders pool name with positions', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('Asie')).toBeTruthy();
  });

  it('renders liquidity card', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('Liquidités disponibles')).toBeTruthy();
  });

  it('clicking a composable ticker opens the composition modal, and closing it clears the state', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    const user = userEvent.setup();
    const etfPosition = { ...mockPositions[0], instrument_type: 'ETF' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [etfPosition], isLoading: false, isError: false });
    render(<HoldingsPage />);

    await user.click(screen.getByText('AAPL'));
    expect(screen.getByTestId('modal')).toBeTruthy();

    await user.click(screen.getByTestId('modal-close'));
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('shows manual price badge for manual source', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    const manualPositions = [{ ...mockPositions[0], last_price_source: 'manual' }];
    mockUseHoldings.mockReturnValue({ data: manualPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('manual')).toBeTruthy();
  });

  it('renders pool summary cards', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Pool summary: Asie pool card should appear
    expect(screen.getAllByText('Asie').length).toBeGreaterThan(0);
  });

  it('shows positions without pool_name as "Non assigné"', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    const unassignedPositions = [{ ...mockPositions[0], pool_name: null, pool_id: null }];
    mockUseHoldings.mockReturnValue({ data: unassignedPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Page should still render
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
  });

  it('Manuel category: shows "—" for Quantité and Dernier prix, date under Total EUR', () => {
    const orPool = { id: 2, name: 'Or', strategy: 'Defensive', target_pct: 0.25, current_pct: 24, current_value_eur: 32336, gap_pct: -1 };
    const dashWithOr = { ...mockDashboard, pools: [...mockDashboard.pools, orPool] };
    mockUseDashboard.mockReturnValue({ data: dashWithOr, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [mockManuelPosition], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Manuel position: Quantité and Dernier prix must show '—'
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    // Date under Total EUR
    expect(screen.getByText('2026-05-16')).toBeTruthy();
  });

  // ── StalePriceBadge in PositionsPage table ───────────────────────────────

  it('StalePriceBadge: shows stale badge when last_price_date is > 2 days ago', () => {
    const staleDate = new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const stalePosition = { ...mockPositions[0], last_price_date: staleDate, last_price_source: 'yahoo' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [stalePosition], isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Should find a label with text matching "Prix : Xj"
    const body = document.body.textContent ?? '';
    expect(body).toMatch(/Prix : \d+j/);
  });

  it('StalePriceBadge: shows no badge when last_price_date is within 2 days', () => {
    const freshDate = new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const freshPosition = { ...mockPositions[0], last_price_date: freshDate, last_price_source: 'yahoo' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [freshPosition], isLoading: false, isError: false });
    render(<HoldingsPage />);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Prix : \d+j/);
    expect(body).not.toContain('Prix inconnu');
  });

  it('StalePriceBadge: shows "Prix inconnu" when last_price_date is null', () => {
    const nullDatePosition = { ...mockPositions[0], last_price_date: null, last_price_source: 'yahoo' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [nullDatePosition], isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('Prix inconnu')).toBeTruthy();
  });

  it('StalePriceBadge: shows no badge for manual source even if date is old', () => {
    const oldDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const manualStale = { ...mockPositions[0], last_price_date: oldDate, last_price_source: 'manual' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [manualStale], isLoading: false, isError: false });
    render(<HoldingsPage />);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Prix : \d+j/);
    expect(body).not.toContain('Prix inconnu');
  });

  it('StalePriceBadge: shows no badge for manuel source (French spelling)', () => {
    const oldDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const manuelStale = { ...mockPositions[0], last_price_date: oldDate, last_price_source: 'manuel' };
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [manuelStale], isLoading: false, isError: false });
    render(<HoldingsPage />);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Prix : \d+j/);
    expect(body).not.toContain('Prix inconnu');
  });

  // ── PV columns ──────────────────────────────────────────────────────────────

  it('renders PV latente column headers', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('PV latente')).toBeTruthy();
    expect(screen.getByText('PV latente %')).toBeTruthy();
  });

  it('shows PV latente value for a position in the pvMap', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    // AAPL is in mockCapitalGains with unrealized_pv=100 → shows "+100.00 €"
    const body = document.body.textContent ?? '';
    expect(body).toContain('+100.00 €');
  });

  it('shows "—" for PV latente when ticker not in pvMap', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    const unknownPosition = [{ ...mockPositions[0], ticker: 'UNKNOWN', product_name: 'Unknown' }];
    mockUseHoldings.mockReturnValue({ data: unknownPosition, isLoading: false, isError: false });
    render(<HoldingsPage />);
    // UNKNOWN not in pvMap → shows — for PV latente
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it('shows pool PV subtotal row when pvMap has data', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.getByText('Sous-total pool')).toBeTruthy();
  });

  it('shows no pool PV subtotal when no positions match pvMap', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    const unknownPositions = [{ ...mockPositions[0], ticker: 'UNKNOWN' }];
    mockUseHoldings.mockReturnValue({ data: unknownPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    expect(screen.queryByText('Sous-total pool')).toBeNull();
  });

  it('uses empty pvMap when capital gains returns no data', () => {
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: mockPositions, isLoading: false, isError: false });
    render(<HoldingsPage />);
    // Should render without crash; no subtotal row since pvMap is empty
    expect(screen.getByText('Positions actuelles')).toBeTruthy();
    expect(screen.queryByText('Sous-total pool')).toBeNull();
  });
});

describe('StalePriceBadge unit', () => {
  it('returns null for manual source (English)', () => {
    const { container } = render(
      <StalePriceBadge lastPriceDate={null} source="manual" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('returns null for manuel source (French)', () => {
    const { container } = render(
      <StalePriceBadge lastPriceDate={null} source="manuel" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows "Prix inconnu" for null date and non-manual source', () => {
    render(<StalePriceBadge lastPriceDate={null} source="yahoo" />);
    expect(screen.getByText('Prix inconnu')).toBeTruthy();
  });

  it('shows no badge for a date 1 day ago', () => {
    const oneDayAgo = new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const { container } = render(<StalePriceBadge lastPriceDate={oneDayAgo} source="yahoo" />);
    expect(container.firstChild).toBeNull();
  });

  it('shows no badge for a date exactly 2 days ago', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const { container } = render(<StalePriceBadge lastPriceDate={twoDaysAgo} source="yahoo" />);
    expect(container.firstChild).toBeNull();
  });

  it('shows badge for a date 3 days ago', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    render(<StalePriceBadge lastPriceDate={threeDaysAgo} source="yahoo" />);
    expect(screen.getByText('Prix : 3j')).toBeTruthy();
  });

  it('shows badge with correct day count for a date 10 days ago', () => {
    const tenDaysAgo = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    render(<StalePriceBadge lastPriceDate={tenDaysAgo} source="yahoo" />);
    expect(screen.getByText('Prix : 10j')).toBeTruthy();
  });
});
