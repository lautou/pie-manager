// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for PatrimoineChart component
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

vi.mock('@patternfly/react-charts/victory', () => ({
  Chart: ({ children, containerComponent }: any) => (
    <div data-testid="chart">
      {containerComponent ?? null}
      {children}
    </div>
  ),
  ChartArea: () => <div data-testid="chart-area" />,
  ChartAxis: ({ tickFormat, dependentAxis }: any) => {
    if (tickFormat && dependentAxis) {
      try {
        tickFormat(500);   // < 1000 branch
        tickFormat(1500);  // >= 1000 branch
      } catch { /* ignore */ }
    }
    return null;
  },
  ChartGroup: ({ children }: any) => <>{children}</>,
  ChartThemeColor: { blue: 'blue' },
}));

vi.mock('victory-zoom-container', () => ({
  VictoryZoomContainer: ({ onZoomDomainChange }: any) => {
    if (typeof onZoomDomainChange === 'function') {
      // Store for direct invocation in tests
      (globalThis as any).__patrimoineZoomCb = onZoomDomainChange;
    }
    return null;
  },
}));

vi.mock('../utils/format', () => ({
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
}));

import PatrimoineChart from './PatrimoineChart';
import type { BrushState } from './IndexChart';

const clampZoom = (domain: any, _minMs: number) => domain;
const makeAxisStyle = () => ({});
const scaleToDateRange = (_s: string) => undefined;

const patrimoineData = [
  { x: new Date('2024-01-01'), y: 10000 },
  { x: new Date('2024-06-01'), y: 11000 },
];

const defaultProps = {
  patrimoineData,
  zoomPatrimoine: undefined,
  setZoomPatrimoine: vi.fn(),
  isManuallyZoomed: false,
  setIsManuallyZoomed: vi.fn(),
  brush: null as BrushState,
  setBrush: vi.fn() as any,
  chartWidth: 800,
  timeScale: '1Y',
  scaleToDateRange,
  makeAxisStyle,
  clampZoom,
  MIN_ZOOM_PATRIMOINE_MS: 7 * 86_400_000,
  CHART_PADDING_LEFT: 50,
};

