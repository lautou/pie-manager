import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle,
  EmptyState, EmptyStateBody,
  Label,
  Spinner,
} from '@patternfly/react-core';
import {
  Chart, ChartAxis, ChartGroup, ChartLegend, ChartLine, ChartThemeColor,
} from '@patternfly/react-charts';
import type { RatioIndicator } from '../types';
import { clampZoomRange, timeAxisStyle } from '../utils/chartZoom';
import ChartCrosshair, { type ChartCrosshairState } from './ChartCrosshair';

const RATIO_COLOR = '#0066CC';
const MA_COLOR = '#F0AB00';
const CHART_PADDING_LEFT = 60;
const MIN_ZOOM_MS = 30 * 86_400_000; // 30 days — a macro ratio chart doesn't need finer zoom

interface RatioIndicatorChartProps {
  title: string;
  data: RatioIndicator | undefined;
  isLoading: boolean;
  aboveLabel: string;
  belowLabel: string;
  interpretationAbove: string;
  interpretationBelow: string;
}

type ZoomDomain = [Date, Date] | undefined;
type Brush = { startX: number; endX: number; active: boolean } | null;

// Preset ranges — same set as PerformancePage's time-scale selector, for a consistent UX
// across every chart in the app that supports zooming.
const PERIODS = ['1M', '3M', '1Y', 'YTD', '5Y', '10Y', 'MAX'] as const;
type Period = typeof PERIODS[number];

function periodToDateRange(period: Period, end: Date): [Date, Date] | undefined {
  const start = new Date(end);
  switch (period) {
    case '1M': start.setMonth(start.getMonth() - 1); break;
    case '3M': start.setMonth(start.getMonth() - 3); break;
    case '1Y': start.setFullYear(start.getFullYear() - 1); break;
    case 'YTD': return [new Date(end.getFullYear(), 0, 1), end];
    case '5Y': start.setFullYear(start.getFullYear() - 5); break;
    case '10Y': start.setFullYear(start.getFullYear() - 10); break;
    case 'MAX': return undefined;
  }
  return [start, end];
}

