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

vi.mock('@patternfly/react-charts/victory', () => ({
  Chart: ({ children }: any) => <div data-testid="chart">{children}</div>,
  ChartAxis: () => null,
  ChartBar: () => <div data-testid="chart-bar" />,
  ChartTooltip: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

const mockUseBondPerformance = vi.fn();
vi.mock('../api/queries', () => ({
  useBondPerformance: () => mockUseBondPerformance(),
}));

const mockUseBondPerfSyncStatus = vi.fn();
vi.mock('../hooks/useMacroSyncStatus', () => ({
  useBondPerfSyncStatus: () => mockUseBondPerfSyncStatus(),
}));

const mockUseSyncStatusInvalidation = vi.fn();
vi.mock('../hooks/useSyncStatusInvalidation', () => ({
  useSyncStatusInvalidation: (...args: any[]) => mockUseSyncStatusInvalidation(...args),
}));

import BondPerformanceSection from './BondPerformanceSection';

const ENTRIES = [
  { code: 'us', label: 'États-Unis', currency: 'USD', perf_pct: -2.5, latest_date: '2026-09-06', anchor_date: '2025-09-06', index_label: 'Trésor américain 7-10 ans (IEF)' },
  { code: 'se', label: 'Suède', currency: 'SEK', perf_pct: 1.2, latest_date: '2026-09-06', anchor_date: '2025-09-06', index_label: 'Obligations suédoises mixtes' },
];

describe('BondPerformanceSection', () => {
  beforeEach(() => {
    mockUseBondPerformance.mockReturnValue({ data: ENTRIES, isLoading: false });
    mockUseBondPerfSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockUseSyncStatusInvalidation.mockClear();
  });

  it('renders the chart with the bond performance title', () => {
    render(<BondPerformanceSection />);
    expect(screen.getByText('Performance des marchés obligataires souverains sur 1 an (EUR)')).toBeInTheDocument();
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseBondPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-09-06T06:00:00Z', finished_at: '2026-09-06T06:00:05Z', total_tickers: 15, succeeded: 15, failed_tickers: [] } });
    render(<BondPerformanceSection />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<BondPerformanceSection />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('delegates sync-status invalidation to useSyncStatusInvalidation with the bond-performance key', () => {
    mockUseBondPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-09-06T06:00:05Z', total_tickers: 15, succeeded: 15, failed_tickers: [] } });
    render(<BondPerformanceSection />);
    expect(mockUseSyncStatusInvalidation).toHaveBeenCalledWith('2026-09-06T06:00:05Z', [['bond-performance']]);
  });

  it('shows a caveat note listing countries whose tracked product is not a pure sovereign-only bond', () => {
    render(<BondPerformanceSection />);
    expect(screen.getByText(/Suède/)).toBeInTheDocument();
  });

  it('shows no caveat note when no returned country is in the caveat list', () => {
    mockUseBondPerformance.mockReturnValue({
      data: [ENTRIES[0]], // 'us' only, not in CAVEAT_CODES
      isLoading: false,
    });
    render(<BondPerformanceSection />);
    expect(screen.queryByText(/⚠️/)).not.toBeInTheDocument();
  });

  it('shows no caveat note when data is not loaded yet', () => {
    mockUseBondPerformance.mockReturnValue({ data: undefined, isLoading: true });
    render(<BondPerformanceSection />);
    expect(screen.queryByText(/⚠️/)).not.toBeInTheDocument();
  });
});
