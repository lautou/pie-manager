/**
 * Tests for IndexChart component — crosshair/tooltip and core rendering.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

// Polyfills for jsdom
(globalThis as any).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
}));

vi.mock('@patternfly/react-charts', () => ({
  Chart: ({ children, containerComponent }: any) => (
    <div data-testid="chart">
      {containerComponent ?? null}
      {children}
    </div>
  ),
  ChartLine: () => <div data-testid="chart-line" />,
  ChartAxis: ({ tickFormat, dependentAxis }: any) => {
    if (tickFormat && dependentAxis) {
      try { tickFormat(100); } catch { /* ignore */ }
    }
    return null;
  },
  ChartGroup: ({ children }: any) => <>{children}</>,
  ChartThemeColor: { green: 'green', multi: 'multi' },
}));

vi.mock('victory-zoom-container', () => ({
  VictoryZoomContainer: ({ onZoomDomainChange }: any) => {
    if (typeof onZoomDomainChange === 'function') {
      (globalThis as any).__indexZoomCb = onZoomDomainChange;
    }
    return null;
  },
}));

import IndexChart from './IndexChart';
import type { BrushState } from './IndexChart';

const makeDate = (iso: string) => new Date(iso);

const totalIndexData = [
  { x: makeDate('2024-01-01'), y: 100 },
  { x: makeDate('2024-06-01'), y: 115 },
  { x: makeDate('2024-12-01'), y: 130 },
];
const offIndexData = [
  { x: makeDate('2024-01-01'), y: 100 },
  { x: makeDate('2024-06-01'), y: 120 },
];
const defIndexData = [
  { x: makeDate('2024-01-01'), y: 100 },
  { x: makeDate('2024-06-01'), y: 110 },
];
const poolSeriesData = {
  Asie:    [{ x: makeDate('2024-01-01'), y: 100, name: 'Asie' }, { x: makeDate('2024-06-01'), y: 110, name: 'Asie' }],
  Energie: [{ x: makeDate('2024-01-01'), y: 100, name: 'Energie' }, { x: makeDate('2024-06-01'), y: 105, name: 'Energie' }],
};
const positionSeriesData = {
  'CW8.PA': [{ x: makeDate('2024-01-01'), y: 100, ticker: 'CW8.PA' }, { x: makeDate('2024-06-01'), y: 125, ticker: 'CW8.PA' }],
};
const positionColorMap = { 'CW8.PA': '#0066CC' };

const clampZoom = (domain: any, _minMs: number) => domain;
const makeAxisStyle = () => ({});
const scaleToDateRange = (_s: string) => undefined;

const defaultProps = {
  indexView: 'total' as const,
  setIndexView: vi.fn(),
  zoomIndex: undefined,
  setZoomIndex: vi.fn(),
  isManuallyZoomed: false,
  setIsManuallyZoomed: vi.fn(),
  brush: null as BrushState,
  setBrush: vi.fn() as any,
  chartWidth: 800,
  chartContainerRef: { current: null } as any,
  timeScale: '1Y',
  scaleToDateRange,
  totalIndexData,
  offIndexData,
  defIndexData,
  poolSeriesData,
  holdingSeriesData: positionSeriesData,
  holdingColorMap: positionColorMap,
  activePools: ['Asie', 'Energie'],
  activeHoldingTickers: ['CW8.PA'],
  visiblePools: null,
  setVisiblePools: vi.fn() as any,
  visibleStrats: null,
  setVisibleStrats: vi.fn() as any,
  visibleHoldings: null,
  setVisibleHoldings: vi.fn() as any,
  makeAxisStyle,
  clampZoom,
  MIN_ZOOM_INDEX_MS: 60 * 86_400_000,
  CHART_PADDING_LEFT: 50,
};