export default function RatioIndicatorChart({
  title, data, isLoading, aboveLabel, belowLabel, interpretationAbove, interpretationBelow,
}: RatioIndicatorChartProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(900);
  const [zoomDomain, setZoomDomain] = useState<ZoomDomain>(undefined);
  const [activePeriod, setActivePeriod] = useState<Period | null>('MAX');
  const [brush, setBrush] = useState<Brush>(null);
  const [crosshair, setCrosshair] = useState<ChartCrosshairState>(null);

  const hasData = !!data && data.dates.length > 0;

  // `containerRef`'s div only mounts once loading finishes and data has arrived (see the
  // isLoading/!hasData branches below) — an empty dependency array here would run this effect
  // once on the FIRST render, while containerRef.current is still null, and never again. That
  // silently freezes chartWidth at its default forever: the chart still *looks* fine (Victory
  // scales its SVG to fill the container via CSS regardless of the width prop), but the pixel
  // math driving drag-to-zoom then maps mouse positions against the wrong plot width, producing
  // a zoomed range that's actually shifted/scaled from where the user dragged.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const initial = el.getBoundingClientRect().width;
    if (initial > 0) setChartWidth(Math.floor(initial));
    const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [isLoading, hasData]);

  const numeratorLabel = data?.numerator_label ?? data?.numerator_ticker ?? '';
  const denominatorLabel = data?.denominator_label ?? data?.denominator_ticker ?? '';
  const ratioLegendName = t('indicators.legendRatioLabel', { numerator: numeratorLabel, denominator: denominatorLabel });
  const movingAvgLegendName = t('indicators.movingAvgLabel', { years: data?.ma_years });
  // Short names for the hover crosshair — same convention as IndexChart's "Offensif"/
  // "Défensif" (no "(base 100)"/"(N ans)" qualifiers, which stay useful in the static legend
  // below the chart but only add clutter to a tooltip shown next to the cursor).
  const ratioShortName = `${numeratorLabel} / ${denominatorLabel}`;
  const movingAvgShortName = t('indicators.movingAvgShortLabel');
  const ratioSeries = hasData ? data.dates.map((d, i) => ({ x: new Date(d), y: data.ratio[i] })) : [];
  const movingAvgSeries = hasData ? data.dates.map((d, i) => ({ x: new Date(d), y: data.moving_avg[i] })) : [];

  const statusLabel = data?.status === 'above' ? aboveLabel : data?.status === 'below' ? belowLabel : null;
  const statusColor = data?.status === 'above' ? 'green' : 'red';
  const interpretation = data?.status === 'above' ? interpretationAbove : data?.status === 'below' ? interpretationBelow : null;

  // ── Brush-drag-to-zoom (mirrors IndexChart.tsx's characteristics) ──────────
  const startBrush = (e: React.MouseEvent) => {
    // Without this, native browser text-selection highlights every text node the drag passes
    // over (axis labels, legend) instead of just showing the brush rectangle below.
    // victory-zoom-container's onMouseDown does this unconditionally (even with allowPan/
    // allowZoom false) — IndexChart.tsx never needed it explicitly for exactly that reason.
    e.preventDefault();
    const rect = chartRef.current?.getBoundingClientRect();
    /* v8 ignore next -- @preserve */
    if (!rect) return;
    setBrush({ startX: e.clientX - rect.left, endX: e.clientX - rect.left, active: true });
  };

  const moveBrush = (e: React.MouseEvent) => {
    const rect = chartRef.current?.getBoundingClientRect();
    /* v8 ignore next -- @preserve */
    if (!rect) return;
    const xPx = e.clientX - rect.left;

    if (brush?.active) {
      setBrush({ ...brush, endX: xPx });
      return;
    }

    // Hover crosshair (only tracked while not dragging a brush) — mirrors IndexChart.tsx's
    // tooltip: nearest data point by date, one colored-bullet row per series.
    /* v8 ignore next -- @preserve */
    if (!hasData) { setCrosshair(null); return; }
    const plotW = rect.width - CHART_PADDING_LEFT - 20;
    const relX = xPx - CHART_PADDING_LEFT;
    if (relX < 0 || relX > plotW || plotW <= 0) {
      setCrosshair(null);
      return;
    }

    const [minT, maxT] = zoomDomain
      ? [zoomDomain[0].getTime(), zoomDomain[1].getTime()]
      : [new Date(data.dates[0]).getTime(), new Date(data.dates[data.dates.length - 1]).getTime()];
    const tMs = minT + (relX / plotW) * (maxT - minT);

    let nearestIdx = 0;
    let minDist = Infinity;
    data.dates.forEach((d, i) => {
      const dist = Math.abs(new Date(d).getTime() - tMs);
      if (dist < minDist) { minDist = dist; nearestIdx = i; }
    });

    setCrosshair({
      xPx,
      date: new Date(data.dates[nearestIdx]),
      series: [
        { name: ratioShortName, value: data.ratio[nearestIdx], color: RATIO_COLOR },
        { name: movingAvgShortName, value: data.moving_avg[nearestIdx], color: MA_COLOR },
      ],
      containerWidth: rect.width,
    });
  };

  const endBrush = () => {
    if (!brush?.active || Math.abs(brush.endX - brush.startX) < 5 || !hasData) {
      setBrush(null);
      return;
    }
    const rect = chartRef.current?.getBoundingClientRect();
    /* v8 ignore next -- @preserve */
    if (!rect) { setBrush(null); return; }
    const plotW = rect.width - CHART_PADDING_LEFT - 20;
    const leftX = Math.min(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    const rightX = Math.max(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    if (plotW <= 0) { setBrush(null); return; }

    const [minT, maxT] = zoomDomain
      ? [zoomDomain[0].getTime(), zoomDomain[1].getTime()]
      : [new Date(data!.dates[0]).getTime(), new Date(data!.dates[data!.dates.length - 1]).getTime()];
    const range = maxT - minT;
    const startMs = minT + (leftX / plotW) * range;
    const endMs = minT + (rightX / plotW) * range;
    setZoomDomain(clampZoomRange([new Date(startMs), new Date(endMs)], MIN_ZOOM_MS));
    setActivePeriod(null); // a manual drag rarely lands exactly on a preset range
    setBrush(null);
  };

  const applyPeriod = (period: Period) => {
    /* v8 ignore next -- @preserve */
    const latest = hasData ? new Date(data!.dates[data!.dates.length - 1]) : new Date();
    const range = periodToDateRange(period, latest);
    setZoomDomain(range && clampZoomRange(range, MIN_ZOOM_MS));
    setActivePeriod(period);
  };

  const axisStyle = timeAxisStyle(zoomDomain);

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span>{title}</span>
          {statusLabel && <Label color={statusColor}>{statusLabel}</Label>}
          {activePeriod === null && (
            <button
              onClick={() => applyPeriod('MAX')}
              style={{ fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 3, background: '#f5f5f5' }}
            >
              ↺ {t('common.resetZoom')}
            </button>
          )}
        </div>
      </CardTitle>
      <CardBody>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
            <Spinner size="md" aria-label={t('common.loading')} />
          </div>
        ) : !hasData ? (
          <EmptyState>
            <EmptyStateBody>{t('indicators.noData')}</EmptyStateBody>
          </EmptyState>
        ) : (
          <>
            <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
              {PERIODS.map((p) => (
                <button
                  key={p}
                  onClick={() => applyPeriod(p)}
                  aria-pressed={activePeriod === p}
                  style={{
                    padding: '3px 10px', cursor: 'pointer', borderRadius: 4, fontSize: '0.8rem',
                    border: activePeriod === p ? '2px solid #0066CC' : '1px solid #ccc',
                    background: activePeriod === p ? '#e8f0fe' : '#f5f5f5',
                    fontWeight: activePeriod === p ? 'bold' : 'normal',
                    color: activePeriod === p ? '#0066CC' : 'inherit',
                  }}
                >
                  {p}
                </button>
              ))}
            </div>
            <div ref={containerRef} style={{ width: '100%', height: 320, position: 'relative' }}>
              <div
                ref={chartRef}
                style={{ width: '100%', height: '100%', userSelect: 'none' }}
                onMouseDown={startBrush}
                onMouseMove={moveBrush}
                onMouseUp={endBrush}
                onMouseLeave={() => { setBrush(null); setCrosshair(null); }}
              >
                {brush?.active && (
                  <div data-testid="zoom-brush-overlay" style={{
                    position: 'absolute',
                    left: Math.min(brush.startX, brush.endX),
                    top: 0,
                    width: Math.abs(brush.endX - brush.startX),
                    height: '100%',
                    background: 'rgba(0, 102, 204, 0.15)',
                    border: '2px solid rgba(0, 102, 204, 0.6)',
                    borderRadius: 2,
                    pointerEvents: 'none',
                    zIndex: 10,
                  }} />
                )}
                <ChartCrosshair crosshair={brush?.active ? null : crosshair} />
                <Chart
                  ariaDesc={title}
                  height={320}
                  width={chartWidth}
                  padding={{ bottom: 70, left: CHART_PADDING_LEFT, right: 20, top: 10 }}
                  scale={{ x: 'time', y: 'linear' }}
                  domain={zoomDomain ? { x: zoomDomain } : undefined}
                  themeColor={ChartThemeColor.multi}
                  legendData={[
                    { name: ratioLegendName, symbol: { fill: RATIO_COLOR } },
                    { name: movingAvgLegendName, symbol: { fill: MA_COLOR } },
                  ]}
                  legendPosition="bottom"
                  legendComponent={<ChartLegend />}
                >
                  <ChartAxis {...axisStyle} />
                  <ChartAxis dependentAxis tickFormat={(y: number) => y.toFixed(0)} />
                  <ChartGroup>
                    <ChartLine data={ratioSeries} interpolation="monotoneX" style={{ data: { stroke: RATIO_COLOR } }} />
                    <ChartLine
                      data={movingAvgSeries}
                      interpolation="monotoneX"
                      style={{ data: { stroke: MA_COLOR, strokeDasharray: '4,4' } }}
                    />
                  </ChartGroup>
                </Chart>
              </div>
            </div>
            {interpretation && (
              <div style={{ fontSize: '0.85rem', color: 'var(--pf-v5-global--Color--200)', marginTop: '0.5rem', textAlign: 'center' }}>
                {interpretation}
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
