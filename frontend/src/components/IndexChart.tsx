import { useRef, useState } from 'react';
import {
  Card, CardBody, CardTitle,
  ToggleGroup, ToggleGroupItem,
} from '@patternfly/react-core';
import {
  Chart, ChartAxis, ChartGroup, ChartLine, ChartThemeColor,
} from '@patternfly/react-charts';
import { VictoryZoomContainer } from 'victory-zoom-container';
import ChartCrosshair, { type ChartCrosshairSeries, type ChartCrosshairState } from './ChartCrosshair';

export type IndexView = 'total' | 'strategie' | 'pools' | 'positions';

export const POOL_COLORS: Record<string, string> = {
  Asie:    '#0066CC',
  Energie: '#F0AB00',
  Or:      '#B8860B',
  Yen:     '#3E8635',
  Legacy:  '#8A8D90',
};

export const HOLDING_COLORS: string[] = [
  '#0066CC', '#F0AB00', '#3E8635', '#C9190B', '#8481DD',
  '#009596', '#F4C145', '#EC7A08', '#A2D9D9', '#B2A3FF',
  '#EF9234', '#23511E', '#7D1007', '#004D63', '#8B8B00',
  '#C73600', '#519DE9', '#6EC664', '#BEF5CA', '#F9E0A2',
];

const OFF_COLOR = '#0066CC';
const DEF_COLOR = '#3E8635';

export type BrushState = {
  startX: number;
  endX: number;
  active: boolean;
  chartId: 'index' | 'patrimoine';
} | null;

interface IndexChartProps {
  indexView: IndexView;
  setIndexView: (v: IndexView) => void;
  zoomIndex: { x?: [Date, Date]; y?: [number, number] } | undefined;
  setZoomIndex: (z: { x?: [Date, Date]; y?: [number, number] } | undefined) => void;
  isManuallyZoomed: boolean;
  setIsManuallyZoomed: (v: boolean) => void;
  brush: BrushState;
  setBrush: React.Dispatch<React.SetStateAction<BrushState>>;
  chartWidth: number;
  chartContainerRef: React.RefObject<HTMLDivElement>;
  timeScale: string;
  scaleToDateRange: (scale: string) => { x: [Date, Date] } | undefined;
  totalIndexData: { x: Date; y: number }[];
  offIndexData: { x: Date; y: number }[];
  defIndexData: { x: Date; y: number }[];
  poolSeriesData: Record<string, { x: Date; y: number; name: string }[]>;
  holdingSeriesData: Record<string, { x: Date; y: number; ticker: string }[]>;
  holdingColorMap: Record<string, string>;
  activePools: string[];
  activeHoldingTickers: string[];
  visiblePools: Set<string> | null;
  setVisiblePools: React.Dispatch<React.SetStateAction<Set<string> | null>>;
  visibleStrats: Set<string> | null;
  setVisibleStrats: React.Dispatch<React.SetStateAction<Set<string> | null>>;
  visibleHoldings: Set<string> | null;
  setVisibleHoldings: React.Dispatch<React.SetStateAction<Set<string> | null>>;
  makeAxisStyle: (zoomDom?: { x?: [Date, Date] }) => object;
  clampZoom: (
    domain: { x?: [Date, Date]; y?: [number, number] },
    minMs: number
  ) => { x?: [Date, Date]; y?: [number, number] };
  MIN_ZOOM_INDEX_MS: number;
  CHART_PADDING_LEFT: number;
}

