// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  ChartLine: () => <div data-testid="chart-line" />,
  ChartAxis: () => null,
  ChartGroup: ({ children }: any) => <>{children}</>,
  ChartLegend: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

const mockUseGrowthIndicator = vi.fn();
const mockUseInflationIndicator = vi.fn();
const mockUseMacroRegions = vi.fn();

vi.mock('../api/queries', () => ({
  useGrowthIndicator: (region: string) => mockUseGrowthIndicator(region),
  useInflationIndicator: (region: string) => mockUseInflationIndicator(region),
  useMacroRegions: () => mockUseMacroRegions(),
}));

const mockUseMacroSyncStatus = vi.fn();
vi.mock('../hooks/useMacroSyncStatus', () => ({
  useMacroSyncStatus: () => mockUseMacroSyncStatus(),
}));

const mockUseSyncStatusInvalidation = vi.fn();
vi.mock('../hooks/useSyncStatusInvalidation', () => ({
  useSyncStatusInvalidation: (...args: any[]) => mockUseSyncStatusInvalidation(...args),
}));

import GrowthInflationSection from './GrowthInflationSection';

const emptyIndicator = {
  dates: [], ratio: [], moving_avg: [], ma_years: null, status: null, latest_date: null,
  numerator_ticker: null, denominator_ticker: null,
};
const growthData = {
  dates: ['2020-01-01'], ratio: [100], moving_avg: [95], ma_years: 7, status: 'above', latest_date: '2020-01-01',
  numerator_ticker: '^SPXEW', denominator_ticker: 'CL=F',
};

const REGIONS = [
  { code: 'us', label: 'États-Unis', equity_ticker: '^SPXEW', bond_ticker: 'GOVT' },
  { code: 'fr', label: 'France', equity_ticker: '^FCHI', bond_ticker: 'MTE.PA' },
];

describe('GrowthInflationSection', () => {
  beforeEach(() => {
    mockUseGrowthIndicator.mockReturnValue({ data: growthData, isLoading: false });
    mockUseInflationIndicator.mockReturnValue({ data: emptyIndicator, isLoading: false });
    mockUseMacroRegions.mockReturnValue({ data: REGIONS });
    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockUseSyncStatusInvalidation.mockClear();
  });

  it('defaults to the first region returned by the API and renders region-aware titles', () => {
    render(<GrowthInflationSection />);
    expect(screen.getByText('Croissance — États-Unis')).toBeInTheDocument();
    expect(screen.getByText('Inflation — États-Unis')).toBeInTheDocument();
    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('us');
    expect(mockUseInflationIndicator).toHaveBeenCalledWith('us');
  });

  it('does not crash and fetches with an empty region when the region list is empty', () => {
    mockUseMacroRegions.mockReturnValue({ data: [] });
    render(<GrowthInflationSection />);
    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('');
  });

  it('switching the region combobox re-fetches both indicators and updates titles', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GrowthInflationSection />);

    await user.selectOptions(screen.getByLabelText('Zone'), 'fr');

    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('fr');
    expect(mockUseInflationIndicator).toHaveBeenCalledWith('fr');
    expect(screen.getByText('Croissance — France')).toBeInTheDocument();
    expect(screen.getByText('Inflation — France')).toBeInTheDocument();
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-07-14T07:00:00Z', finished_at: '2026-07-14T07:00:05Z', total_tickers: 8, succeeded: 8, failed_tickers: [] } });
    render(<GrowthInflationSection />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<GrowthInflationSection />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('delegates sync-status invalidation to useSyncStatusInvalidation with the growth/inflation keys', () => {
    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-14T07:00:05Z', total_tickers: 8, succeeded: 8, failed_tickers: [] } });
    render(<GrowthInflationSection />);
    expect(mockUseSyncStatusInvalidation).toHaveBeenCalledWith(
      '2026-07-14T07:00:05Z', [['macro-growth'], ['macro-inflation']],
    );
  });
});
