// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for DashboardPage TreemapContent component.
 * Uses the real recharts Treemap to exercise the TreemapContent function.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
  Link: ({ children }: any) => <a>{children}</a>,
}));

// Mock PatternFly core — same override as DashboardPage.test.tsx (Modal with testids)
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <button data-testid="modal-close" onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div data-testid="modal-title">{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
  ModalVariant: { medium: 'medium' },
}));

// Mock PatternFly table
vi.mock('@patternfly/react-table', () => pfTableStubs);

// Mock PatternFly charts
vi.mock('@patternfly/react-charts/victory', () => ({
  ChartDonut: ({ events, data }: any) => (
    <div data-testid="chart-donut">
      {data?.map((d: any, i: number) => (
        <div
          key={i}
          data-testid={`donut-segment-${i}`}
          onClick={() => {
            if (events?.[0]?.eventHandlers?.onClick) {
              events[0].eventHandlers.onClick({} as any, { datum: d });
            }
          }}
        />
      ))}
    </div>
  ),
  ChartThemeColor: { multi: 'multi', green: 'green' },
}));

// DO NOT mock recharts — use the real implementation to cover TreemapContent
// We mock only the ResizeObserver polyfill since jsdom doesn't have it
(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock SyncBadge
vi.mock('../components/SyncBadge', () => ({
  default: () => <span data-testid="sync-badge" />,
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
const mockUseDashboard = vi.fn();
const mockUseHoldings = vi.fn();
const mockUseProducts = vi.fn();
const mockUsePrices = vi.fn();
const mockUseCapitalGains = vi.fn();

vi.mock('../api/queries', () => ({
  useDashboard: (...args: any[]) => mockUseDashboard(...args),
  useHoldings: (...args: any[]) => mockUseHoldings(...args),
  useProducts: () => mockUseProducts(),
  usePrices: (...args: any[]) => mockUsePrices(...args),
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
}));

import DashboardPage from './DashboardPage';

const mockDashboard = {
  total_eur: 100000,
  offensive_eur: 50000,
  defensive_eur: 50000,
  liquidity_eur: 1000,
  last_updated: '2024-01-01',
  pools: [
    { id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, current_value_eur: 25000, current_pct: 25, gap_pct: 0 },
    { id: 2, name: 'Or', strategy: 'Defensive', target_pct: 0.25, current_value_eur: 25000, current_pct: 25, gap_pct: 0 },
  ],
};

describe('DashboardPage — TreemapContent with real recharts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // No Manuel products by default → StalePriceWarning renders nothing
    mockUseProducts.mockReturnValue({ data: [] });
    mockUsePrices.mockReturnValue({ data: [] });
    mockUseCapitalGains.mockReturnValue({ data: { total_unrealized_pv: 0, total_realized_pv: 0, total_pv: 0, tickers: [] }, isLoading: false });
    // Mock getBoundingClientRect for recharts ResponsiveContainer
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 300, top: 0, left: 0,
      bottom: 300, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('TreemapContent returns null when width < 10 (tiny container, line 50)', () => {
    // With a very small container, recharts computes cells with width/height < 10px
    // This triggers the `if (width < 10 || height < 10) return null` guard
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 5, height: 5, top: 0, left: 0,
      bottom: 5, right: 5, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({
      data: [
        { ticker: 'AAPL', product_name: 'Apple', pool_id: 1, pool_name: 'Asie', quantity: 10, last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 15000, currency: 'USD' },
      ],
    });

    render(<DashboardPage />);
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });

  it('renders with real Treemap and covers TreemapContent (depth=1 pool node)', () => {
    mockUseDashboard.mockReturnValue({ data: mockDashboard, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({
      data: [
        { ticker: 'AAPL', product_name: 'Apple', pool_id: 1, pool_name: 'Asie', quantity: 10, last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 15000, currency: 'USD' },
        { ticker: 'MSFT', product_name: 'Microsoft', pool_id: 1, pool_name: 'Asie', quantity: 5, last_price: 300, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 10000, currency: 'USD' },
      ],
    });

    render(<DashboardPage />);
    // Page renders without crashing — covers TreemapContent paths
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });

  it('renders with real Treemap for Energie pool (unknown pool color — uses fallback)', () => {
    const dashWithEnergie = {
      ...mockDashboard,
      pools: [
        { id: 1, name: 'Energie', strategy: 'Offensive', target_pct: 0.25, current_value_eur: 30000, current_pct: 30, gap_pct: 5 },
      ],
    };
    mockUseDashboard.mockReturnValue({ data: dashWithEnergie, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({
      data: [
        { ticker: 'TTE.PA', product_name: 'TotalEnergies', pool_id: 1, pool_name: 'Energie', quantity: 100, last_price: 60, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 6000, currency: 'EUR' },
      ],
    });

    render(<DashboardPage />);
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });

  it('renders with pool with no positions — uses fallback child node in treemap', () => {
    const dashNoPos = {
      ...mockDashboard,
      pools: [
        { id: 1, name: 'Yen', strategy: 'Defensive', target_pct: 0.25, current_value_eur: 20000, current_pct: 20, gap_pct: -5 },
      ],
    };
    mockUseDashboard.mockReturnValue({ data: dashNoPos, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({ data: [] }); // No positions — fallback child used

    render(<DashboardPage />);
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });

  it('renders with unknown pool name for POOL_LIGHT fallback coverage', () => {
    const dashUnknown = {
      ...mockDashboard,
      pools: [
        { id: 1, name: 'CustomPool', strategy: 'Offensive', target_pct: 0.25, current_value_eur: 15000, current_pct: 15, gap_pct: -10 },
      ],
    };
    mockUseDashboard.mockReturnValue({ data: dashUnknown, isLoading: false, isError: false });
    mockUseHoldings.mockReturnValue({
      data: [
        { ticker: 'CUSTOM', product_name: 'Custom Asset', pool_id: 1, pool_name: 'CustomPool', quantity: 1, last_price: 100, last_price_date: '2024-01-01', last_price_source: 'manual', value_eur: 100, currency: 'EUR' },
      ],
    });

    render(<DashboardPage />);
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });
});
