// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import {
	Badge,
	Card,
	CardBody,
	CardTitle,
	Grid,
	GridItem,
	Modal,
	ModalBody,
	ModalHeader,
	ModalVariant,
	PageSection,
	PageSectionVariants,
	Spinner,
	Content,
	ContentVariants,
	Title
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { formatEUR, formatUnitPrice, dateToLocalStr } from '../utils/format';
import { useDailySnapshots, useDailyWithPools, useMonthlySnapshots, useHoldingsAtDate, useTWRR } from '../api/queries';
import type { TWRRPoint } from '../api/queries';
import type { DailySnapshot, Holding } from '../types';
import IndexChart, { HOLDING_COLORS } from '../components/IndexChart';
import type { IndexView, BrushState } from '../components/IndexChart';
import PatrimoineChart from '../components/PatrimoineChart';
import SnapshotsTable from '../components/SnapshotsTable';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';

const defaultScale = (() => { const e = new Date(); const s = new Date(e); s.setFullYear(s.getFullYear()-1); return { x: [s, e] as [Date,Date] }; })();

const PERIODS = ['1M', '3M', '1Y', 'YTD', '5Y', '10Y', 'MAX'] as const;
type Period = typeof PERIODS[number];

function periodStart(period: Period, refDate: Date): Date | null {
  const d = new Date(refDate);
  switch (period) {
    case '1M': d.setMonth(d.getMonth() - 1); return d;
    case '3M': d.setMonth(d.getMonth() - 3); return d;
    case '1Y': d.setFullYear(d.getFullYear() - 1); return d;
    case 'YTD': return new Date(refDate.getFullYear(), 0, 1);
    case '5Y': d.setFullYear(d.getFullYear() - 5); return d;
    case '10Y': d.setFullYear(d.getFullYear() - 10); return d;
    /* v8 ignore next -- @preserve */
    case 'MAX': return null;
  }
}

function twrrPct(total: TWRRPoint[], period: Period): number | null {
  if (total.length < 2) return null;
  const end = total[total.length - 1];
  const endDate = new Date(end.date);
  const start = periodStart(period, endDate);
  let startPt: TWRRPoint;
  if (!start) {
    startPt = total[0];
  } else {
    const startStr = dateToLocalStr(start);
    // If oldest data point is more recent than the requested period → not enough history
    if (total[0].date > startStr) return null;
    const found = total.find((p) => p.date >= startStr);
    if (!found || found === end) return null;
    startPt = found;
  }
  if (startPt.index === 0) return null;
  return (end.index / startPt.index - 1) * 100;
}

function patrimoineRef(sorted: DailySnapshot[], period: Period): number | null {
  if (sorted.length < 2) return null;
  const last = sorted[sorted.length - 1];
  const start = periodStart(period, new Date(last.date));
  if (!start) return sorted[0].total_eur;
  const startStr = start.toISOString().slice(0, 10);
  const found = [...sorted].reverse().find((s) => s.date <= startStr);
  return found && found.total_eur !== 0 ? found.total_eur : null;
}

function patrimoinePct(sorted: DailySnapshot[], period: Period): number | null {
  const ref = patrimoineRef(sorted, period);
  if (ref === null || sorted.length < 2) return null;
  return (sorted[sorted.length - 1].total_eur / ref - 1) * 100;
}

function patrimoineAbsChange(sorted: DailySnapshot[], period: Period): number | null {
  const ref = patrimoineRef(sorted, period);
  if (ref === null || sorted.length < 2) return null;
  return sorted[sorted.length - 1].total_eur - ref;
}

function PctBadge({ value }: { value: number | null }) {
  if (value === null) return <span style={{ color: '#aaa' }}>—</span>;
  const color = value >= 0 ? '#137333' : '#C9190B';
  return (
    <span style={{ color }}>
      {value >= 0 ? '+' : ''}{value.toFixed(2)} %
    </span>
  );
}

