import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle,
  EmptyState, EmptyStateBody,
  Label,
  Spinner,
} from '@patternfly/react-core';
import {
  Chart, ChartAxis, ChartGroup, ChartLegend, ChartLine, ChartThemeColor, ChartVoronoiContainer,
} from '@patternfly/react-charts';
import type { RatioIndicator } from '../types';

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

function clampZoom(domain: [Date, Date], minMs: number): [Date, Date] {
  const [s, e] = domain;
  const diff = e.getTime() - s.getTime();
  if (diff < minMs) {
    const center = (s.getTime() + e.getTime()) / 2;
    return [new Date(center - minMs / 2), new Date(center + minMs / 2)];
  }
  return domain;
}

export default function RatioIndicatorChart({
  title, data, isLoading, aboveLabel, belowLabel, interpretationAbove, interpretationBelow,
}: RatioIndicatorChartProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(900);
  const [zoomDomain, setZoomDomain] = useState<ZoomDomain>(undefined);
  const [isManuallyZoomed, setIsManuallyZoomed] = useState(false);
  const [brush, setBrush] = useState<Brush>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const initial = el.getBoundingClientRect().width;
    if (initial > 0) setChartWidth(Math.floor(initial));
    const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const hasData = !!data && data.dates.length > 0;
  const numeratorLabel = data?.numerator_label ?? data?.numerator_ticker ?? '';
  const denominatorLabel = data?.denominator_label ?? data?.denominator_ticker ?? '';
  const ratioLegendName = t('indicators.legendRatioLabel', { numerator: numeratorLabel, denominator: denominatorLabel });
  const movingAvgLegendName = t('indicators.movingAvgLabel', { years: data?.ma_years });
  const ratioSeries = hasData ? data.dates.map((d, i) => ({ x: new Date(d), y: data.ratio[i], name: ratioLegendName })) : [];
  const movingAvgSeries = hasData ? data.dates.map((d, i) => ({ x: new Date(d), y: data.moving_avg[i], name: movingAvgLegendName })) : [];

  const statusLabel = data?.status === 'above' ? aboveLabel : data?.status === 'below' ? belowLabel : null;
  const statusColor = data?.status === 'above' ? 'green' : 'red';
  const interpretation = data?.status === 'above' ? interpretationAbove : data?.status === 'below' ? interpretationBelow : null;

  // ── Brush-drag-to-zoom (mirrors IndexChart.tsx's characteristics) ──────────
  const startBrush = (e: React.MouseEvent) => {
    const rect = chartRef.current?.getBoundingClientRect();
    /* v8 ignore next -- @preserve */
    if (!rect) return;
    setBrush({ startX: e.clientX - rect.left, endX: e.clientX - rect.left, active: true });
  };

  const moveBrush = (e: React.MouseEvent) => {
    if (!brush?.active) return;
    const rect = chartRef.current?.getBoundingClientRect();
    /* v8 ignore next -- @preserve */
    if (!rect) return;
    setBrush({ ...brush, endX: e.clientX - rect.left });
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
    setZoomDomain(clampZoom([new Date(startMs), new Date(endMs)], MIN_ZOOM_MS));
    setIsManuallyZoomed(true);
    setBrush(null);
  };

  const resetZoom = () => {
    setZoomDomain(undefined);
    setIsManuallyZoomed(false);
  };

  // Full date when zoomed in tight (< 90 days), year otherwise — mirrors PerformancePage's
  // makeAxisStyle adaptive tick format.
  const zoomDays = zoomDomain ? (zoomDomain[1].getTime() - zoomDomain[0].getTime()) / 86_400_000 : Infinity;
  const xTickFormat = (d: Date) => {
    const dt = d instanceof Date ? d : new Date(d);
    if (zoomDays < 90) {
      return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
    }
    return dt.getFullYear().toString();
  };

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span>{title}</span>
          {statusLabel && <Label color={statusColor}>{statusLabel}</Label>}
          {isManuallyZoomed && (
            <button
              onClick={resetZoom}
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
            <div ref={containerRef} style={{ width: '100%', height: 320, position: 'relative' }}>
              <div
                ref={chartRef}
                style={{ width: '100%', height: '100%', userSelect: 'none' }}
                onMouseDown={startBrush}
                onMouseMove={moveBrush}
                onMouseUp={endBrush}
                onMouseLeave={() => setBrush(null)}
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
                <Chart
                  ariaDesc={title}
                  height={320}
                  width={chartWidth}
                  padding={{ bottom: 70, left: CHART_PADDING_LEFT, right: 20, top: 10 }}
                  scale={{ x: 'time', y: 'linear' }}
                  domain={zoomDomain ? { x: zoomDomain } : undefined}
                  themeColor={ChartThemeColor.multi}
                  containerComponent={
                    <ChartVoronoiContainer
                      labels={({ datum }: { datum: { x: Date; y: number; name: string } }) =>
                        `${datum.name}: ${datum.y.toFixed(1)}`
                      }
                      voronoiDimension="x"
                    />
                  }
                  legendData={[
                    { name: ratioLegendName, symbol: { fill: RATIO_COLOR } },
                    { name: movingAvgLegendName, symbol: { fill: MA_COLOR } },
                  ]}
                  legendPosition="bottom"
                  legendComponent={<ChartLegend />}
                >
                  <ChartAxis tickFormat={xTickFormat} />
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