export default function IndexChart({
  indexView, setIndexView,
  zoomIndex, setZoomIndex,
  isManuallyZoomed, setIsManuallyZoomed,
  brush, setBrush,
  chartWidth, chartContainerRef,
  timeScale, scaleToDateRange,
  totalIndexData, offIndexData, defIndexData,
  poolSeriesData, holdingSeriesData, holdingColorMap,
  activePools, activeHoldingTickers,
  visiblePools, setVisiblePools,
  visibleStrats, setVisibleStrats,
  visibleHoldings, setVisibleHoldings,
  makeAxisStyle, clampZoom,
  MIN_ZOOM_INDEX_MS, CHART_PADDING_LEFT,
}: IndexChartProps) {
  const indexChartRef = useRef<HTMLDivElement>(null);
  const [crosshair, setCrosshair] = useState<ChartCrosshairState>(null);

  const isPoolVisible    = (n: string) => visiblePools    === null || visiblePools.has(n);
  const isStratVisible   = (n: string) => visibleStrats   === null || visibleStrats.has(n);
  const isHoldingVisible = (t: string) => visibleHoldings === null || visibleHoldings.has(t);

  const soloToggle = (setter: React.Dispatch<React.SetStateAction<Set<string> | null>>) =>
    (name: string) => setter((prev) => {
      if (prev === null) return new Set([name]);
      if (prev.has(name)) { const next = new Set(prev); next.delete(name); return next.size === 0 ? null : next; }
      return new Set([...prev, name]);
    });

  const togglePool    = soloToggle(setVisiblePools);
  const toggleStrat   = soloToggle(setVisibleStrats);
  const toggleHolding = soloToggle(setVisibleHoldings);

  const allHoldingVals = activeHoldingTickers
    .filter((t) => isHoldingVisible(t))
    .flatMap((t) => (holdingSeriesData[t] ?? []).map((d) => d.y));
  const minHoldingVal = allHoldingVals.length ? Math.min(...allHoldingVals) : 0;
  const maxHoldingVal = allHoldingVals.length ? Math.max(...allHoldingVals) : 150;

  const allIndexVals =
    indexView === 'total'
      ? totalIndexData.map((d) => d.y)
      : indexView === 'strategie'
      ? [
          ...(isStratVisible('Offensif') ? offIndexData : []),
          ...(isStratVisible('Défensif') ? defIndexData : []),
        ].map((d) => d.y)
      : indexView === 'pools'
      ? Object.entries(poolSeriesData)
          .filter(([name]) => activePools.includes(name) && isPoolVisible(name))
          .flatMap(([, data]) => data)
          .map((d) => d.y)
      : [];
  const minIdx = allIndexVals.length ? Math.min(...allIndexVals) : 0;
  const maxIdx = allIndexVals.length ? Math.max(...allIndexVals) : 150;

  const depAxisStyle = { tickLabels: { fontSize: 10 }, grid: { stroke: '#d4d4d4', strokeWidth: 0.5 } };

  const startBrush = (e: React.MouseEvent) => {
    const rect = indexChartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    setBrush({ startX: x, endX: x, active: true, chartId: 'index' });
  };

  const moveBrush = (e: React.MouseEvent) => {
    const rect = indexChartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const xPx = e.clientX - rect.left;

    // Update brush drag if active
    if (brush?.active) {
      setBrush(b => b ? { ...b, endX: xPx } : null);
    }

    // Update crosshair (only when not dragging a brush)
    if (!brush?.active) {
      const plotW = rect.width - CHART_PADDING_LEFT - 10;
      const relX = xPx - CHART_PADDING_LEFT;
      if (relX >= 0 && relX <= plotW && plotW > 0) {
        let minT: number, maxT: number;
        if (zoomIndex?.x) {
          minT = zoomIndex.x[0].getTime();
          maxT = zoomIndex.x[1].getTime();
        } else {
          const baseData = totalIndexData.length ? totalIndexData : offIndexData.length ? offIndexData : defIndexData;
          if (baseData.length < 2) { setCrosshair(null); return; }
          minT = baseData[0].x.getTime();
          maxT = baseData[baseData.length - 1].x.getTime();
        }
        const tMs = minT + (relX / plotW) * (maxT - minT);

        const findNearest = (data: { x: Date; y: number }[]): { x: Date; y: number } | null => {
          if (!data.length) return null;
          let nearest = data[0];
          let minDist = Math.abs(nearest.x.getTime() - tMs);
          for (const pt of data) {
            const dist = Math.abs(pt.x.getTime() - tMs);
            if (dist < minDist) { minDist = dist; nearest = pt; }
          }
          return nearest;
        };

        const series: ChartCrosshairSeries[] = [];

        const addToSeries = (name: string, data: { x: Date; y: number }[], color: string) => {
          const pt = findNearest(data);
          if (pt) series.push({ name, value: pt.y, color });
        };

        if (indexView === 'total') {
          addToSeries('Total', totalIndexData, '#3E8635');
        } else if (indexView === 'strategie') {
          if (isStratVisible('Offensif')) addToSeries('Offensif', offIndexData, OFF_COLOR);
          if (isStratVisible('Défensif')) addToSeries('Défensif', defIndexData, DEF_COLOR);
        } else if (indexView === 'pools') {
          for (const name of activePools.filter((n) => isPoolVisible(n))) {
            addToSeries(name, poolSeriesData[name] ?? [], POOL_COLORS[name] ?? '#6A6E73');
          }
        } else {
          for (const ticker of activeHoldingTickers.filter((t) => isHoldingVisible(t))) {
            addToSeries(ticker, holdingSeriesData[ticker] ?? [], holdingColorMap[ticker] ?? '#6A6E73');
          }
        }

        // Determine hoverDate from the primary data for the current view
        const primaryData =
          indexView === 'total' ? totalIndexData
          : indexView === 'strategie' ? [...offIndexData, ...defIndexData]
          : indexView === 'pools' ? activePools.flatMap((n) => poolSeriesData[n] ?? [])
          : activeHoldingTickers.flatMap((t) => holdingSeriesData[t] ?? []);
        const hoverDate = findNearest(primaryData)?.x ?? null;

        if (hoverDate && series.length) {
          setCrosshair({ xPx, date: hoverDate, series, containerWidth: rect.width });
        } else {
          setCrosshair(null);
        }
      } else {
        setCrosshair(null);
      }
    } else {
      setCrosshair(null);
    }
  };

  const endBrush = () => {
    if (!brush?.active || Math.abs(brush.endX - brush.startX) < 5) {
      setBrush(null);
      return;
    }
    const rect = indexChartRef.current?.getBoundingClientRect();
    if (!rect) { setBrush(null); return; }
    const plotW = rect.width - CHART_PADDING_LEFT - 10;
    const leftX = Math.min(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    const rightX = Math.max(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    if (plotW <= 0) { setBrush(null); return; }
    const currentZoom = zoomIndex;
    let minT: number, maxT: number;
    if (currentZoom?.x) {
      minT = currentZoom.x[0].getTime();
      maxT = currentZoom.x[1].getTime();
    } else {
      const allData = totalIndexData.map(d => d.x);
      if (allData.length < 2) { setBrush(null); return; }
      minT = allData[0].getTime();
      maxT = allData[allData.length - 1].getTime();
    }
    const range = maxT - minT;
    const startMs = minT + (leftX / plotW) * range;
    const endMs = minT + (rightX / plotW) * range;
    const clamped = clampZoom({ x: [new Date(startMs), new Date(endMs)] }, MIN_ZOOM_INDEX_MS);
    setZoomIndex(clamped);
    setIsManuallyZoomed(true);
    setBrush(null);
  };

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <span>Indice de performance TWRR (base 100)</span>
          <ToggleGroup aria-label="Vue indice">
            <ToggleGroupItem
              text="Total"
              isSelected={indexView === 'total'}
              onChange={() => { setIndexView('total'); setZoomIndex(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
            />
            <ToggleGroupItem
              text="Offensif / Défensif"
              isSelected={indexView === 'strategie'}
              onChange={() => { setIndexView('strategie'); setZoomIndex(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
            />
            <ToggleGroupItem
              text="Pools"
              isSelected={indexView === 'pools'}
              onChange={() => { setIndexView('pools'); setZoomIndex(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
            />
            <ToggleGroupItem
              text="Positions"
              isSelected={indexView === 'positions'}
              onChange={() => { setIndexView('positions'); setZoomIndex(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
            />
          </ToggleGroup>
          {isManuallyZoomed && (
            <button
              onClick={() => { setZoomIndex(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
              style={{ fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 3, background: '#f5f5f5' }}
            >
              ↺ Réinitialiser zoom
            </button>
          )}
        </div>
      </CardTitle>
      <CardBody style={{ padding: '1rem 1rem 0.5rem' }}>
        {/* Legend for multi-series views */}
        {indexView === 'strategie' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
            {[{ key: 'Offensif', color: OFF_COLOR }, { key: 'Défensif', color: DEF_COLOR }].map(({ key, color }) => {
              const hidden = !isStratVisible(key);
              return (
                <button key={key} onClick={() => toggleStrat(key)} title={hidden ? 'Afficher' : 'Masquer'} style={{
                  background: 'none', border: '1px solid transparent', borderRadius: 4, cursor: 'pointer',
                  padding: '2px 8px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 4,
                  opacity: hidden ? 0.35 : 1, textDecoration: hidden ? 'line-through' : 'none',
                }}>
                  <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, backgroundColor: hidden ? '#bbb' : color }} />
                  {key}
                </button>
              );
            })}
            {visibleStrats !== null && (['Offensif', 'Défensif'].some(k => !isStratVisible(k))) && (
              <button onClick={() => setVisibleStrats(null)} style={{
                fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer',
                border: '1px solid #0066CC', borderRadius: 3, background: '#e8f0fe', color: '#0066CC',
              }}>↺ Tout afficher</button>
            )}
          </div>
        )}
        {indexView === 'pools' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
            {activePools.map((name) => {
              const hidden = !isPoolVisible(name);
              const color = POOL_COLORS[name] ?? '#6A6E73';
              return (
                <button key={name} onClick={() => togglePool(name)} title={hidden ? 'Afficher' : 'Masquer'} style={{
                  background: 'none', border: '1px solid transparent', borderRadius: 4, cursor: 'pointer',
                  padding: '2px 8px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 4,
                  opacity: hidden ? 0.35 : 1, textDecoration: hidden ? 'line-through' : 'none',
                }}>
                  <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, backgroundColor: hidden ? '#bbb' : color }} />
                  {name}
                </button>
              );
            })}
            {visiblePools !== null && activePools.some(n => !isPoolVisible(n)) && (
              <button onClick={() => setVisiblePools(null)} style={{
                fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer',
                border: '1px solid #0066CC', borderRadius: 3, background: '#e8f0fe', color: '#0066CC',
              }}>↺ Tout afficher</button>
            )}
          </div>
        )}
        {indexView === 'positions' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
            {activeHoldingTickers.map((ticker) => {
              const hidden = !isHoldingVisible(ticker);
              const color = holdingColorMap[ticker];
              const label = ticker.length > 12 ? ticker.slice(0, 12) + '…' : ticker;
              return (
                <button key={ticker} onClick={() => toggleHolding(ticker)} title={hidden ? 'Afficher' : 'Masquer'} style={{
                  background: 'none', border: '1px solid transparent', borderRadius: 4, cursor: 'pointer',
                  padding: '2px 8px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 4,
                  opacity: hidden ? 0.35 : 1, textDecoration: hidden ? 'line-through' : 'none',
                }}>
                  <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, backgroundColor: hidden ? '#bbb' : color }} />
                  {label}
                </button>
              );
            })}
            {visibleHoldings !== null && activeHoldingTickers.some(t => !isHoldingVisible(t)) && (
              <button onClick={() => setVisibleHoldings(null)} style={{
                fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer',
                border: '1px solid #0066CC', borderRadius: 3, background: '#e8f0fe', color: '#0066CC',
              }}>↺ Tout afficher</button>
            )}
          </div>
        )}

        <div
          ref={indexChartRef}
          style={{ width: '100%', height: 340, position: 'relative', userSelect: 'none' }}
          onMouseDown={startBrush}
          onMouseMove={moveBrush}
          onMouseUp={endBrush}
          onMouseLeave={() => { if (brush?.active) setBrush(null); setCrosshair(null); }}
        >
          {/* Visible brush rectangle overlay */}
          {brush?.active && brush.chartId === 'index' && (
            <div style={{
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
          {/* Crosshair overlay */}
          <ChartCrosshair crosshair={brush?.active ? null : crosshair} />
          <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }}>
            {indexView === 'total' && totalIndexData.length > 0 && (
              <Chart
                ariaDesc="Indice de performance base 100"
                height={340} width={chartWidth}
                padding={{ bottom: 70, left: 50, right: 10, top: 10 }}
                domain={{ y: [Math.min(minIdx * 0.97, 95), maxIdx * 1.02] }}
                themeColor={ChartThemeColor.green}
                containerComponent={
                  <VictoryZoomContainer
                    zoomDomain={zoomIndex}
                    onZoomDomainChange={(domain: any) => { if (!brush?.active) { setZoomIndex(clampZoom(domain, MIN_ZOOM_INDEX_MS)); setIsManuallyZoomed(true); } }}
                    zoomDimension="x" allowPan={false} allowZoom={false}
                  />
                }
              >
                <ChartAxis {...makeAxisStyle(zoomIndex)} />
                <ChartAxis dependentAxis tickFormat={(y: number) => y.toFixed(0)} style={depAxisStyle} />
                <ChartGroup>
                  <ChartLine data={totalIndexData} interpolation="monotoneX" />
                </ChartGroup>
              </Chart>
            )}

            {indexView === 'strategie' && (offIndexData.length > 0 || defIndexData.length > 0) && (
              <Chart
                ariaDesc="Indice offensif/défensif base 100"
                height={340} width={chartWidth}
                padding={{ bottom: 70, left: 50, right: 10, top: 10 }}
                domain={{ y: [Math.min(minIdx * 0.97, 95), maxIdx * 1.02] }}
                themeColor={ChartThemeColor.multi}
                containerComponent={
                  <VictoryZoomContainer
                    zoomDomain={zoomIndex}
                    onZoomDomainChange={(domain: any) => { if (!brush?.active) { setZoomIndex(clampZoom(domain, MIN_ZOOM_INDEX_MS)); setIsManuallyZoomed(true); } }}
                    zoomDimension="x" allowPan={false} allowZoom={false}
                  />
                }
              >
                <ChartAxis {...makeAxisStyle(zoomIndex)} />
                <ChartAxis dependentAxis tickFormat={(y: number) => y.toFixed(0)} style={depAxisStyle} />
                <ChartGroup>
                  {isStratVisible('Offensif') && <ChartLine data={offIndexData} interpolation="monotoneX" style={{ data: { stroke: OFF_COLOR } }} />}
                  {isStratVisible('Défensif') && <ChartLine data={defIndexData} interpolation="monotoneX" style={{ data: { stroke: DEF_COLOR } }} />}
                </ChartGroup>
              </Chart>
            )}

            {indexView === 'pools' && Object.keys(poolSeriesData).length > 0 && (
              <Chart
                ariaDesc="Indice pools base 100"
                height={340} width={chartWidth}
                padding={{ bottom: 70, left: 50, right: 10, top: 10 }}
                domain={{ y: [Math.min(minIdx * 0.97, 95), maxIdx * 1.02] }}
                themeColor={ChartThemeColor.multi}
                containerComponent={
                  <VictoryZoomContainer
                    zoomDomain={zoomIndex}
                    onZoomDomainChange={(domain: any) => { if (!brush?.active) { setZoomIndex(clampZoom(domain, MIN_ZOOM_INDEX_MS)); setIsManuallyZoomed(true); } }}
                    zoomDimension="x" allowPan={false} allowZoom={false}
                  />
                }
              >
                <ChartAxis {...makeAxisStyle(zoomIndex)} />
                <ChartAxis dependentAxis tickFormat={(y: number) => y.toFixed(0)} style={depAxisStyle} />
                <ChartGroup>
                  {activePools.filter((name) => isPoolVisible(name)).map((name) => (
                    <ChartLine
                      key={name}
                      data={poolSeriesData[name]}
                      interpolation="monotoneX"
                      style={{ data: { stroke: POOL_COLORS[name] ?? '#6A6E73' } }}
                    />
                  ))}
                </ChartGroup>
              </Chart>
            )}

            {indexView === 'positions' && activeHoldingTickers.length > 0 && (
              <Chart
                ariaDesc="Indice de performance positions base 100"
                height={340} width={chartWidth}
                padding={{ bottom: 70, left: 50, right: 10, top: 10 }}
                domain={{ y: [Math.min(minHoldingVal * 0.97, 95), maxHoldingVal * 1.02] }}
                themeColor={ChartThemeColor.multi}
                containerComponent={
                  <VictoryZoomContainer
                    zoomDomain={zoomIndex}
                    onZoomDomainChange={(domain: any) => { if (!brush?.active) { setZoomIndex(clampZoom(domain, MIN_ZOOM_INDEX_MS)); setIsManuallyZoomed(true); } }}
                    zoomDimension="x" allowPan={false} allowZoom={false}
                  />
                }
              >
                <ChartAxis {...makeAxisStyle(zoomIndex)} />
                <ChartAxis dependentAxis tickFormat={(y: number) => y.toFixed(0)} style={depAxisStyle} />
                <ChartGroup>
                  {activeHoldingTickers.filter((t) => isHoldingVisible(t)).map((ticker) => (
                    <ChartLine
                      key={ticker}
                      data={holdingSeriesData[ticker]}
                      interpolation="monotoneX"
                      style={{ data: { stroke: holdingColorMap[ticker] } }}
                    />
                  ))}
                </ChartGroup>
              </Chart>
            )}
          </div>
        </div>

        {indexView !== 'total' && (
          <div style={{ fontSize: '0.75rem', color: '#8A8D90', marginTop: '0.25rem' }}>
            * TWRR (Time-Weighted Rate of Return) — indice normalisé à 100 au début de la période, insensible aux flux externes
          </div>
        )}
      </CardBody>
    </Card>
  );
}