function PeriodGrid({
  values, timeScale, absValues,
}: {
  values: (number | null)[];
  timeScale: string;
  absValues?: (number | null)[];
}) {
  return (
    <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
      {PERIODS.map((p, i) => (
        <div key={p} style={{
          textAlign: 'center',
          padding: '3px 8px',
          borderRadius: 4,
          background: timeScale === p ? '#e8f0fe' : undefined,
          border: timeScale === p ? '1px solid #0066CC' : '1px solid transparent',
        }}>
          <div style={{ fontSize: '0.65rem', color: '#6A6E73', fontWeight: 600, marginBottom: '1px', textTransform: 'uppercase' }}>{p}</div>
          {absValues && (
            <div style={{ fontSize: '0.75rem', color: absValues[i] === null ? '#aaa' : absValues[i]! >= 0 ? '#137333' : '#C9190B' }}>
              {absValues[i] === null ? '—' : `${absValues[i]! >= 0 ? '+' : ''}${formatEUR(absValues[i]!)}`}
            </div>
          )}
          <div style={{ fontSize: '0.85rem', fontWeight: timeScale === p ? 700 : 400 }}>
            <PctBadge value={values[i]} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function PerformancePage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const [indexView, setIndexView] = useState<IndexView>('total');
  const [snapPage, setSnapPage] = useState(1);
  const [selectedSnap, setSelectedSnap] = useState<DailySnapshot | null>(null);
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);
  const [zoomIndex, setZoomIndex] = useState<{ x?: [Date, Date]; y?: [number, number] } | undefined>(defaultScale);
  const [zoomPatrimoine, setZoomPatrimoine] = useState<{ x?: [Date, Date]; y?: [number, number] } | undefined>(defaultScale);
  const [isManuallyZoomedIndex, setIsManuallyZoomedIndex] = useState(false);
  const [isManuallyZoomedPatrimoine, setIsManuallyZoomedPatrimoine] = useState(false);

  // Time scale selector
  type TimeScale = '1M' | '3M' | '1Y' | 'YTD' | '5Y' | '10Y' | 'MAX';
  const [timeScale, setTimeScale] = useState<TimeScale>('1Y');

  const scaleToDateRange = (scale: string): { x: [Date, Date] } | undefined => {
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let start: Date;
    switch (scale) {
      /* v8 ignore next -- @preserve */
      case '1M':  start = new Date(end); start.setMonth(start.getMonth() - 1); break;
      /* v8 ignore next -- @preserve */
      case '3M':  start = new Date(end); start.setMonth(start.getMonth() - 3); break;
      /* v8 ignore next -- @preserve */
      case 'YTD': start = new Date(end.getFullYear(), 0, 1); break;
      /* v8 ignore next -- @preserve */
      case '5Y':  start = new Date(end); start.setFullYear(start.getFullYear() - 5); break;
      /* v8 ignore next -- @preserve */
      case '10Y': start = new Date(end); start.setFullYear(start.getFullYear() - 10); break;
      case 'MAX': return undefined;
      default:    start = new Date(end); start.setFullYear(start.getFullYear() - 1); // '1Y' + any unknown
    }
    return { x: [start, end] };
  };

  const applyTimeScale = (scale: TimeScale) => {
    const range = scaleToDateRange(scale);
    setTimeScale(scale);
    setZoomIndex(range);
    setZoomPatrimoine(range);
    setIsManuallyZoomedIndex(false);
    setIsManuallyZoomedPatrimoine(false);
  };

  const [brush, setBrush] = useState<BrushState>(null);

  const [visiblePools, setVisiblePools] = useState<Set<string> | null>(null);
  const [visibleStrats, setVisibleStrats] = useState<Set<string> | null>(null);
  const [visiblePositions, setVisiblePositions] = useState<Set<string> | null>(null);

  // Responsive chart width
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(1100);
  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;
    const initial = el.getBoundingClientRect().width;
    if (initial > 0) setChartWidth(Math.floor(initial));
    const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { data: daily,   isLoading: loadingDaily }   = useDailySnapshots(portfolioId!);
  const { data: histHoldings, isLoading: loadingHist } = useHoldingsAtDate(portfolioId!, selectedSnap?.date ?? null);
  const { isLoading: loadingMonthly } = useMonthlySnapshots(portfolioId!);
  const { data: _withPools } = useDailyWithPools(portfolioId!);
  const { data: twrr, isLoading: loadingTWRR } = useTWRR(portfolioId!);

  // useMemo must be declared before any early return (Rules of Hooks)
  const sortedDaily = useMemo(
    () => [...(daily ?? [])].sort((a, b) => a.date.localeCompare(b.date)),
    [daily],
  );

  const loading = loadingDaily || loadingMonthly || loadingTWRR;

  if (loading) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" />
        </div>
      </PageSection>
    );
  }

  // ── TWRR index series — rebased to 100 at the start of the zoom window ──
  const rebaseToZoom = (
    raw: { x: Date; y: number }[],
    zoomStart: Date | undefined,
  ): { x: Date; y: number }[] => {
    if (!raw.length) return raw;
    const refPt = zoomStart
      ? (raw.find((p) => p.x >= zoomStart) ?? raw[0])
      : raw[0];
    /* v8 ignore next -- @preserve */
    const ref = refPt?.y ?? 1;
    /* v8 ignore next -- @preserve */
    if (!ref) return raw;
    return raw.map((p) => ({ ...p, y: Math.round((p.y / ref) * 10000) / 100 }));
  };

  const zStart = zoomIndex?.x?.[0];
  const twrrToSeries = (pts: TWRRPoint[]) =>
    rebaseToZoom(pts.map((p) => ({ x: new Date(p.date), y: p.index })), zStart);

  const totalIndexData = twrrToSeries(twrr?.total ?? []);
  const offIndexData   = twrrToSeries(twrr?.offensive ?? []);
  const defIndexData   = twrrToSeries(twrr?.defensive ?? []);

  const poolNames = Object.keys(twrr?.pools ?? {});
  const poolSeriesData: Record<string, { x: Date; y: number; name: string }[]> = {};
  for (const [name, pts] of Object.entries(twrr?.pools ?? {})) {
    const rebased = rebaseToZoom(
      pts.map((p) => ({ x: new Date(p.date), y: p.index })),
      zStart,
    );
    poolSeriesData[name] = rebased.map((p) => ({ ...p, name }));
  }

  const activePools = poolNames.filter((name) => {
    /* v8 ignore next -- @preserve */
    const series = poolSeriesData[name] ?? [];
    /* v8 ignore next -- @preserve */
    if (!series.length) return false;
    /* v8 ignore next -- @preserve */
    if (!zoomIndex?.x) return true;
    const [zS, zE] = zoomIndex.x;
    return series.some((d) => d.x >= zS && d.x <= zE);
  });

  const positionNames = Object.keys(twrr?.positions ?? {});
  const positionSeriesData: Record<string, { x: Date; y: number; ticker: string }[]> = {};
  for (const [name, pts] of Object.entries(twrr?.positions ?? {})) {
    const rebased = rebaseToZoom(pts.map((p) => ({ x: new Date(p.date), y: p.index })), zStart);
    positionSeriesData[name] = rebased.map((p) => ({ ...p, ticker: name }));
  }

  const positionColorMap: Record<string, string> = {};
  positionNames.forEach((name, i) => {
    positionColorMap[name] = HOLDING_COLORS[i % HOLDING_COLORS.length];
  });

  const activePositionTickers = positionNames.filter((name) => {
    /* v8 ignore next -- @preserve */
    const series = positionSeriesData[name] ?? [];
    /* v8 ignore next -- @preserve */
    if (!series.length) return false;
    /* v8 ignore next -- @preserve */
    if (!zoomIndex?.x) return true;
    const [zS, zE] = zoomIndex.x;
    return series.some((d) => d.x >= zS && d.x <= zE);
  });

  const step = Math.max(1, Math.floor(sortedDaily.length / 150));
  const patrimoineData = sortedDaily
    .filter((_, i) => i % step === 0 || i === sortedDaily.length - 1)
    .map((s) => ({ x: new Date(s.date), y: Math.round(s.total_eur) }));

  // Adaptive date format: full date (YYYY-MM-DD) when zoomed < 90 days, month otherwise
  const makeAxisStyle = (zoomDom?: { x?: [Date, Date] }) => {
    const zoomDays = zoomDom?.x
      ? (zoomDom.x[1].getTime() - zoomDom.x[0].getTime()) / 86_400_000
      : Infinity;
    return {
      scale: 'time' as const,
      tickFormat: (d: Date) => {
        const dt = d instanceof Date ? d : new Date(d);
        const yy = dt.getFullYear();
        const mm = String(dt.getMonth() + 1).padStart(2, '0');
        if (zoomDays < 90) {
          const dd = String(dt.getDate()).padStart(2, '0');
          return `${yy}-${mm}-${dd}`;
        }
        return `${yy}-${mm}`;
      },
      style: {
        tickLabels: { fontSize: 10, angle: -45, textAnchor: 'end' as const },
        grid: { stroke: '#d4d4d4', strokeWidth: 0.5 },
      },
      tickCount: 16,
      fixLabelOverlap: true,
    };
  };

  const MIN_ZOOM_INDEX_MS = 60 * 86_400_000;
  const MIN_ZOOM_PATRIMOINE_MS = 7 * 86_400_000;
  const CHART_PADDING_LEFT = 50;

  const clampZoom = (domain: { x?: [Date, Date]; y?: [number, number] }, minMs: number) => {
    if (!domain.x) return domain;
    const [s, e] = domain.x;
    const diff = e.getTime() - s.getTime();
    if (diff < minMs) {
      const center = (s.getTime() + e.getTime()) / 2;
      return { ...domain, x: [new Date(center - minMs / 2), new Date(center + minMs / 2)] as [Date, Date] };
    }
    return domain;
  };

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1.5rem' }}>
        {t('performance.title')}
      </Title>

      {/* ── Valeur patrimoine + TWRR multi-périodes ── */}
      <Grid hasGutter style={{ marginBottom: '1.5rem' }}>
        <GridItem span={6}>
          <Card isFullHeight>
            <CardTitle>{t('performance.patrimoine')}</CardTitle>
            <CardBody>
              {sortedDaily.length > 0 ? (
                <>
                  <div style={{ fontSize: '1.6rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
                    {formatEUR(sortedDaily[sortedDaily.length - 1].total_eur)}
                  </div>
                  <PeriodGrid
                    values={PERIODS.map((p) => patrimoinePct(sortedDaily, p))}
                    absValues={PERIODS.map((p) => patrimoineAbsChange(sortedDaily, p))}
                    timeScale={timeScale}
                  />
                </>
              ) : (
                <Content component={ContentVariants.p} style={{ color: '#6A6E73' }}>{t('performance.noData')}</Content>
              )}
            </CardBody>
          </Card>
        </GridItem>
        <GridItem span={6}>
          <Card isFullHeight>
            <CardTitle>TWRR (Time-Weighted Rate of Return)</CardTitle>
            <CardBody>
              <PeriodGrid
                values={PERIODS.map((p) => twrrPct(twrr?.total ?? [], p))}
                timeScale={timeScale}
              />
              <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: '#3E8635' }}>
                ✅ Mesure fiable — neutralise les flux externes
              </div>
            </CardBody>
          </Card>
        </GridItem>
      </Grid>

      {/* ── Time scale selector (shared between both charts) ── */}
      <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        {(['1M', '3M', '1Y', 'YTD', '5Y', '10Y', 'MAX'] as const).map((s) => (
          <button key={s} onClick={() => applyTimeScale(s)} style={{
            padding: '3px 10px', cursor: 'pointer', borderRadius: 4, fontSize: '0.8rem',
            border: timeScale === s ? '2px solid #0066CC' : '1px solid #ccc',
            background: timeScale === s ? '#e8f0fe' : '#f5f5f5',
            fontWeight: timeScale === s ? 'bold' : 'normal',
            color: timeScale === s ? '#0066CC' : 'inherit',
          }}>
            {s}
          </button>
        ))}
      </div>

      {/* ── Graphique indice base 100 ── */}
      <IndexChart
        indexView={indexView}
        setIndexView={setIndexView}
        zoomIndex={zoomIndex}
        setZoomIndex={setZoomIndex}
        isManuallyZoomed={isManuallyZoomedIndex}
        setIsManuallyZoomed={setIsManuallyZoomedIndex}
        brush={brush}
        setBrush={setBrush}
        chartWidth={chartWidth}
        chartContainerRef={chartContainerRef}
        timeScale={timeScale}
        scaleToDateRange={scaleToDateRange}
        totalIndexData={totalIndexData}
        offIndexData={offIndexData}
        defIndexData={defIndexData}
        poolSeriesData={poolSeriesData}
        holdingSeriesData={positionSeriesData}
        holdingColorMap={positionColorMap}
        activePools={activePools}
        activeHoldingTickers={activePositionTickers}
        visiblePools={visiblePools}
        setVisiblePools={setVisiblePools}
        visibleStrats={visibleStrats}
        setVisibleStrats={setVisibleStrats}
        visibleHoldings={visiblePositions}
        setVisibleHoldings={setVisiblePositions}
        makeAxisStyle={makeAxisStyle}
        clampZoom={clampZoom}
        MIN_ZOOM_INDEX_MS={MIN_ZOOM_INDEX_MS}
        CHART_PADDING_LEFT={CHART_PADDING_LEFT}
      />

      {/* ── Graphique patrimoine ── */}
      <PatrimoineChart
        patrimoineData={patrimoineData}
        zoomPatrimoine={zoomPatrimoine}
        setZoomPatrimoine={setZoomPatrimoine}
        isManuallyZoomed={isManuallyZoomedPatrimoine}
        setIsManuallyZoomed={setIsManuallyZoomedPatrimoine}
        brush={brush}
        setBrush={setBrush}
        chartWidth={chartWidth}
        timeScale={timeScale}
        scaleToDateRange={scaleToDateRange}
        makeAxisStyle={makeAxisStyle}
        clampZoom={clampZoom}
        MIN_ZOOM_PATRIMOINE_MS={MIN_ZOOM_PATRIMOINE_MS}
        CHART_PADDING_LEFT={CHART_PADDING_LEFT}
      />

      {/* ── Tableau snapshots journaliers ── */}
      <SnapshotsTable
        sortedDaily={sortedDaily}
        snapPage={snapPage}
        setSnapPage={setSnapPage}
        onRowClick={setSelectedSnap}
      />

      {/* ── Popup positions historiques ── */}
      {selectedSnap && (
        <Modal
          variant={ModalVariant.large}
          isOpen
          onClose={() => setSelectedSnap(null)}
        >
          <ModalHeader title={`${t('holdings.currentHoldings')} ${selectedSnap.date} — ${t('common.total')} ${formatEUR(selectedSnap.total_eur)}`} />
          <ModalBody>
          {loadingHist ? (
            <div style={{ textAlign: 'center', padding: '2rem' }}><Spinner size="lg" /></div>
          ) : !histHoldings || histHoldings.length === 0 ? (
            <Content><Content component="p">{t('performance.noHoldingsAtDate')}</Content></Content>
          ) : (() => {
            const UNASSIGNED = t('holdings.unassigned');
            const byPool = new Map<string, Holding[]>();
            for (const h of histHoldings) {
              const key = h.pool_name ?? UNASSIGNED;
              if (!byPool.has(key)) byPool.set(key, []);
              byPool.get(key)!.push(h);
            }
            const sorted = [...byPool.entries()].sort(([a], [b]) => {
              if (a === UNASSIGNED) return 1;
              if (b === UNASSIGNED) return -1;
              const totA = byPool.get(a)!.reduce((s, h) => s + h.value_eur, 0);
              const totB = byPool.get(b)!.reduce((s, h) => s + h.value_eur, 0);
              return totB - totA;
            });

            return (
              <div>
                {sorted.map(([poolName, poolHoldings]) => {
                  const poolTotal = poolHoldings.reduce((s, h) => s + h.value_eur, 0);
                  return (
                    <div key={poolName} style={{ marginBottom: '1.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <strong>{poolName}</strong>
                        <Badge>{formatEUR(poolTotal)}</Badge>
                        <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>
                          {selectedSnap.total_eur > 0
                            ? `${(poolTotal / selectedSnap.total_eur * 100).toFixed(1)} %`
                            : ''}
                        </span>
                      </div>
                      <Table variant="compact" aria-label={poolName}>
                        <Thead><Tr><Th>{t('common.ticker')}</Th><Th>{t('common.quantity')}</Th><Th>{t('common.price')}</Th><Th>{t('positions.valueEur')}</Th></Tr></Thead>
                        <Tbody>
                          {poolHoldings.sort((a, b) => b.value_eur - a.value_eur).map((h) => (
                            <Tr key={h.ticker}>
                              <Td><strong><TickerLink ticker={h.ticker} instrumentType={h.instrument_type} onClick={setCompositionTicker} /></strong></Td>
                              <Td>{h.quantity.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}</Td>
                              <Td>{formatUnitPrice(h.last_price, h.currency || 'EUR')}</Td>
                              <Td>{formatEUR(h.value_eur)}</Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    </div>
                  );
                })}
              </div>
            );
          })()}
          </ModalBody>
        </Modal>
      )}
      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </PageSection>
  );
}
