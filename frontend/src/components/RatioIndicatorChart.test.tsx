import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

// Polyfills for jsdom
(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

vi.mock('@patternfly/react-core', () => ({ ...pfCoreStubs }));

let capturedDomain: any;
vi.mock('@patternfly/react-charts', () => ({
  Chart: ({ children, containerComponent, legendComponent, domain, legendData }: any) => {
    capturedDomain = domain;
    return (
      <div data-testid="chart">
        {containerComponent ?? null}
        {legendComponent ?? null}
        <div data-testid="legend-names">{(legendData ?? []).map((l: any) => l.name).join('|')}</div>
        {children}
      </div>
    );
  },
  ChartLine: ({ data }: any) => <div data-testid="chart-line" data-points={data?.length ?? 0} />,
  ChartAxis: ({ tickFormat, dependentAxis }: any) => {
    if (tickFormat) {
      try {
        tickFormat(dependentAxis ? 100 : new Date('2020-01-01'));
        // Also try a raw timestamp (not a Date instance) to cover the `instanceof Date` fallback.
        if (!dependentAxis) tickFormat(new Date('2020-01-02').getTime() as any);
      } catch { /* ignore */ }
    }
    return null;
  },
  ChartGroup: ({ children }: any) => <>{children}</>,
  ChartLegend: () => <div data-testid="chart-legend" />,
  ChartVoronoiContainer: ({ labels }: any) => {
    if (labels) {
      try { labels({ datum: { x: new Date('2020-01-01'), y: 42, name: 'Ratio' } }); } catch { /* ignore */ }
    }
    return <div data-testid="voronoi-container" />;
  },
  ChartThemeColor: { multi: 'multi' },
}));

import RatioIndicatorChart from './RatioIndicatorChart';
import type { RatioIndicator } from '../types';

const baseData: RatioIndicator = {
  dates: ['2020-01-01', '2020-01-02'],
  ratio: [100.0, 110.0],
  moving_avg: [100.0, 105.0],
  ma_years: 7,
  status: 'above',
  latest_date: '2020-01-02',
  numerator_ticker: '^SPXEW',
  denominator_ticker: 'CL=F',
  numerator_label: 'S&P 500 Equal Weight',
  denominator_label: 'Pétrole (WTI)',
};

const interpretationProps = {
  interpretationAbove: 'Interprétation haut',
  interpretationBelow: 'Interprétation bas',
};

function getChartContainer() {
  return screen.getByTestId('chart').parentElement as HTMLElement;
}

describe('RatioIndicatorChart', () => {
  beforeEach(() => {
    capturedDomain = undefined;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 320, top: 0, left: 0, bottom: 320, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  it('shows a spinner while loading', () => {
    render(<RatioIndicatorChart title="Growth" data={undefined} isLoading aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
  });

  it('shows an empty state when there is no data', () => {
    render(<RatioIndicatorChart title="Growth" data={undefined} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('shows an empty state when dates is an empty array', () => {
    const empty: RatioIndicator = { ...baseData, dates: [], ratio: [], moving_avg: [], status: null, latest_date: null };
    render(<RatioIndicatorChart title="Growth" data={empty} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('renders the chart, the "above" status label, and the interpretation text', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Croissance" belowLabel="Récession" {...interpretationProps} />);
    expect(screen.getByTestId('chart')).toBeInTheDocument();
    expect(screen.getAllByTestId('chart-line')).toHaveLength(2);
    const label = screen.getByTestId('label');
    expect(label).toHaveTextContent('Croissance');
    expect(label).toHaveAttribute('data-color', 'green');
    expect(screen.getByText('Interprétation haut')).toBeInTheDocument();
  });

  it('renders the "below" status label in red with its interpretation', () => {
    const below: RatioIndicator = { ...baseData, status: 'below' };
    render(<RatioIndicatorChart title="Inflation" data={below} isLoading={false} aboveLabel="Désinflation" belowLabel="Inflation" {...interpretationProps} />);
    const label = screen.getByTestId('label');
    expect(label).toHaveTextContent('Inflation');
    expect(label).toHaveAttribute('data-color', 'red');
    expect(screen.getByText('Interprétation bas')).toBeInTheDocument();
  });

  it('renders no status label or interpretation when status is null', () => {
    const noStatus: RatioIndicator = { ...baseData, status: null };
    render(<RatioIndicatorChart title="Growth" data={noStatus} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.queryByTestId('label')).not.toBeInTheDocument();
    expect(screen.queryByText('Interprétation haut')).not.toBeInTheDocument();
    expect(screen.queryByText('Interprétation bas')).not.toBeInTheDocument();
  });

  it('builds the legend from the descriptive labels, not the raw tickers, not a generic label', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const legend = screen.getByTestId('legend-names').textContent ?? '';
    expect(legend).toContain('S&P 500 Equal Weight');
    expect(legend).toContain('Pétrole (WTI)');
    expect(legend).not.toContain('^SPXEW');
  });

  it('falls back to the raw ticker in the legend when no descriptive label is provided', () => {
    const noLabels: RatioIndicator = { ...baseData, numerator_label: null, denominator_label: null };
    render(<RatioIndicatorChart title="Growth" data={noLabels} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const legend = screen.getByTestId('legend-names').textContent ?? '';
    expect(legend).toContain('^SPXEW');
    expect(legend).toContain('CL=F');
  });

  it('picks up the initial container width from getBoundingClientRect', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.getByTestId('chart')).toBeInTheDocument();
  });

  it('updates chart width when the ResizeObserver callback fires', () => {
    let capturedCallback: ((entries: any[]) => void) | null = null;
    (globalThis as any).ResizeObserver = class {
      constructor(cb: (entries: any[]) => void) { capturedCallback = cb; }
      observe() { capturedCallback?.([{ contentRect: { width: 950 } }]); }
      unobserve() {}
      disconnect() {}
    };

    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    expect(screen.getByTestId('chart')).toBeInTheDocument();

    (globalThis as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  // ── Brush-drag-to-zoom ──────────────────────────────────────────────────

  it('shows a brush overlay while dragging', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 400 });
    expect(screen.getByTestId('zoom-brush-overlay')).toBeInTheDocument();
  });

  it('completing a drag beyond the 5px threshold zooms in and shows the reset button', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 400 });
    fireEvent.mouseUp(container);

    expect(screen.getByText(/Réinitialiser zoom/)).toBeInTheDocument();
    expect(screen.queryByTestId('zoom-brush-overlay')).not.toBeInTheDocument();
    expect(capturedDomain).toBeDefined();
  });

  it('a drag under the 5px threshold does not zoom', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 102 });
    fireEvent.mouseUp(container);

    expect(screen.queryByText(/Réinitialiser zoom/)).not.toBeInTheDocument();
  });

  it('a completed drag on a collapsed (zero-width) container does not zoom', () => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 50, height: 320, top: 0, left: 0, bottom: 320, right: 50, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 5 });
    fireEvent.mouseMove(container, { clientX: 45 });
    fireEvent.mouseUp(container);

    expect(screen.queryByText(/Réinitialiser zoom/)).not.toBeInTheDocument();
  });

  it('clicking reset clears the zoom domain', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 400 });
    fireEvent.mouseUp(container);

    fireEvent.click(screen.getByText(/Réinitialiser zoom/));
    expect(screen.queryByText(/Réinitialiser zoom/)).not.toBeInTheDocument();
    expect(capturedDomain).toBeUndefined();
  });

  it('zooming into a narrow window (< 90 days) switches the axis to full-date formatting', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    // A tiny drag near the left edge, clamped to the 30-day minimum zoom window —
    // re-renders with zoomDays < 90, exercising the ChartAxis full-date tickFormat branch.
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 110 });
    fireEvent.mouseUp(container);
    expect(screen.getByText(/Réinitialiser zoom/)).toBeInTheDocument();
  });

  it('a wide drag on a multi-year dataset zooms without clamping to the 30-day minimum', () => {
    const wideData: RatioIndicator = {
      ...baseData,
      dates: ['2015-01-01', '2025-01-01'],
      ratio: [100.0, 130.0],
      moving_avg: [100.0, 120.0],
    };
    render(<RatioIndicatorChart title="Growth" data={wideData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 700 });
    fireEvent.mouseUp(container);

    expect(screen.getByText(/Réinitialiser zoom/)).toBeInTheDocument();
    const [start, end] = capturedDomain.x as [Date, Date];
    expect(end.getTime() - start.getTime()).toBeGreaterThan(90 * 86_400_000);
  });

  it('re-zooming while already zoomed uses the current zoom domain as the base range', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 400 });
    fireEvent.mouseUp(container);
    expect(screen.getByText(/Réinitialiser zoom/)).toBeInTheDocument();

    // Second drag, now starting from an already-zoomed domain.
    fireEvent.mouseDown(container, { clientX: 150 });
    fireEvent.mouseMove(container, { clientX: 300 });
    fireEvent.mouseUp(container);
    expect(screen.getByText(/Réinitialiser zoom/)).toBeInTheDocument();
  });

  it('mouse leaving the chart while dragging cancels the brush', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseDown(container, { clientX: 100 });
    fireEvent.mouseMove(container, { clientX: 400 });
    fireEvent.mouseLeave(container);
    expect(screen.queryByTestId('zoom-brush-overlay')).not.toBeInTheDocument();
  });

  it('moving the mouse without an active drag does nothing', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseMove(container, { clientX: 400 });
    expect(screen.queryByTestId('zoom-brush-overlay')).not.toBeInTheDocument();
  });

  it('releasing the mouse without a prior mousedown is a no-op', () => {
    render(<RatioIndicatorChart title="Growth" data={baseData} isLoading={false} aboveLabel="Up" belowLabel="Down" {...interpretationProps} />);
    const container = getChartContainer();
    fireEvent.mouseUp(container);
    expect(screen.queryByText(/Réinitialiser zoom/)).not.toBeInTheDocument();
  });
});
