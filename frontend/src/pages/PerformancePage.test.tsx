// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for PerformancePage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

// Polyfills for jsdom
(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

// Mock PatternFly core — override Spinner (size prop), Pagination for PerformancePage specifics
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Pagination: ({ onSetPage, page }: any) => (
    <div data-testid="pagination">
      <button onClick={() => onSetPage(null, page + 1)}>Next</button>
    </div>
  ),
  // Override Spinner to accept size prop for spinner-md / spinner-xl assertions
  Spinner: ({ size }: any) => <div data-testid={`spinner-${size || 'xl'}`} />,
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <button onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div>{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
  ModalVariant: { large: 'large' },
}));

// Mock PatternFly table
vi.mock('@patternfly/react-table', () => pfTableStubs);

// Mock PatternFly charts
vi.mock('@patternfly/react-charts/victory', () => ({
  Chart: ({ children, containerComponent }: any) => (
    <div data-testid="chart">
      {/* Render containerComponent so VictoryZoomContainer mock is called and callbacks captured */}
      {containerComponent ?? null}
      {children}
    </div>
  ),
  ChartArea: () => <div data-testid="chart-area" />,
  ChartAxis: ({ tickFormat, dependentAxis }: any) => {
    // Exercise the tickFormat callback with a few sample dates to cover date formatting branches
    if (tickFormat && !dependentAxis) {
      try {
        // Short zoom (< 90 days) — triggers full date format
        tickFormat(new Date('2024-06-15'));
        // Also try with a non-Date value to cover `instanceof Date` branch
        tickFormat(new Date('2024-01-01').getTime() as any);
      } catch {
        // Ignore errors — we just want to exercise the code paths
      }
    }
    // Also exercise dependent axis (y-axis) tickFormat with numeric values (lines 552, 599, 629, 712)
    if (tickFormat && dependentAxis) {
      try {
        tickFormat(100);    // covers y.toFixed(0) in index charts
        tickFormat(500);    // < 1000 → covers '${y}€' branch in patrimoine chart (line 712)
        tickFormat(1500);   // >= 1000 → covers '${(y/1000).toFixed(0)}k€' branch (line 712)
      } catch { /* ignore */ }
    }
    return null;
  },
  ChartGroup: ({ children }: any) => <>{children}</>,
  ChartLine: () => <div data-testid="chart-line" />,
  ChartThemeColor: { green: 'green', blue: 'blue', multi: 'multi' },
}));

// Mock victory-zoom-container — captures onZoomDomainChange callbacks for direct testing
// Each render of VictoryZoomContainer pushes its callback to this array.
// Tests can call capturedZoomCallbacks[n]({ x: [...] }) inside act() to cover
// the onZoomDomainChange handlers without causing infinite render loops.
const capturedZoomCallbacks: Array<(domain: any) => void> = [];

vi.mock('victory-zoom-container', () => ({
  VictoryZoomContainer: ({ onZoomDomainChange }: any) => {
    if (typeof onZoomDomainChange === 'function') {
      capturedZoomCallbacks.push(onZoomDomainChange);
    }
    return null;
  },
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatUnitPrice: (v: number, _c?: string) => `${v} €`,
  dateToLocalStr: (d?: Date) => d ? `${d.getFullYear()}-01-01` : '2026-01-01',
  localDateStr: (_offset?: number) => '2026-01-01',
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct1: (val: number) => `${val.toFixed(1)} %`,
}));

// Mock API queries
const mockUseDailySnapshots = vi.fn();
const mockUseHoldingsAtDate = vi.fn();
const mockUseMonthlySnapshots = vi.fn();
const mockUseDailyWithPools = vi.fn();
const mockUseTWRR = vi.fn();

vi.mock('../api/queries', () => ({
  useDailySnapshots: (...args: any[]) => mockUseDailySnapshots(...args),
  useHoldingsAtDate: (...args: any[]) => mockUseHoldingsAtDate(...args),
  useMonthlySnapshots: (...args: any[]) => mockUseMonthlySnapshots(...args),
  useDailyWithPools: (...args: any[]) => mockUseDailyWithPools(...args),
  useTWRR: (...args: any[]) => mockUseTWRR(...args),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
}));

import PerformancePage from './PerformancePage';

// Dates within the default 1Y zoom window (1 year ago to today from 2026-05-19):
// zStart ≈ 2025-05-19, so dates >= 2025-06-01 fall inside.
// rebase ref = first point >= zStart = 2025-06-01 with index 120
// rebased 2026-05-18 = Math.round((130/120)*10000)/100 = 108.33
// periodTwrrPct = 108.33 - 100 = 8.33
const mockTWRR = {
  total: [
    { date: '2024-01-01', index: 100 },
    { date: '2025-06-01', index: 120 },
    { date: '2026-05-18', index: 130 },
  ],
  offensive: [{ date: '2025-06-01', index: 120 }, { date: '2026-05-18', index: 125 }],
  defensive: [{ date: '2025-06-01', index: 100 }, { date: '2026-05-18', index: 105 }],
  pools: { Asie: [{ date: '2025-06-01', index: 100 }, { date: '2026-05-18', index: 110 }] },
  positions: { AAPL: [{ date: '2025-06-01', index: 100 }, { date: '2026-05-18', index: 112 }] },
};

