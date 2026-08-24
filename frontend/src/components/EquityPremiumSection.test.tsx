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

let capturedBarData: any[] | null = null;
let capturedColorBySign: boolean | undefined;

vi.mock('@patternfly/react-charts/victory', () => ({
  Chart: ({ children }: any) => <div data-testid="chart">{children}</div>,
  ChartAxis: () => null,
  ChartBar: ({ data }: any) => {
    capturedBarData = data;
    return <div data-testid="chart-bar" />;
  },
  ChartTooltip: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

const mockUseEquityPremium = vi.fn();
vi.mock('../api/queries', () => ({
  useEquityPremium: () => mockUseEquityPremium(),
}));

const mockUseEquityPremiumSyncStatus = vi.fn();
vi.mock('../hooks/useMacroSyncStatus', () => ({
  useEquityPremiumSyncStatus: () => mockUseEquityPremiumSyncStatus(),
}));

const mockUseSyncStatusInvalidation = vi.fn();
vi.mock('../hooks/useSyncStatusInvalidation', () => ({
  useSyncStatusInvalidation: (...args: any[]) => mockUseSyncStatusInvalidation(...args),
}));

// PerformanceBarChart isn't mocked directly — mocking its victory-chart deps above (same
// pattern as SectorPerformanceSection.test.tsx) is enough to render it in jsdom, while still
// letting us assert on colorBySign by wrapping the real component.
vi.mock('./PerformanceBarChart', async () => {
  const actual = await vi.importActual<any>('./PerformanceBarChart');
  return {
    default: (props: any) => {
      capturedColorBySign = props.colorBySign;
      return actual.default(props);
    },
  };
});

import EquityPremiumSection from './EquityPremiumSection';

const ENTRIES = [
  {
    code: 'us', label: 'États-Unis', premium_pct: 2.5, equity_yield_pct: 4.0, bond_yield_pct: 1.5,
    equity_label: 'S&P 500 (SPY)', bond_label: 'Trésor US (IEF)', asof_date: '2026-07-19',
  },
];

describe('EquityPremiumSection', () => {
  beforeEach(() => {
    capturedBarData = null;
    capturedColorBySign = undefined;
    mockUseEquityPremium.mockReturnValue({ data: ENTRIES, isLoading: false });
    mockUseEquityPremiumSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockUseSyncStatusInvalidation.mockClear();
  });

  it('renders the chart with the equity premium title', () => {
    render(<EquityPremiumSection />);
    expect(screen.getByText('Prime de risque des actions (Equity Risk Premium)')).toBeInTheDocument();
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('maps entries into the generic chart datum shape with a rich tooltip label', () => {
    render(<EquityPremiumSection />);
    expect(capturedBarData).toEqual([
      { x: 'États-Unis', y: 2.5, tooltipLabel: 'S&P 500 (SPY) (4.0%) vs Trésor US (IEF) (1.5%)' },
    ]);
  });

  it('enables sign-based bar coloring', () => {
    render(<EquityPremiumSection />);
    expect(capturedColorBySign).toBe(true);
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseEquityPremiumSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-07-19T07:45:00Z', finished_at: '2026-07-19T07:45:05Z', total_tickers: 22, succeeded: 22, failed_tickers: [] } });
    render(<EquityPremiumSection />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<EquityPremiumSection />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('delegates sync-status invalidation to useSyncStatusInvalidation with the equity-premium key', () => {
    mockUseEquityPremiumSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-19T07:45:05Z', total_tickers: 22, succeeded: 22, failed_tickers: [] } });
    render(<EquityPremiumSection />);
    expect(mockUseSyncStatusInvalidation).toHaveBeenCalledWith('2026-07-19T07:45:05Z', [['equity-premium']]);
  });
});
