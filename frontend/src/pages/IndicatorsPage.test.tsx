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

const mockInvalidateQueries = vi.fn();
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
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

import IndicatorsPage from './IndicatorsPage';

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

describe('IndicatorsPage', () => {
  beforeEach(() => {
    mockUseGrowthIndicator.mockReturnValue({ data: growthData, isLoading: false });
    mockUseInflationIndicator.mockReturnValue({ data: emptyIndicator, isLoading: false });
    mockUseMacroRegions.mockReturnValue({ data: REGIONS });
    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'never', started_at: null, finished_at: null, total_tickers: 0, succeeded: 0, failed_tickers: [] } });
    mockInvalidateQueries.mockClear();
  });

  it('defaults to the first region returned by the API and renders region-aware titles', () => {
    render(<IndicatorsPage />);
    expect(screen.getByText('Indicateurs macro')).toBeInTheDocument();
    expect(screen.getByText('Croissance — États-Unis')).toBeInTheDocument();
    expect(screen.getByText('Inflation — États-Unis')).toBeInTheDocument();
    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('us');
    expect(mockUseInflationIndicator).toHaveBeenCalledWith('us');
  });

  it('renders no region combobox options and does not crash when the region list is empty', () => {
    mockUseMacroRegions.mockReturnValue({ data: [] });
    render(<IndicatorsPage />);
    expect(screen.getByText('Indicateurs macro')).toBeInTheDocument();
    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('');
  });

  it('switching the region combobox re-fetches both indicators and updates titles', async () => {
    const user = userEvent.setup({ delay: null });
    render(<IndicatorsPage />);

    await user.selectOptions(screen.getByLabelText('Zone'), 'fr');

    expect(mockUseGrowthIndicator).toHaveBeenCalledWith('fr');
    expect(mockUseInflationIndicator).toHaveBeenCalledWith('fr');
    expect(screen.getByText('Croissance — France')).toBeInTheDocument();
    expect(screen.getByText('Inflation — France')).toBeInTheDocument();
  });

  it('shows the last sync time when a sync has already happened', () => {
    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'success', started_at: '2026-07-14T07:00:00Z', finished_at: '2026-07-14T07:00:05Z', total_tickers: 8, succeeded: 8, failed_tickers: [] } });
    render(<IndicatorsPage />);
    expect(screen.getByText(/Dernière synchro/)).toBeInTheDocument();
  });

  it('does not show a last sync time when never synced', () => {
    render(<IndicatorsPage />);
    expect(screen.queryByText(/Dernière synchro/)).not.toBeInTheDocument();
  });

  it('invalidates the growth/inflation queries when finished_at changes after the first render', () => {
    const { rerender } = render(<IndicatorsPage />);
    expect(mockInvalidateQueries).not.toHaveBeenCalled();

    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-14T07:00:05Z', total_tickers: 8, succeeded: 8, failed_tickers: [] } });
    rerender(<IndicatorsPage />);
    // First observed non-null value is just the baseline — no invalidation yet.
    expect(mockInvalidateQueries).not.toHaveBeenCalled();

    mockUseMacroSyncStatus.mockReturnValue({ data: { status: 'success', started_at: 't0', finished_at: '2026-07-14T08:00:05Z', total_tickers: 8, succeeded: 8, failed_tickers: [] } });
    rerender(<IndicatorsPage />);
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['macro-growth'] });
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['macro-inflation'] });

    // Re-rendering again with the SAME finished_at must not invalidate a second time.
    mockInvalidateQueries.mockClear();
    rerender(<IndicatorsPage />);
    expect(mockInvalidateQueries).not.toHaveBeenCalled();
  });
});