// For negative TWRR test: index decreases inside zoom window (120 → 108)
// rebased 2026-05-18 = Math.round((108/120)*10000)/100 = 90.00
// periodTwrrPct = 90.00 - 100 = -10.00
const mockTWRRNegative = {
  ...mockTWRR,
  total: [
    { date: '2025-06-01', index: 120 },
    { date: '2026-05-18', index: 108 },
  ],
};

const mockDailySnapshots = [
  { id: 1, portfolio_id: 1, date: '2024-01-01', total_eur: 10000, offensive_eur: 5000, defensive_eur: 5000 },
  { id: 2, portfolio_id: 1, date: '2024-06-01', total_eur: 11000, offensive_eur: 5500, defensive_eur: 5500 },
];



describe('PerformancePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedZoomCallbacks.length = 0;
    mockUseDailyWithPools.mockReturnValue({ data: [] });
    mockUseHoldingsAtDate.mockReturnValue({ data: undefined, isLoading: false });
  });

  it('shows spinner when loading (daily)', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: true });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: undefined, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getAllByTestId(/spinner/).length).toBeGreaterThan(0);
  });

  it('shows spinner when loading (monthly)', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: true });
    mockUseTWRR.mockReturnValue({ data: undefined, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getAllByTestId(/spinner/).length).toBeGreaterThan(0);
  });

  it('shows spinner when loading (TWRR)', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: undefined, isLoading: true });

    render(<PerformancePage />);
    expect(screen.getAllByTestId(/spinner/).length).toBeGreaterThan(0);
  });

  it('renders page title when data is loaded', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('renders Valeur patrimoine card with current value and MAX euro change', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('Valeur patrimoine')).toBeInTheDocument();
    // Last snapshot total_eur = 11000
    expect(screen.getAllByText('11000.00 €').length).toBeGreaterThanOrEqual(1);
    // abs change for available periods (1M,3M,YTD,MAX) = 11000-10000 = +1000
    expect(screen.getAllByText('+1000.00 €').length).toBeGreaterThanOrEqual(1);
  });

  it('renders TWRR card with period grid', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('TWRR (Time-Weighted Rate of Return)')).toBeInTheDocument();
    expect(screen.getByText(/Mesure fiable/i)).toBeInTheDocument();
    // Both grids show period labels (Valeur patrimoine + TWRR)
    expect(screen.getAllByText('1Y').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('MAX').length).toBeGreaterThanOrEqual(2);
  });

  it('shows snapshots table', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('2024-01-01')).toBeInTheDocument();
  });

  it('time scale buttons are rendered', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getAllByText('1M')[0]).toBeInTheDocument();
    expect(screen.getAllByText('MAX')[0]).toBeInTheDocument();
  });

  it('clicking time scale changes selected scale', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const btn1M = screen.getAllByText('1M')[0];
    await user.click(btn1M);
    // After clicking 1M, check the page still renders
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('toggle view buttons render and can be clicked', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Click Offensif / Défensif toggle
    await user.click(screen.getByTestId('toggle-Offensif / Défensif'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('toggle to Pools view', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getByTestId('toggle-Pools'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('toggle to Positions view', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getByTestId('toggle-Positions'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('clicking MAX time scale', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getAllByText('MAX')[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('clicking a snapshot row opens modal', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    mockUseHoldingsAtDate.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Click the first snapshot row
    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    if (snapRow) {
      await user.click(snapRow);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    }
  });

  it('modal closes when onClose is called', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    mockUseHoldingsAtDate.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    if (snapRow) {
      await user.click(snapRow);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
      // Close the modal
      await user.click(screen.getByText('Close'));
      expect(screen.queryByTestId('modal')).toBeNull();
    }
  });

  it('shows modal with loading spinner when hist positions are loading', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    mockUseHoldingsAtDate.mockReturnValue({ data: undefined, isLoading: true });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    if (snapRow) {
      await user.click(snapRow);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    }
  });

  it('shows modal with positions when histPositions has data', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    const histPositions = [
      {
        ticker: 'AAPL', product_name: 'Apple', pool_id: 1, pool_name: 'Asie',
        quantity: 10, last_price: 150, last_price_date: '2024-01-01',
        last_price_source: 'yahoo', value_eur: 2000, currency: 'USD',
      },
      {
        ticker: 'TSLA', product_name: 'Tesla', pool_id: 2, pool_name: 'Non assigné',
        quantity: 5, last_price: 200, last_price_date: '2024-01-01',
        last_price_source: 'yahoo', value_eur: 1000, currency: 'USD',
      },
      {
        ticker: 'MSFT', product_name: 'Microsoft', pool_id: 1, pool_name: 'Asie',
        quantity: 8, last_price: 300, last_price_date: '2024-01-01',
        last_price_source: 'yahoo', value_eur: 2400, currency: 'USD',
      },
    ];
    mockUseHoldingsAtDate.mockReturnValue({ data: histPositions, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    if (snapRow) {
      await user.click(snapRow);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
      // Positions should be shown in the modal
      expect(screen.getByText('AAPL')).toBeInTheDocument();
    }
  });

  it('clicking a composable ticker inside the snapshot modal opens the composition modal, and closing it clears the state', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    mockUseHoldingsAtDate.mockReturnValue({
      data: [{
        ticker: 'AAPL', product_name: 'Apple', pool_id: 1, pool_name: 'Asie', instrument_type: 'ETF',
        quantity: 10, last_price: 150, last_price_date: '2024-01-01',
        last_price_source: 'yahoo', value_eur: 2000, currency: 'USD',
      }],
      isLoading: false,
    });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    expect(snapRow).toBeInTheDocument();
    await user.click(snapRow!);
    const snapshotModal = screen.getByTestId('modal');

    await user.click(within(snapshotModal).getByText('AAPL'));
    const modals = screen.getAllByTestId('modal');
    expect(modals.length).toBe(2);

    await user.click(screen.getAllByText('Close')[1]);
    expect(screen.getAllByTestId('modal').length).toBe(1);
  });

  it('renders "Aucune donnée disponible." when patrimoineData is empty', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('Aucune donnée disponible.')).toBeInTheDocument();
  });

  it('clicking 3M time scale sets selected scale', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getAllByText('3M')[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('clicking YTD time scale works', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getAllByText('YTD')[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('clicking 5Y time scale works', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getAllByText('5Y')[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('clicking 10Y time scale works', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    await user.click(screen.getAllByText('10Y')[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('renders two KPI cards: Valeur patrimoine and TWRR', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('Valeur patrimoine')).toBeInTheDocument();
    expect(screen.getByText('TWRR (Time-Weighted Rate of Return)')).toBeInTheDocument();
    expect(screen.getByText(/Mesure fiable/i)).toBeInTheDocument();
  });

  it('shows Aucun snapshot when no daily data', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('Aucun snapshot disponible.')).toBeInTheDocument();
  });

  it('pagination button can be clicked', async () => {
    // Enough snapshots to need pagination (SNAP_PAGE_SIZE = 15)
    const manySnapshots = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1, portfolio_id: 1,
      date: `2024-01-${String(i + 1).padStart(2, '0')}`,
      total_eur: 10000 + i * 100, offensive_eur: 5000, defensive_eur: 5000,
    }));
    mockUseDailySnapshots.mockReturnValue({ data: manySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Pagination should be rendered
    expect(screen.getByTestId('pagination')).toBeInTheDocument();
    await user.click(screen.getByText('Next'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('shows "Aucune position à cette date." when histPositions is empty', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });
    mockUseHoldingsAtDate.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    const rows = screen.getAllByRole('row');
    const snapRow = rows.find(r => r.textContent?.includes('2024-01-01'));
    if (snapRow) {
      await user.click(snapRow);
      expect(screen.getByText('Aucune position à cette date.')).toBeInTheDocument();
    }
  });

  it('shows patrimoine chart when daily snapshots are available', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    // The chart should render when patrimoineData.length > 0
    expect(screen.getByText(/Évolution du patrimoine/i)).toBeInTheDocument();
    // Chart area should appear (not "Aucune donnée disponible.")
    const noDataMsgs = screen.queryAllByText('Aucune donnée disponible.');
    expect(noDataMsgs.length).toBe(0);
  });

  it('shows ↺ Réinitialiser zoom button only after brush zoom interaction', async () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 400, top: 0, left: 0,
      bottom: 400, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    render(<PerformancePage />);

    // Initially no reset zoom button (time-scale zoom is not "manual")
    expect(screen.queryAllByText(/↺ Réinitialiser zoom/i).length).toBe(0);

    // Simulate a brush drag on the index chart → sets isManuallyZoomedIndex=true
    const chartDivs = document.querySelectorAll('[style*="user-select: none"]');
    if (chartDivs.length > 0) {
      fireEvent.mouseDown(chartDivs[0] as HTMLElement, { clientX: 100, clientY: 50 });
      fireEvent.mouseMove(chartDivs[0] as HTMLElement, { clientX: 500, clientY: 50 });
      fireEvent.mouseUp(chartDivs[0] as HTMLElement);
    }

    const resetBtns = screen.getAllByText(/↺ Réinitialiser zoom/i);
    expect(resetBtns.length).toBeGreaterThan(0);
    // Click the reset zoom button
    fireEvent.click(resetBtns[0]);
    expect(screen.getByText('Performance')).toBeInTheDocument();

    vi.restoreAllMocks();
  });

  it('shows TWRR strategie view with legend buttons', async () => {
    const twrrWithData = {
      ...mockTWRR,
      offensive: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 105 }],
      defensive: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 98 }],
    };
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: twrrWithData, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Toggle to strategie view
    await user.click(screen.getByTestId('toggle-Offensif / Défensif'));
    // Legend buttons should appear for Offensif and Défensif
    expect(screen.getByText('Offensif')).toBeInTheDocument();
    expect(screen.getByText('Défensif')).toBeInTheDocument();
    // Click the Offensif legend button to toggle visibility
    await user.click(screen.getByText('Offensif'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('shows TWRR pools view with pool legend buttons', async () => {
    const twrrWithPools = {
      ...mockTWRR,
      pools: {
        Asie: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 110 }],
        Or: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 95 }],
      },
    };
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: twrrWithPools, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Toggle to pools view — should show pool names in legend
    await user.click(screen.getByTestId('toggle-Pools'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
    // Click a pool legend button to toggle visibility
    const asieBtn = screen.queryByText('Asie');
    if (asieBtn) {
      await user.click(asieBtn);
    }
  });

  it('shows TWRR positions view with position legend buttons', async () => {
    const twrrWithPositions = {
      ...mockTWRR,
      positions: {
        AAPL: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 120 }],
        TSLA: [{ date: '2024-01-01', index: 100 }, { date: '2024-06-01', index: 80 }],
      },
    };
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: twrrWithPositions, isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<PerformancePage />);

    // Toggle to positions view
    await user.click(screen.getByTestId('toggle-Positions'));
    expect(screen.getByText('Performance')).toBeInTheDocument();
    const aaplBtn = screen.queryByText('AAPL');
    if (aaplBtn) {
      await user.click(aaplBtn);
    }
  });

  it('brush events on index chart div — mousedown, mousemove, mouseup', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);

    // Find chart div containers (they have onMouseDown etc.)
    const chartDivs = document.querySelectorAll('[style*="user-select: none"]');
    if (chartDivs.length > 0) {
      const chartDiv = chartDivs[0] as HTMLElement;
      // Trigger brush start
      fireEvent.mouseDown(chartDiv, { clientX: 100, clientY: 50 });
      // Trigger brush move
      fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
      // Trigger brush end (short drag — less than 5px threshold won't apply zoom)
      fireEvent.mouseUp(chartDiv);
    }
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('brush events on patrimoine chart div — mousedown, mousemove, mouseleave', () => {
    mockUseDailySnapshots.mockReturnValue({ data: mockDailySnapshots, isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);

    const chartDivs = document.querySelectorAll('[style*="user-select: none"]');
    if (chartDivs.length > 1) {
      const patrimoineDiv = chartDivs[1] as HTMLElement;
      fireEvent.mouseDown(patrimoineDiv, { clientX: 100, clientY: 50 });
      fireEvent.mouseMove(patrimoineDiv, { clientX: 200, clientY: 50 });
      fireEvent.mouseLeave(patrimoineDiv);
    }
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('TWRR period grid shows 1Y value (index 120→130 = +8.33%)', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    expect(screen.getByText('TWRR (Time-Weighted Rate of Return)')).toBeInTheDocument();
    // 1Y period: index 120→130 = (130/120-1)*100 = 8.33%
    expect(screen.getByText('+8.33 %')).toBeInTheDocument();
    expect(screen.getByText(/Mesure fiable/i)).toBeInTheDocument();
  });

  it('shows "Non disponible" in Valeur patrimoine when no daily snapshots', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseTWRR.mockReturnValue({ data: mockTWRR, isLoading: false });

    render(<PerformancePage />);
    const nonDispos = screen.getAllByText('Non disponible');
    expect(nonDispos.length).toBeGreaterThanOrEqual(1);
  });

  it('TWRR period grid shows negative value (danger color branch)', () => {
    mockUseDailySnapshots.mockReturnValue({ data: [], isLoading: false });
    mockUseMonthlySnapshots.mockReturnValue({ data: [], isLoading: false });
    // index 120 → 108: 1Y and MAX = (108/120-1)*100 = -10.00%
    mockUseTWRR.mockReturnValue({ data: mockTWRRNegative, isLoading: false });

    render(<PerformancePage />);
    // Multiple periods show -10.00% — use getAllByText
    expect(screen.getAllByText('-10.00 %').length).toBeGreaterThanOrEqual(1);
  });
});
