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

const mockUseSectorPerformance = vi.fn();
vi.mock('../api/queries', () => ({
  useSectorPerformance: () => mockUseSectorPerformance(),
}));

const mockUseSectorPerfSyncStatus = vi.fn();
vi.mock('../hooks/useMacroSyncStatus', () => ({
  useSectorPerfSyncStatus: () => mockUseSectorPerfSyncStatus(),
}));

const mockUseSyncStatusInvalidation = vi.fn();
vi.mock('../hooks/useSyncStatusInvalidation', () => ({
  useSyncStatusInvalidation: (...args: any[]) => mockUseSyncStatusInvalidation(...args),
}));

import SectorPerformanceSection from './SectorPerformanceSection';

const ENTRIES = [
  { code: 'or', label: 'Or', currency: 'USD', perf_pct: 20.19, latest_date: '2026-07-19', anchor_date: '2025-07-19', index_label: 'Or (COMEX)' },
];

describe('SectorPerformanceSection', () => {
  beforeEach(() => {
    mockUseSectorPerformance.mockReturnValue({ data: ENTRIES, isLoading: false });
    mockUseSectorPerfSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockUseSyncStatusInvalidation.mockClear();
  });

  it('renders the chart with the sector performance title', () => {
    render(<SectorPerformanceSection />);
    expect(screen.getByText("Performance des classes d'actifs sur 1 an (EUR)")).toBeInTheDocument();
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseSectorPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-07-19T07:30:00Z', finished_at: '2026-07-19T07:30:05Z', total_tickers: 4, succeeded: 4, failed_tickers: [] } });
    render(<SectorPerformanceSection />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<SectorPerformanceSection />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('delegates sync-status invalidation to useSyncStatusInvalidation with the sector-performance key', () => {
    mockUseSectorPerfSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-19T07:30:05Z', total_tickers: 4, succeeded: 4, failed_tickers: [] } });
    render(<SectorPerformanceSection />);
    expect(mockUseSyncStatusInvalidation).toHaveBeenCalledWith('2026-07-19T07:30:05Z', [['sector-performance']]);
  });
});
