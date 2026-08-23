// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

vi.mock('@patternfly/react-core', () => ({ ...pfCoreStubs }));

vi.mock('@patternfly/react-charts', () => ({
  Chart: ({ children }: any) => <div data-testid="chart">{children}</div>,
  ChartAxis: () => null,
  ChartBar: () => <div data-testid="chart-bar" />,
  ChartTooltip: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

const mockUseCountryPerformance = vi.fn();
vi.mock('../api/queries', () => ({
  useCountryPerformance: () => mockUseCountryPerformance(),
}));

const mockUseCountryPerfSyncStatus = vi.fn();
vi.mock('../hooks/useMacroSyncStatus', () => ({
  useCountryPerfSyncStatus: () => mockUseCountryPerfSyncStatus(),
}));

const mockUseSyncStatusInvalidation = vi.fn();
vi.mock('../hooks/useSyncStatusInvalidation', () => ({
  useSyncStatusInvalidation: (...args: any[]) => mockUseSyncStatusInvalidation(...args),
}));

import MarketPerformanceSection from './MarketPerformanceSection';

const ENTRIES = [
  { code: 'us', label: 'États-Unis', currency: 'USD', perf_pct: 20.19, latest_date: '2026-07-19', anchor_date: '2025-07-19', index_label: 'S&P 500' },
];

describe('MarketPerformanceSection', () => {
  beforeEach(() => {
    mockUseCountryPerformance.mockReturnValue({ data: ENTRIES, isLoading: false });
    mockUseCountryPerfSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockUseSyncStatusInvalidation.mockClear();
  });

  it('renders the chart with the market performance title', () => {
    render(<MarketPerformanceSection />);
    expect(screen.getByText('Top 15 — Performance boursière sur 1 an (EUR)')).toBeInTheDocument();
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseCountryPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-07-19T07:15:00Z', finished_at: '2026-07-19T07:15:05Z', total_tickers: 23, succeeded: 23, failed_tickers: [] } });
    render(<MarketPerformanceSection />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<MarketPerformanceSection />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('delegates sync-status invalidation to useSyncStatusInvalidation with the country-performance key', () => {
    mockUseCountryPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-19T07:15:05Z', total_tickers: 23, succeeded: 23, failed_tickers: [] } });
    render(<MarketPerformanceSection />);
    expect(mockUseSyncStatusInvalidation).toHaveBeenCalledWith('2026-07-19T07:15:05Z', [['country-performance']]);
  });
});
