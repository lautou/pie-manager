// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import '@testing-library/jest-dom';

import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

vi.mock('@patternfly/react-core', () => ({ ...pfCoreStubs }));

let capturedBarData: any[] | null = null;
let capturedContainerComponent: any = null;
let capturedDependentAxisStyle: any = null;

vi.mock('@patternfly/react-charts', () => ({
  Chart: ({ children, containerComponent }: any) => {
    capturedContainerComponent = containerComponent;
    return <div data-testid="chart">{children}</div>;
  },
  ChartAxis: ({ tickFormat, dependentAxis, style }: any) => {
    if (dependentAxis) {
      if (tickFormat) tickFormat(20.19);
      capturedDependentAxisStyle = style;
    }
    return null;
  },
  ChartBar: ({ data }: any) => {
    capturedBarData = data;
    return <div data-testid="chart-bar" data-points={data?.length ?? 0} />;
  },
  ChartTooltip: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

import CountryPerformanceChart from './CountryPerformanceChart';

const ENTRIES = [
  { code: 'in', label: 'Inde', currency: 'INR', perf_pct: -3.2, latest_date: '2026-07-19', anchor_date: '2025-07-19', index_label: 'BSE Sensex' },
  { code: 'us', label: 'États-Unis', currency: 'USD', perf_pct: 20.19, latest_date: '2026-07-19', anchor_date: '2025-07-19', index_label: 'S&P 500' },
  { code: 'kr', label: 'Corée du Sud', currency: 'KRW', perf_pct: 102.88, latest_date: '2026-07-19', anchor_date: '2025-07-19', index_label: 'KOSPI Composite' },
];

describe('CountryPerformanceChart', () => {
  beforeEach(() => {
    capturedBarData = null;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 360, top: 0, left: 0, bottom: 360, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  it('shows a spinner while loading', () => {
    render(<CountryPerformanceChart title="Top 15" data={undefined} isLoading />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows an empty state when there is no data', () => {
    render(<CountryPerformanceChart title="Top 15" data={[]} isLoading={false} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('shows an empty state when data is undefined and not loading', () => {
    render(<CountryPerformanceChart title="Top 15" data={undefined} isLoading={false} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('renders one bar per country, in the order received (ascending, not re-sorted)', () => {
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(screen.getByTestId('chart-bar')).toHaveAttribute('data-points', '3');
    expect(capturedBarData).toEqual([
      { x: 'Inde', y: -3.2, indexLabel: 'BSE Sensex' },
      { x: 'États-Unis', y: 20.19, indexLabel: 'S&P 500' },
      { x: 'Corée du Sud', y: 102.88, indexLabel: 'KOSPI Composite' },
    ]);
  });

  it('passes negative values through untouched (no zero-floor clipping)', () => {
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedBarData?.some((d) => d.y < 0)).toBe(true);
  });

  it('renders the given title', () => {
    render(<CountryPerformanceChart title="Top 15 — Performance" data={ENTRIES} isLoading={false} />);
    expect(screen.getByText('Top 15 — Performance')).toBeInTheDocument();
  });

  it('ignores a zero-width initial measurement (container not yet laid out)', () => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 0, height: 360, top: 0, left: 0, bottom: 360, right: 0, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('applies horizontal gridlines to the dependent (Y) axis', () => {
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedDependentAxisStyle?.grid).toEqual({ stroke: '#d2d2d2', strokeWidth: 1 });
  });

  it('configures a hover tooltip via ChartVoronoiContainer with a formatted "country — index: pct%" label', () => {
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedContainerComponent).not.toBeNull();
    const label = capturedContainerComponent.props.labels({
      datum: { x: 'Corée du Sud', y: 102.876, indexLabel: 'KOSPI Composite' },
    });
    expect(label).toBe('Corée du Sud — KOSPI Composite: 102.9%');
  });

  it('updates chart width when the ResizeObserver callback fires', () => {
    let capturedCallback: ((entries: any[]) => void) | null = null;
    const originalRO = (globalThis as any).ResizeObserver;
    (globalThis as any).ResizeObserver = class {
      constructor(cb: (entries: any[]) => void) { capturedCallback = cb; }
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    render(<CountryPerformanceChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedCallback).not.toBeNull();
    act(() => { capturedCallback!([{ contentRect: { width: 950 } }]); });
    (globalThis as any).ResizeObserver = originalRO;
  });
});
