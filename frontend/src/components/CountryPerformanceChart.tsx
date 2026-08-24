// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle,
  EmptyState, EmptyStateBody,
  Spinner,
} from '@patternfly/react-core';
import {
	Chart,
	ChartAxis,
	ChartBar,
	ChartThemeColor,
	ChartTooltip,
	ChartVoronoiContainer
} from '@patternfly/react-charts/victory';
import type { CountryPerformanceEntry } from '../types';

const BAR_COLOR = '#0066CC';
const GRID_STYLE = { stroke: '#d2d2d2', strokeWidth: 1 };

interface CountryPerformanceChartProps {
  title: string;
  data: CountryPerformanceEntry[] | undefined;
  isLoading: boolean;
}

/**
 * Static ranked bar chart (Top N countries, trailing-1-year EUR-adjusted performance) —
 * deliberately NOT modeled on RatioIndicatorChart.tsx: this has a categorical x-axis (no
 * dates), a single snapshot per country (no time series to zoom/scrub), so none of that
 * component's drag-to-zoom/crosshair/period-selector machinery applies (YAGNI).
 *
 * The y-axis domain is left auto-computed from the data (no explicit `domain` prop) so a
 * negative-performance country renders its bar below the zero line instead of being
 * silently clipped by an assumed zero floor.
 */
export default function CountryPerformanceChart({ title, data, isLoading }: CountryPerformanceChartProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(900);

  const hasData = !!data && data.length > 0;

  // containerRef's div only mounts once loading finishes and data has arrived — see
  // RatioIndicatorChart.tsx's identical comment on why [isLoading, hasData] (not []) is
  // the correct dependency array here.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const initial = el.getBoundingClientRect().width;
    if (initial > 0) setChartWidth(Math.floor(initial));
    const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [isLoading, hasData]);

  // Rendered in the exact order the API returns (already ascending: worst on the left,
  // best on the right) — no client-side re-sort. indexLabel rides along on each datum
  // (not part of the x/y the bar itself is positioned by) so the tooltip can name the
  // underlying index without a separate lookup.
  const series = hasData
    ? data.map((d) => ({ x: d.label, y: d.perf_pct, indexLabel: d.index_label }))
    : [];

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>{title}</CardTitle>
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
          <div ref={containerRef} style={{ width: '100%', height: 360 }}>
            <Chart
              ariaDesc={title}
              height={360}
              width={chartWidth}
              padding={{ bottom: 90, left: 60, right: 20, top: 20 }}
              domainPadding={{ x: 20 }}
              themeColor={ChartThemeColor.multi}
              containerComponent={
                <ChartVoronoiContainer
                  voronoiDimension="x"
                  labels={({ datum }: { datum: { x: string; y: number; indexLabel: string } }) =>
                    `${datum.x} — ${datum.indexLabel}: ${datum.y.toFixed(1)}%`}
                  labelComponent={<ChartTooltip />}
                  constrainToVisibleArea
                />
              }
            >
              <ChartAxis style={{ tickLabels: { angle: -45, fontSize: 10, textAnchor: 'end' } }} />
              <ChartAxis
                dependentAxis
                tickFormat={(y: number) => `${y.toFixed(0)}%`}
                style={{ grid: GRID_STYLE }}
              />
              <ChartBar data={series} style={{ data: { fill: BAR_COLOR } }} />
            </Chart>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