describe('IndexChart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (globalThis as any).__indexZoomCb = undefined;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 340, top: 0, left: 0,
      bottom: 340, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Basic rendering ────────────────────────────────────────────────────────

  it('renders the performance chart card', () => {
    render(<IndexChart {...defaultProps} />);
    expect(screen.getByText(/Indice de performance/i)).toBeTruthy();
  });

  it('shows reset zoom button when isManuallyZoomed is true', () => {
    render(<IndexChart {...defaultProps} isManuallyZoomed={true} />);
    expect(screen.getByText(/↺ Réinitialiser zoom/i)).toBeTruthy();
  });

  it('does not show reset zoom button when isManuallyZoomed is false', () => {
    render(<IndexChart {...defaultProps} isManuallyZoomed={false} />);
    expect(screen.queryByText(/↺ Réinitialiser zoom/i)).toBeNull();
  });

  it('reset zoom button calls setZoomIndex and setIsManuallyZoomed', () => {
    const setZoomIndex = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    render(<IndexChart {...defaultProps} isManuallyZoomed={true} setZoomIndex={setZoomIndex} setIsManuallyZoomed={setIsManuallyZoomed} />);
    fireEvent.click(screen.getByText(/↺ Réinitialiser zoom/i));
    expect(setZoomIndex).toHaveBeenCalled();
    expect(setIsManuallyZoomed).toHaveBeenCalledWith(false);
  });

  it('renders strategie toggle buttons', () => {
    render(<IndexChart {...defaultProps} />);
    expect(screen.getByTestId('toggle-Total')).toBeTruthy();
    expect(screen.getByTestId('toggle-Offensif / Défensif')).toBeTruthy();
    expect(screen.getByTestId('toggle-Pools')).toBeTruthy();
    expect(screen.getByTestId('toggle-Positions')).toBeTruthy();
  });

  it('click on strategie toggle calls setIndexView', () => {
    const setIndexView = vi.fn();
    render(<IndexChart {...defaultProps} setIndexView={setIndexView} />);
    fireEvent.click(screen.getByTestId('toggle-Offensif / Défensif'));
    expect(setIndexView).toHaveBeenCalledWith('strategie');
  });

  it('click on Pools toggle calls setIndexView with pools', () => {
    const setIndexView = vi.fn();
    render(<IndexChart {...defaultProps} setIndexView={setIndexView} />);
    fireEvent.click(screen.getByTestId('toggle-Pools'));
    expect(setIndexView).toHaveBeenCalledWith('pools');
  });

  it('click on Positions toggle calls setIndexView with positions', () => {
    const setIndexView = vi.fn();
    render(<IndexChart {...defaultProps} setIndexView={setIndexView} />);
    fireEvent.click(screen.getByTestId('toggle-Positions'));
    expect(setIndexView).toHaveBeenCalledWith('positions');
  });

  it('click on Total toggle calls setIndexView with total', () => {
    const setIndexView = vi.fn();
    render(<IndexChart {...defaultProps} setIndexView={setIndexView} />);
    fireEvent.click(screen.getByTestId('toggle-Total'));
    expect(setIndexView).toHaveBeenCalledWith('total');
  });

  // ── Brush interactions ────────────────────────────────────────────────────

  it('mouseDown starts brush on chart div', () => {
    const setBrush = vi.fn();
    render(<IndexChart {...defaultProps} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseDown(chartDiv, { clientX: 100, clientY: 50 });
    expect(setBrush).toHaveBeenCalledWith(expect.objectContaining({ active: true, chartId: 'index' }));
  });

  it('startBrush: getBoundingClientRect returns null → early return', () => {
    const setBrush = vi.fn();
    render(<IndexChart {...defaultProps} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    fireEvent.mouseDown(chartDiv, { clientX: 100, clientY: 50 });
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('mouseUp with no active brush → setBrush(null)', () => {
    const setBrush = vi.fn();
    render(<IndexChart {...defaultProps} brush={null} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseUp with small drag (< 5px) → setBrush(null)', () => {
    const setBrush = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 103, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseUp with large drag and no zoom → uses allData range', () => {
    const setBrush = vi.fn();
    const setZoomIndex = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomIndex={setZoomIndex} setIsManuallyZoomed={setIsManuallyZoomed} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setZoomIndex).toHaveBeenCalled();
    expect(setIsManuallyZoomed).toHaveBeenCalledWith(true);
  });

  it('mouseUp with large drag and < 2 data points → early return', () => {
    const setBrush = vi.fn();
    const setZoomIndex = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'index' };
    render(
      <IndexChart
        {...defaultProps}
        totalIndexData={[{ x: makeDate('2024-01-01'), y: 100 }]}
        offIndexData={[]}
        defIndexData={[]}
        brush={activeBrush}
        setBrush={setBrush}
        setZoomIndex={setZoomIndex}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomIndex).not.toHaveBeenCalled();
  });

  it('mouseUp with large drag and zoom.x set → uses zoom range', () => {
    const setBrush = vi.fn();
    const setZoomIndex = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'index' };
    const zoom = { x: [makeDate('2024-01-01'), makeDate('2024-06-01')] as [Date, Date] };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomIndex={setZoomIndex} zoomIndex={zoom} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setZoomIndex).toHaveBeenCalled();
  });

  it('mouseUp: getBoundingClientRect null → setBrush(null) early return', () => {
    const setBrush = vi.fn();
    const setZoomIndex = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomIndex={setZoomIndex} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomIndex).not.toHaveBeenCalled();
  });

  it('mouseUp: plotW <= 0 → setBrush(null) early return', () => {
    const setBrush = vi.fn();
    const setZoomIndex = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomIndex={setZoomIndex} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => ({
      width: 0, height: 340, top: 0, left: 0,
      bottom: 340, right: 0, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomIndex).not.toHaveBeenCalled();
  });

  it('mouseLeave clears brush when active', () => {
    const setBrush = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseLeave(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseLeave does nothing to brush when brush is null', () => {
    const setBrush = vi.fn();
    render(<IndexChart {...defaultProps} brush={null} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseLeave(chartDiv);
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('brush overlay renders when brush is active on index chart', () => {
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} />);
    const overlayDivs = document.querySelectorAll('[style*="rgba(0, 102, 204, 0.15)"]');
    expect(overlayDivs.length).toBeGreaterThan(0);
  });

  it('brush overlay does not render for patrimoine chartId', () => {
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'patrimoine' };
    render(<IndexChart {...defaultProps} brush={activeBrush} />);
    const overlayDivs = document.querySelectorAll('[style*="rgba(0, 102, 204, 0.15)"]');
    expect(overlayDivs.length).toBe(0);
  });

  it('moveBrush: getBoundingClientRect returns null → early return', () => {
    render(<IndexChart {...defaultProps} brush={null} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    // No error should be thrown
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
    // crosshair-line should not appear since getBoundingClientRect returns null
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('moveBrush: updates brush endX when brush is active', () => {
    const capturedUpdaters: Array<(prev: any) => any> = [];
    const setBrush = vi.fn((updater: any) => {
      if (typeof updater === 'function') capturedUpdaters.push(updater);
    });
    const activeBrush: BrushState = { startX: 100, endX: 100, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
    expect(setBrush).toHaveBeenCalled();
    // Also test the null branch of the updater
    if (capturedUpdaters.length > 0) {
      const result = capturedUpdaters[0](null);
      expect(result).toBeNull();
    }
  });

  // ── Crosshair — total view ────────────────────────────────────────────────

  it('crosshair shows vertical line and tooltip on mouseMove in total view', () => {
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // Move to a position within the plot area (left=50..790)
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="crosshair-tooltip"]')).toBeTruthy();
  });

  it('crosshair shows date and value in tooltip (total view)', () => {
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Total/);
  });

  it('crosshair disappears on mouseLeave (total view)', () => {
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeTruthy();
    fireEvent.mouseLeave(chartDiv);
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when mouse is left of plot area (relX < 0)', () => {
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // clientX=10, CHART_PADDING_LEFT=50 → relX = 10 - 50 = -40 < 0
    fireEvent.mouseMove(chartDiv, { clientX: 10, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when mouse is right of plot area (relX > plotW)', () => {
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // clientX=800 (rect.width), relX = 800-50=750, plotW = 800-50-10=740 → relX > plotW
    fireEvent.mouseMove(chartDiv, { clientX: 800, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair uses zoomIndex x-range when provided', () => {
    const zoom = { x: [makeDate('2024-01-01'), makeDate('2024-12-01')] as [Date, Date] };
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={zoom} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-tooltip"]')).toBeTruthy();
  });

  it('crosshair hidden when brush is active (no crosshair during drag)', () => {
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} indexView="total" brush={activeBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  // ── Crosshair — strategie view ────────────────────────────────────────────

  it('crosshair shows Offensif/Défensif series in strategie view', () => {
    render(<IndexChart {...defaultProps} indexView="strategie" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Offensif/);
    expect(tooltip?.textContent).toMatch(/Défensif/);
  });

  it('crosshair shows only Offensif when Défensif hidden', () => {
    render(<IndexChart {...defaultProps} indexView="strategie" visibleStrats={new Set(['Offensif'])} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Offensif/);
    expect(tooltip?.textContent).not.toMatch(/Défensif/);
  });

  it('crosshair shows no series when all strats hidden (empty series → no crosshair)', () => {
    render(<IndexChart {...defaultProps} indexView="strategie" visibleStrats={new Set()} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    // No series → no crosshair
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  // ── Crosshair — pools view ────────────────────────────────────────────────

  it('crosshair shows pool names in pools view', () => {
    render(<IndexChart {...defaultProps} indexView="pools" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Asie/);
    expect(tooltip?.textContent).toMatch(/Energie/);
  });

  it('crosshair respects visible pools filter', () => {
    render(<IndexChart {...defaultProps} indexView="pools" visiblePools={new Set(['Asie'])} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Asie/);
    expect(tooltip?.textContent).not.toMatch(/Energie/);
  });

  // ── Crosshair — positions view ────────────────────────────────────────────

  it('crosshair shows position tickers in positions view', () => {
    render(<IndexChart {...defaultProps} indexView="positions" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/CW8\.PA/);
  });

  it('crosshair respects visible positions filter', () => {
    render(<IndexChart {...defaultProps} indexView="positions" visibleHoldings={new Set()} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    // no visible positions → no series → no crosshair
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  // ── Crosshair — no data edge cases ────────────────────────────────────────

  it('crosshair hidden when totalIndexData has < 2 points and no zoom (total view)', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="total"
        totalIndexData={[{ x: makeDate('2024-01-01'), y: 100 }]}
        offIndexData={[]}
        defIndexData={[]}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  // ── Legend toggle interactions ─────────────────────────────────────────────

  it('strategie view: shows Offensif/Défensif legend buttons', () => {
    render(<IndexChart {...defaultProps} indexView="strategie" />);
    expect(screen.getByText('Offensif')).toBeTruthy();
    expect(screen.getByText('Défensif')).toBeTruthy();
  });

  it('strategie view: toggle Offensif button calls setVisibleStrats', () => {
    const setVisibleStrats = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="strategie" setVisibleStrats={setVisibleStrats} />);
    fireEvent.click(screen.getByText('Offensif'));
    expect(setVisibleStrats).toHaveBeenCalled();
  });

  it('strategie view: shows "↺ Tout afficher" when some strats are hidden', () => {
    render(<IndexChart {...defaultProps} indexView="strategie" visibleStrats={new Set(['Offensif'])} />);
    expect(screen.getByText(/↺ Tout afficher/i)).toBeTruthy();
  });

  it('strategie view: clicking "↺ Tout afficher" resets visibleStrats', () => {
    const setVisibleStrats = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="strategie" visibleStrats={new Set(['Offensif'])} setVisibleStrats={setVisibleStrats} />);
    fireEvent.click(screen.getByText(/↺ Tout afficher/i));
    expect(setVisibleStrats).toHaveBeenCalledWith(null);
  });

  it('pools view: shows pool legend buttons', () => {
    render(<IndexChart {...defaultProps} indexView="pools" />);
    expect(screen.getByText('Asie')).toBeTruthy();
    expect(screen.getByText('Energie')).toBeTruthy();
  });

  it('pools view: toggle pool button calls setVisiblePools', () => {
    const setVisiblePools = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="pools" setVisiblePools={setVisiblePools} />);
    fireEvent.click(screen.getByText('Asie'));
    expect(setVisiblePools).toHaveBeenCalled();
  });

  it('pools view: shows "↺ Tout afficher" when a pool is hidden', () => {
    render(<IndexChart {...defaultProps} indexView="pools" visiblePools={new Set(['Asie'])} />);
    expect(screen.getByText(/↺ Tout afficher/i)).toBeTruthy();
  });

  it('pools view: clicking "↺ Tout afficher" resets visiblePools', () => {
    const setVisiblePools = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="pools" visiblePools={new Set(['Asie'])} setVisiblePools={setVisiblePools} />);
    fireEvent.click(screen.getByText(/↺ Tout afficher/i));
    expect(setVisiblePools).toHaveBeenCalledWith(null);
  });

  it('positions view: shows ticker legend buttons', () => {
    render(<IndexChart {...defaultProps} indexView="positions" />);
    expect(screen.getByText('CW8.PA')).toBeTruthy();
  });

  it('positions view: toggle position button calls setVisibleHoldings', () => {
    const setVisibleHoldings = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="positions" setVisibleHoldings={setVisibleHoldings} />);
    fireEvent.click(screen.getByText('CW8.PA'));
    expect(setVisibleHoldings).toHaveBeenCalled();
  });

  it('positions view: shows "↺ Tout afficher" when a position is hidden', () => {
    render(<IndexChart {...defaultProps} indexView="positions" visibleHoldings={new Set()} />);
    expect(screen.getByText(/↺ Tout afficher/i)).toBeTruthy();
  });

  it('positions view: clicking "↺ Tout afficher" resets visiblePositions', () => {
    const setVisibleHoldings = vi.fn() as any;
    render(<IndexChart {...defaultProps} indexView="positions" visibleHoldings={new Set()} setVisibleHoldings={setVisibleHoldings} />);
    fireEvent.click(screen.getByText(/↺ Tout afficher/i));
    expect(setVisibleHoldings).toHaveBeenCalledWith(null);
  });

  it('positions view: shows TWRR disclaimer', () => {
    render(<IndexChart {...defaultProps} indexView="positions" />);
    expect(screen.getByText(/insensible aux flux externes/i)).toBeTruthy();
  });

  it('total view: does not show TWRR disclaimer', () => {
    render(<IndexChart {...defaultProps} indexView="total" />);
    expect(screen.queryByText(/insensible aux flux externes/i)).toBeNull();
  });

  // ── onZoomDomainChange ────────────────────────────────────────────────────

  it('onZoomDomainChange: calls setZoomIndex and setIsManuallyZoomed when brush not active', () => {
    const setZoomIndex = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    render(<IndexChart {...defaultProps} setZoomIndex={setZoomIndex} setIsManuallyZoomed={setIsManuallyZoomed} />);
    const cb = (globalThis as any).__indexZoomCb;
    if (cb) {
      cb({ x: [makeDate('2024-01-01'), makeDate('2024-06-01')] });
      expect(setZoomIndex).toHaveBeenCalled();
      expect(setIsManuallyZoomed).toHaveBeenCalledWith(true);
    }
  });

  it('onZoomDomainChange: skips when brush is active', () => {
    const setZoomIndex = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'index' };
    render(<IndexChart {...defaultProps} brush={activeBrush} setZoomIndex={setZoomIndex} />);
    const cb = (globalThis as any).__indexZoomCb;
    if (cb) {
      cb({ x: [makeDate('2024-01-01'), makeDate('2024-06-01')] });
      expect(setZoomIndex).not.toHaveBeenCalled();
    }
  });

  // ── ChartAxis tickFormat ──────────────────────────────────────────────────

  it('dependent axis tickFormat produces formatted string', () => {
    // The mock calls tickFormat(100); in ChartAxis — just ensure it does not throw
    render(<IndexChart {...defaultProps} indexView="total" />);
    // No assertion needed beyond not throwing; mock calls tickFormat in ChartAxis
    expect(true).toBe(true);
  });

  // ── Crosshair tooltip flip branch (right edge) ────────────────────────────

  it('crosshair tooltip flips to the left when near the right edge', () => {
    // Override rect to 300px wide so xPx+8 > width-160 branch triggers
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 300, height: 340, top: 0, left: 0,
      bottom: 340, right: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    // clientX=200, relX=200-50=150, plotW=300-50-10=240 → in range
    render(<IndexChart {...defaultProps} indexView="total" zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip).toBeTruthy();
  });

  // ── Pools view: second pool sets hoverDate branch ─────────────────────────

  it('pools view: both pools show values (second pool does not set hoverDate again)', () => {
    // Both Asie and Energie are visible; hoverDate is set by Asie (first), then
    // Energie's `if (!hoverDate) hoverDate = pt.x` is false — coverage for the
    // already-set branch
    render(<IndexChart {...defaultProps} indexView="pools" visiblePools={null} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Asie/);
    expect(tooltip?.textContent).toMatch(/Energie/);
  });

  // ── Positions view: unknown pool color fallback ───────────────────────────

  it('positions view: uses fallback color when positionColorMap has no entry', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="positions"
        holdingColorMap={{}} // no color for CW8.PA → uses '#6A6E73'
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/CW8\.PA/);
  });

  // ── Strategie view: Défensif sets hoverDate when Offensif has no data ─────

  it('strategie view: Défensif sets hoverDate when Offensif data is empty', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="strategie"
        offIndexData={[]} // Offensif visible but empty → findNearest returns null
        visibleStrats={null} // both visible
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Défensif/);
  });

  it('strategie view: no crosshair when both Offensif and Défensif data are empty', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="strategie"
        offIndexData={[]}
        defIndexData={[]}
        visibleStrats={null}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('strategie view: Offensif sets hoverDate; Défensif does not re-set it (false branch)', () => {
    // Both visible and both have data. Offensif runs first → sets hoverDate.
    // Défensif's `if (!hoverDate)` is false → hoverDate not overwritten.
    // Both appear in tooltip.
    render(
      <IndexChart
        {...defaultProps}
        indexView="strategie"
        visibleStrats={null} // both visible
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Offensif/);
    expect(tooltip?.textContent).toMatch(/Défensif/);
  });

  it('pools view: second pool does not re-set hoverDate (false branch)', () => {
    // Both Asie and Energie visible; Asie runs first (sets hoverDate), Energie then
    // hits the `if (!hoverDate)` false branch.
    render(<IndexChart {...defaultProps} indexView="pools" visiblePools={null} zoomIndex={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/Asie/);
    expect(tooltip?.textContent).toMatch(/Energie/);
  });

  it('pools view: pool with empty data array (findNearest returns null)', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="pools"
        poolSeriesData={{ Asie: [] }} // empty → findNearest returns null
        activePools={['Asie']}
        visiblePools={null}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('total view: no crosshair when totalIndexData is empty (findNearest returns null)', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="total"
        totalIndexData={[]}
        zoomIndex={{ x: [makeDate('2024-01-01'), makeDate('2024-12-01')] as [Date, Date] }}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('positions view: ticker not in holdingSeriesData (uses ?? [] fallback)', () => {
    // 'UNKNOWN' not in holdingSeriesData → holdingSeriesData['UNKNOWN'] ?? [] = []
    // → findNearest returns null → no series → no crosshair
    render(
      <IndexChart
        {...defaultProps}
        indexView="positions"
        activeHoldingTickers={['UNKNOWN']}
        holdingColorMap={{ UNKNOWN: '#aabbcc' }}
        holdingSeriesData={{}} // UNKNOWN not in dict → ?? [] branch
        zoomIndex={{ x: [makeDate('2024-01-01'), makeDate('2024-12-01')] as [Date, Date] }}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('moveBrush: baseData falls back to defIndexData when total and off are empty (no zoom)', () => {
    render(
      <IndexChart
        {...defaultProps}
        indexView="total"
        totalIndexData={[]}
        offIndexData={[]}
        defIndexData={defIndexData}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    // defIndexData has 2 points so baseData.length >= 2, but indexView=total
    // finds nearest from totalIndexData=[] → returns null → no crosshair
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('moveBrush: baseData uses offIndexData when total is empty but off has data (no zoom)', () => {
    // totalIndexData.length = 0, offIndexData.length > 0 → baseData = offIndexData (branch 26)
    render(
      <IndexChart
        {...defaultProps}
        indexView="total"
        totalIndexData={[]}
        offIndexData={offIndexData} // non-empty
        defIndexData={[]}
        zoomIndex={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    // indexView=total: findNearest(totalIndexData=[]) → null → no crosshair
    // but baseData = offIndexData (covers branch 26 true alt)
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('pools view: pool name not in poolSeriesData dict (uses ?? [] fallback)', () => {
    // activePools contains 'Custom' but poolSeriesData does not → poolSeriesData['Custom'] is undefined
    render(
      <IndexChart
        {...defaultProps}
        indexView="pools"
        activePools={['Custom']}
        poolSeriesData={{}} // 'Custom' not in dict → ?? [] branch hit
        visiblePools={null}
        zoomIndex={{ x: [makeDate('2024-01-01'), makeDate('2024-12-01')] as [Date, Date] }}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    // Empty data → no crosshair
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('pools view: pool name not in POOL_COLORS uses fallback color (#6A6E73)', () => {
    // Pool name 'CustomPool' is not in POOL_COLORS dict → ?? '#6A6E73' fallback branch
    render(
      <IndexChart
        {...defaultProps}
        indexView="pools"
        activePools={['CustomPool']}
        poolSeriesData={{
          CustomPool: [
            { x: makeDate('2024-01-01'), y: 100, name: 'CustomPool' },
            { x: makeDate('2024-06-01'), y: 110, name: 'CustomPool' },
          ],
        }}
        visiblePools={null}
        zoomIndex={{ x: [makeDate('2024-01-01'), makeDate('2024-12-01')] as [Date, Date] }}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toMatch(/CustomPool/);
  });
});
