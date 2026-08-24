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

const BAR_COLOR = '#0066CC';
// Same red/green convention already used elsewhere for signed values (PerformancePage.tsx,
// AccountsSummaryPage.tsx) — reused here rather than inventing a new pair.
const POSITIVE_COLOR = '#3E8635';
const NEGATIVE_COLOR = '#C9190B';
const GRID_STYLE = { stroke: '#d2d2d2', strokeWidth: 1 };

/**
 * Fully domain-agnostic chart datum — every caller maps its own entries (PerformanceEntry,
 * EquityPremiumEntry, ...) into this shape before passing `data` in, so the chart itself never
 * needs to know about a specific feature's fields (currency, anchor_date, equity/bond labels,
 * ...). `tooltipLabel` is the descriptive text shown between the bar's category and its
 * formatted value, e.g. an index/ETF name — build a richer string here for a chart that needs
 * more than one number in its tooltip (see EquityPremiumSection.tsx).
 */
export interface PerformanceChartDatum {
  label: string;
  value: number;
  tooltipLabel: string;
}

interface PerformanceBarChartProps {
  title: string;
  data: PerformanceChartDatum[] | undefined;
  isLoading: boolean;
  /** Colors each bar green (>= 0) / red (< 0) instead of the uniform BAR_COLOR — opt-in so the
   * two existing percentage-leaderboard charts render unchanged. */
  colorBySign?: boolean;
}

/**
 * Static ranked bar chart — one bar per row, sorted by the caller (already ascending: worst on
 * the left, best on the right — no client-side re-sort). Shared by the country leaderboard
 * (MarketPerformanceSection.tsx), the sector/commodity chart (SectorPerformanceSection.tsx),
 * and the equity risk premium chart (EquityPremiumSection.tsx) — they differ only in what
 * populates `data` and whether `colorBySign` is set, never in how it's rendered.
 *
 * Deliberately NOT modeled on RatioIndicatorChart.tsx: this has a categorical x-axis (no
 * dates), a single snapshot per row (no time series to zoom/scrub), so none of that
 * component's drag-to-zoom/crosshair/period-selector machinery applies (YAGNI).
 *
 * The y-axis domain is left auto-computed from the data (no explicit `domain` prop) so a
 * negative value renders its bar below the zero line instead of being silently clipped by an
 * assumed zero floor.
 */
export default function PerformanceBarChart({ title, data, isLoading, colorBySign = false }: PerformanceBarChartProps) {
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

  // Rendered in the exact order given (already ascending: worst on the left, best on the
  // right) — no client-side re-sort. tooltipLabel rides along on each datum (not part of the
  // x/y the bar itself is positioned by) so the tooltip can show descriptive text without a
  // separate lookup.
  const series = hasData
    ? data.map((d) => ({ x: d.label, y: d.value, tooltipLabel: d.tooltipLabel }))
    : [];

  // Victory's own callback type declares `datum` optional (CallbackArgs), but it is always
  // present for a real ChartBar render — `any` avoids a structural mismatch without adding an
  // untestable defensive branch for a case that never happens in practice.
  const barFill: any = colorBySign
    ? ({ datum }: { datum: { y: number } }) => (datum.y >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR)
    : BAR_COLOR;

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
                  labels={({ datum }: { datum: { x: string; y: number; tooltipLabel: string } }) =>
                    `${datum.x} — ${datum.tooltipLabel}: ${datum.y.toFixed(1)}%`}
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
              <ChartBar data={series} style={{ data: { fill: barFill } }} />
            </Chart>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
