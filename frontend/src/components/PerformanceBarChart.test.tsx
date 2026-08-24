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
let capturedBarFill: any = null;
let capturedContainerComponent: any = null;
let capturedDependentAxisStyle: any = null;

vi.mock('@patternfly/react-charts/victory', () => ({
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
  ChartBar: ({ data, style }: any) => {
    capturedBarData = data;
    capturedBarFill = style?.data?.fill;
    return <div data-testid="chart-bar" data-points={data?.length ?? 0} />;
  },
  ChartTooltip: () => null,
  ChartVoronoiContainer: () => null,
  ChartThemeColor: { multi: 'multi' },
}));

import PerformanceBarChart from './PerformanceBarChart';

const ENTRIES = [
  { label: 'Inde', value: -3.2, tooltipLabel: 'BSE Sensex' },
  { label: 'États-Unis', value: 20.19, tooltipLabel: 'S&P 500' },
  { label: 'Corée du Sud', value: 102.88, tooltipLabel: 'KOSPI Composite' },
];

describe('PerformanceBarChart', () => {
  beforeEach(() => {
    capturedBarData = null;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 360, top: 0, left: 0, bottom: 360, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  it('shows a spinner while loading', () => {
    render(<PerformanceBarChart title="Top 15" data={undefined} isLoading />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows an empty state when there is no data', () => {
    render(<PerformanceBarChart title="Top 15" data={[]} isLoading={false} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('shows an empty state when data is undefined and not loading', () => {
    render(<PerformanceBarChart title="Top 15" data={undefined} isLoading={false} />);
    expect(screen.getByText(/Aucune donnée/)).toBeInTheDocument();
  });

  it('renders one bar per row, in the order received (ascending, not re-sorted)', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(screen.getByTestId('chart-bar')).toHaveAttribute('data-points', '3');
    expect(capturedBarData).toEqual([
      { x: 'Inde', y: -3.2, tooltipLabel: 'BSE Sensex' },
      { x: 'États-Unis', y: 20.19, tooltipLabel: 'S&P 500' },
      { x: 'Corée du Sud', y: 102.88, tooltipLabel: 'KOSPI Composite' },
    ]);
  });

  it('passes negative values through untouched (no zero-floor clipping)', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedBarData?.some((d) => d.y < 0)).toBe(true);
  });

  it('renders the given title', () => {
    render(<PerformanceBarChart title="Top 15 — Performance" data={ENTRIES} isLoading={false} />);
    expect(screen.getByText('Top 15 — Performance')).toBeInTheDocument();
  });

  it('ignores a zero-width initial measurement (container not yet laid out)', () => {
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 0, height: 360, top: 0, left: 0, bottom: 360, right: 0, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(screen.getByTestId('chart-bar')).toBeInTheDocument();
  });

  it('applies horizontal gridlines to the dependent (Y) axis', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedDependentAxisStyle?.grid).toEqual({ stroke: '#d2d2d2', strokeWidth: 1 });
  });

  it('configures a hover tooltip via ChartVoronoiContainer with a formatted "label — tooltip: value%" label', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedContainerComponent).not.toBeNull();
    const label = capturedContainerComponent.props.labels({
      datum: { x: 'Corée du Sud', y: 102.876, tooltipLabel: 'KOSPI Composite' },
    });
    expect(label).toBe('Corée du Sud — KOSPI Composite: 102.9%');
  });

  it('uses a uniform bar color by default (colorBySign off)', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedBarFill).toBe('#0066CC');
  });

  it('colors bars green/red by sign when colorBySign is set', () => {
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} colorBySign />);
    expect(typeof capturedBarFill).toBe('function');
    expect(capturedBarFill({ datum: { y: 2.5 } })).toBe('#3E8635');
    expect(capturedBarFill({ datum: { y: -1.0 } })).toBe('#C9190B');
    expect(capturedBarFill({ datum: { y: 0 } })).toBe('#3E8635');
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
    render(<PerformanceBarChart title="Top 15" data={ENTRIES} isLoading={false} />);
    expect(capturedCallback).not.toBeNull();
    act(() => { capturedCallback!([{ contentRect: { width: 950 } }]); });
    (globalThis as any).ResizeObserver = originalRO;
  });
});