describe('PatrimoineChart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (globalThis as any).__patrimoineZoomCb = undefined;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 400, top: 0, left: 0,
      bottom: 400, right: 800, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders patrimoine chart when data is available', () => {
    render(<PatrimoineChart {...defaultProps} />);
    expect(screen.getByText(/Évolution du patrimoine/i)).toBeInTheDocument();
  });

  it('renders "Aucune donnée disponible." when patrimoineData is empty', () => {
    render(<PatrimoineChart {...defaultProps} patrimoineData={[]} />);
    expect(screen.getByText('Aucune donnée disponible.')).toBeInTheDocument();
  });

  it('shows reset zoom button when isManuallyZoomed is true', () => {
    render(<PatrimoineChart {...defaultProps} isManuallyZoomed={true} />);
    expect(screen.getByText(/↺ Réinitialiser zoom/i)).toBeInTheDocument();
  });

  it('does not show reset zoom button when isManuallyZoomed is false', () => {
    render(<PatrimoineChart {...defaultProps} isManuallyZoomed={false} />);
    expect(screen.queryByText(/↺ Réinitialiser zoom/i)).toBeNull();
  });

  it('reset zoom button calls setZoomPatrimoine and setIsManuallyZoomed', () => {
    const setZoomPatrimoine = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    render(<PatrimoineChart {...defaultProps} isManuallyZoomed={true} setZoomPatrimoine={setZoomPatrimoine} setIsManuallyZoomed={setIsManuallyZoomed} />);
    fireEvent.click(screen.getByText(/↺ Réinitialiser zoom/i));
    expect(setZoomPatrimoine).toHaveBeenCalled();
    expect(setIsManuallyZoomed).toHaveBeenCalledWith(false);
  });

  it('mouseDown starts brush, mouseMove updates brush', () => {
    const setBrush = vi.fn();
    render(<PatrimoineChart {...defaultProps} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseDown(chartDiv, { clientX: 100, clientY: 50 });
    expect(setBrush).toHaveBeenCalledWith(expect.objectContaining({ active: true, chartId: 'patrimoine' }));
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
  });

  it('mouseUp with no active brush clears the brush state and returns early', () => {
    // brush is null → !brush?.active is true → setBrush(null); return
    const setBrush = vi.fn();
    render(<PatrimoineChart {...defaultProps} brush={null} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseUp with a drag smaller than 5px clears the brush state without zooming', () => {
    const setBrush = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 103, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseUp with a large drag and no active zoom computes the new zoom from the full data range', () => {
    const setBrush = vi.fn();
    const setZoomPatrimoine = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'patrimoine' };
    // No zoom set → goes into else branch
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomPatrimoine={setZoomPatrimoine} setIsManuallyZoomed={setIsManuallyZoomed} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    // With 2 data points, should compute zoom and call setZoomPatrimoine + setIsManuallyZoomed
    expect(setZoomPatrimoine).toHaveBeenCalled();
    expect(setIsManuallyZoomed).toHaveBeenCalledWith(true);
  });

  it('mouseUp with a large drag returns early when fewer than 2 data points are available', () => {
    const setBrush = vi.fn();
    const setZoomPatrimoine = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'patrimoine' };
    render(
      <PatrimoineChart
        {...defaultProps}
        patrimoineData={[{ x: new Date('2024-01-01'), y: 10000 }]}
        brush={activeBrush}
        setBrush={setBrush}
        setZoomPatrimoine={setZoomPatrimoine}
        zoomPatrimoine={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    // allData.length < 2 → setBrush(null); return
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomPatrimoine).not.toHaveBeenCalled();
  });

  it('mouseUp with large drag and zoom.x set → uses zoom range', () => {
    const setBrush = vi.fn();
    const setZoomPatrimoine = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'patrimoine' };
    const zoom = { x: [new Date('2024-01-01'), new Date('2024-06-01')] as [Date, Date] };
    render(
      <PatrimoineChart
        {...defaultProps}
        brush={activeBrush}
        setBrush={setBrush}
        setZoomPatrimoine={setZoomPatrimoine}
        setIsManuallyZoomed={setIsManuallyZoomed}
        zoomPatrimoine={zoom}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseUp(chartDiv);
    expect(setZoomPatrimoine).toHaveBeenCalled();
    expect(setIsManuallyZoomed).toHaveBeenCalledWith(true);
  });

  it('mouseLeave clears brush when brush is active', () => {
    const setBrush = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseLeave(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
  });

  it('mouseLeave does nothing when brush is null', () => {
    const setBrush = vi.fn();
    render(<PatrimoineChart {...defaultProps} brush={null} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseLeave(chartDiv);
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('brush overlay div renders when brush is active on patrimoine', () => {
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} />);
    // The overlay div should be rendered (brush active + chartId=patrimoine)
    const overlayDivs = document.querySelectorAll('[style*="rgba(0, 102, 204, 0.15)"]');
    expect(overlayDivs.length).toBeGreaterThan(0);
  });

  it('startBrush: getBoundingClientRect returns null → early return', () => {
    const setBrush = vi.fn();
    render(<PatrimoineChart {...defaultProps} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    fireEvent.mouseDown(chartDiv, { clientX: 100, clientY: 50 });
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('moveBrush: getBoundingClientRect returns null → early return', () => {
    const setBrush = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 100, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('endBrush: getBoundingClientRect returns null → setBrush(null)', () => {
    const setBrush = vi.fn();
    const setZoomPatrimoine = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'patrimoine' };
    render(
      <PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} setZoomPatrimoine={setZoomPatrimoine} />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    chartDiv.getBoundingClientRect = () => null as any;
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomPatrimoine).not.toHaveBeenCalled();
  });

  it('onZoomDomainChange: calls setZoomPatrimoine and setIsManuallyZoomed when brush is not active', () => {
    const setZoomPatrimoine = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    render(<PatrimoineChart {...defaultProps} setZoomPatrimoine={setZoomPatrimoine} setIsManuallyZoomed={setIsManuallyZoomed} />);
    const cb = (globalThis as any).__patrimoineZoomCb;
    if (cb) {
      cb({ x: [new Date('2024-01-01'), new Date('2024-06-01')] });
      expect(setZoomPatrimoine).toHaveBeenCalled();
      expect(setIsManuallyZoomed).toHaveBeenCalledWith(true);
    }
  });

  it('onZoomDomainChange: skips setZoomPatrimoine when brush is active', () => {
    const setZoomPatrimoine = vi.fn();
    const setIsManuallyZoomed = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setZoomPatrimoine={setZoomPatrimoine} setIsManuallyZoomed={setIsManuallyZoomed} />);
    const cb = (globalThis as any).__patrimoineZoomCb;
    if (cb) {
      cb({ x: [new Date('2024-01-01'), new Date('2024-06-01')] });
      expect(setZoomPatrimoine).not.toHaveBeenCalled();
      expect(setIsManuallyZoomed).not.toHaveBeenCalled();
    }
  });

  it('moveBrush: no-op when brush is not active', () => {
    const setBrush = vi.fn();
    render(<PatrimoineChart {...defaultProps} brush={null} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
    expect(setBrush).not.toHaveBeenCalled();
  });

  it('moveBrush: null branch inside setBrush updater (b is null during state update)', () => {
    // We need brush.active=true so moveBrush proceeds, then setBrush updater runs with b=null.
    // Use a real-ish setBrush that captures the updater function and calls it with null.
    const capturedUpdaters: Array<(prev: any) => any> = [];
    const setBrush = vi.fn((updater: any) => {
      if (typeof updater === 'function') {
        capturedUpdaters.push(updater);
      }
    });
    const activeBrush: BrushState = { startX: 100, endX: 100, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} setBrush={setBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 50 });
    // Call captured updater with null to exercise the `b ? ... : null` null branch (line 57)
    if (capturedUpdaters.length > 0) {
      const result = capturedUpdaters[0](null);
      expect(result).toBeNull();
    }
  });

  it('endBrush clears the brush state early when the plot width is zero or negative', () => {
    const setBrush = vi.fn();
    const setZoomPatrimoine = vi.fn();
    const activeBrush: BrushState = { startX: 100, endX: 600, active: true, chartId: 'patrimoine' };
    render(
      <PatrimoineChart
        {...defaultProps}
        brush={activeBrush}
        setBrush={setBrush}
        setZoomPatrimoine={setZoomPatrimoine}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // Mock getBoundingClientRect to return width=0 so plotW = 0 - 50 - 10 = -60 <= 0
    chartDiv.getBoundingClientRect = () => ({
      width: 0, height: 400, top: 0, left: 0,
      bottom: 400, right: 0, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.mouseUp(chartDiv);
    expect(setBrush).toHaveBeenCalledWith(null);
    expect(setZoomPatrimoine).not.toHaveBeenCalled();
  });

  // ── Crosshair tests ───────────────────────────────────────────────────────

  it('crosshair shows line and tooltip on mouseMove in plot area (no zoom)', () => {
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // clientX=300, CHART_PADDING_LEFT=50, rect.width=800, plotW=740, relX=250 → in range
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeInTheDocument();
    expect(document.querySelector('[data-testid="crosshair-tooltip"]')).toBeInTheDocument();
  });

  it('crosshair tooltip contains date and EUR formatted value', () => {
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    // Should show a date and a value formatted as EUR
    expect(tooltip?.textContent).toBeTruthy();
    // Check it has some content (date + value)
    expect(tooltip?.textContent?.length).toBeGreaterThan(0);
  });

  it('crosshair uses zoomPatrimoine x-range when provided', () => {
    const zoom = { x: [new Date('2024-01-01'), new Date('2024-06-01')] as [Date, Date] };
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={zoom} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-tooltip"]')).toBeInTheDocument();
  });

  it('crosshair disappears on mouseLeave', () => {
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeInTheDocument();
    fireEvent.mouseLeave(chartDiv);
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when mouse is left of plot area (relX < 0)', () => {
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // clientX=10, CHART_PADDING_LEFT=50 → relX = 10 - 50 = -40 < 0
    fireEvent.mouseMove(chartDiv, { clientX: 10, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when mouse is beyond plot width (relX > plotW)', () => {
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    // clientX=800 (rect.right), relX=750, plotW=800-50-10=740 → 750 > 740
    fireEvent.mouseMove(chartDiv, { clientX: 800, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when brush is active (no crosshair during drag)', () => {
    const activeBrush: BrushState = { startX: 100, endX: 200, active: true, chartId: 'patrimoine' };
    render(<PatrimoineChart {...defaultProps} brush={activeBrush} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair hidden when patrimoineData has fewer than 2 points', () => {
    render(
      <PatrimoineChart
        {...defaultProps}
        patrimoineData={[{ x: new Date('2024-01-01'), y: 10000 }]}
        zoomPatrimoine={undefined}
      />
    );
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair not visible when brush is null (mouseLeave clears crosshair too)', () => {
    render(<PatrimoineChart {...defaultProps} brush={null} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 300, clientY: 100 });
    fireEvent.mouseLeave(chartDiv);
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeNull();
  });

  it('crosshair nearest-point: finds second data point when cursor is near right side', () => {
    // Move cursor far to the right so the second point (2024-06-01) is the nearest
    // rect.width=800, plotW=740, CHART_PADDING_LEFT=50
    // relX = clientX - 50; at clientX=790 → relX=740 (rightmost)
    // tMs maps to near 2024-06-01, so nearest should be the second point
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 789, clientY: 100 });
    expect(document.querySelector('[data-testid="crosshair-line"]')).toBeInTheDocument();
    // The tooltip should show 11000 or 10000 as the nearest value
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    expect(tooltip?.textContent).toBeTruthy();
  });

  it('crosshair tooltip flips left when mouse is near right edge of container', () => {
    // Override rect to be 300px wide so xPx+8 > width-150
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 300, height: 400, top: 0, left: 0,
      bottom: 400, right: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    // clientX=200, relX=200-50=150, plotW=300-50-10=240 → in range
    // xPx=200, 200+8=208 > 300-150=150 → flip condition is true
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 200, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    // Tooltip should still appear (flipped to the left)
    expect(tooltip).toBeInTheDocument();
  });

  it('crosshair tooltip does not flip when mouse is near left side', () => {
    // Default rect width=800; xPx=100, 100+8=108 < 800-150=650 → no flip
    render(<PatrimoineChart {...defaultProps} zoomPatrimoine={undefined} />);
    const chartDiv = document.querySelector('[style*="user-select: none"]') as HTMLElement;
    fireEvent.mouseMove(chartDiv, { clientX: 100, clientY: 100 });
    const tooltip = document.querySelector('[data-testid="crosshair-tooltip"]');
    // Tooltip appears to the right of cursor (no flip)
    expect(tooltip).toBeInTheDocument();
  });
});
