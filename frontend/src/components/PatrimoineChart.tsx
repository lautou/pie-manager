// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react';
import {
  Card, CardBody, CardTitle,
  Content, ContentVariants,
} from '@patternfly/react-core';
import {
	Chart,
	ChartArea,
	ChartAxis,
	ChartGroup,
	ChartThemeColor
} from '@patternfly/react-charts';
import { VictoryZoomContainer } from 'victory-zoom-container';
import type { BrushState } from './IndexChart';
import { formatEUR } from '../utils/format';

interface PatrimoineChartProps {
  patrimoineData: { x: Date; y: number }[];
  zoomPatrimoine: { x?: [Date, Date]; y?: [number, number] } | undefined;
  setZoomPatrimoine: (z: { x?: [Date, Date]; y?: [number, number] } | undefined) => void;
  isManuallyZoomed: boolean;
  setIsManuallyZoomed: (v: boolean) => void;
  brush: BrushState;
  setBrush: React.Dispatch<React.SetStateAction<BrushState>>;
  chartWidth: number;
  timeScale: string;
  scaleToDateRange: (scale: string) => { x: [Date, Date] } | undefined;
  makeAxisStyle: (zoomDom?: { x?: [Date, Date] }) => object;
  clampZoom: (
    domain: { x?: [Date, Date]; y?: [number, number] },
    minMs: number
  ) => { x?: [Date, Date]; y?: [number, number] };
  MIN_ZOOM_PATRIMOINE_MS: number;
  CHART_PADDING_LEFT: number;
}

type CrosshairState = {
  xPx: number;
  date: Date;
  value: number;
  containerWidth: number;
} | null;

export default function PatrimoineChart({
  patrimoineData,
  zoomPatrimoine, setZoomPatrimoine,
  isManuallyZoomed, setIsManuallyZoomed,
  brush, setBrush,
  chartWidth,
  timeScale, scaleToDateRange,
  makeAxisStyle, clampZoom,
  MIN_ZOOM_PATRIMOINE_MS, CHART_PADDING_LEFT,
}: PatrimoineChartProps) {
  const patrimoineChartRef = useRef<HTMLDivElement>(null);
  const [crosshair, setCrosshair] = useState<CrosshairState>(null);

  const maxVal = patrimoineData.length ? Math.max(...patrimoineData.map((d) => d.y)) : 100;
  const minVal = patrimoineData.length ? Math.min(...patrimoineData.map((d) => d.y)) : 0;

  const depAxisStyle = { tickLabels: { fontSize: 10 }, grid: { stroke: '#d4d4d4', strokeWidth: 0.5 } };

  const startBrush = (e: React.MouseEvent) => {
    const rect = patrimoineChartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    setBrush({ startX: x, endX: x, active: true, chartId: 'patrimoine' });
  };

  const moveBrush = (e: React.MouseEvent) => {
    const rect = patrimoineChartRef.current?.getBoundingClientRect();
    if (!rect) return;
    const xPx = e.clientX - rect.left;

    // Update brush drag if active
    if (brush?.active) {
      setBrush(b => b ? { ...b, endX: xPx } : null);
    }

    // Update crosshair (only when not dragging a brush)
    if (!brush?.active && patrimoineData.length >= 2) {
      const plotW = rect.width - CHART_PADDING_LEFT - 10;
      const relX = xPx - CHART_PADDING_LEFT;
      if (relX >= 0 && relX <= plotW && plotW > 0) {
        const currentZoom = zoomPatrimoine;
        let minT: number, maxT: number;
        if (currentZoom?.x) {
          minT = currentZoom.x[0].getTime();
          maxT = currentZoom.x[1].getTime();
        } else {
          minT = patrimoineData[0].x.getTime();
          maxT = patrimoineData[patrimoineData.length - 1].x.getTime();
        }
        const tMs = minT + (relX / plotW) * (maxT - minT);
        // Find nearest point
        let nearest = patrimoineData[0];
        let minDist = Math.abs(nearest.x.getTime() - tMs);
        for (const pt of patrimoineData) {
          const dist = Math.abs(pt.x.getTime() - tMs);
          if (dist < minDist) { minDist = dist; nearest = pt; }
        }
        setCrosshair({ xPx, date: nearest.x, value: nearest.y, containerWidth: rect.width });
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
    const rect = patrimoineChartRef.current?.getBoundingClientRect();
    if (!rect) { setBrush(null); return; }
    const plotW = rect.width - CHART_PADDING_LEFT - 10;
    const leftX = Math.min(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    const rightX = Math.max(brush.startX, brush.endX) - CHART_PADDING_LEFT;
    if (plotW <= 0) { setBrush(null); return; }
    const currentZoom = zoomPatrimoine;
    let minT: number, maxT: number;
    if (currentZoom?.x) {
      minT = currentZoom.x[0].getTime();
      maxT = currentZoom.x[1].getTime();
    } else {
      const allData = patrimoineData.map(d => d.x);
      if (allData.length < 2) { setBrush(null); return; }
      minT = allData[0].getTime();
      maxT = allData[allData.length - 1].getTime();
    }
    const range = maxT - minT;
    const startMs = minT + (leftX / plotW) * range;
    const endMs = minT + (rightX / plotW) * range;
    const clamped = clampZoom({ x: [new Date(startMs), new Date(endMs)] }, MIN_ZOOM_PATRIMOINE_MS);
    setZoomPatrimoine(clamped);
    setIsManuallyZoomed(true);
    setBrush(null);
  };

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span>Évolution du patrimoine (€)</span>
          {isManuallyZoomed && (
            <button
              onClick={() => { setZoomPatrimoine(scaleToDateRange(timeScale)); setIsManuallyZoomed(false); }}
              style={{ fontSize: '0.75rem', padding: '2px 8px', cursor: 'pointer', border: '1px solid #ccc', borderRadius: 3, background: '#f5f5f5' }}
            >
              ↺ Réinitialiser zoom
            </button>
          )}
        </div>
      </CardTitle>
      <CardBody style={{ padding: '1rem 1rem 0.5rem' }}>
        {patrimoineData.length === 0 ? (
          <Content>
            <Content component={ContentVariants.p}>Aucune donnée disponible.</Content>
          </Content>
        ) : (
          <div
            ref={patrimoineChartRef}
            style={{ width: '100%', height: 340, position: 'relative', userSelect: 'none' }}
            onMouseDown={startBrush}
            onMouseMove={moveBrush}
            onMouseUp={endBrush}
            onMouseLeave={() => { if (brush?.active) setBrush(null); setCrosshair(null); }}
          >
            {brush?.active && brush.chartId === 'patrimoine' && (
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
            {crosshair && !brush?.active && (
              <>
                {/* Vertical crosshair line */}
                <div
                  data-testid="crosshair-line"
                  style={{
                    position: 'absolute',
                    left: crosshair.xPx,
                    top: 10,
                    width: 1,
                    height: 'calc(100% - 80px)',
                    borderLeft: '1px dashed rgba(60,63,66,0.5)',
                    pointerEvents: 'none',
                    zIndex: 11,
                  }}
                />
                {/* Tooltip */}
                <div
                  data-testid="crosshair-tooltip"
                  style={{
                    position: 'absolute',
                    left: crosshair.xPx + 8 > crosshair.containerWidth - 150
                      ? crosshair.xPx - 140
                      : crosshair.xPx + 8,
                    top: 16,
                    background: 'rgba(21,21,21,0.85)',
                    color: '#fff',
                    borderRadius: 4,
                    padding: '4px 8px',
                    fontSize: '0.78rem',
                    pointerEvents: 'none',
                    zIndex: 12,
                    whiteSpace: 'nowrap',
                  }}
                >
                  <div>{crosshair.date.toLocaleDateString('fr-FR')}</div>
                  <div style={{ fontWeight: 'bold' }}>{formatEUR(crosshair.value)}</div>
                </div>
              </>
            )}
            <Chart
              ariaDesc="Évolution du patrimoine"
              ariaTitle="Patrimoine"
              height={340} width={chartWidth}
              padding={{ bottom: 70, left: 55, right: 10, top: 10 }}
              domain={{ y: [minVal * 0.95, maxVal * 1.02] }}
              themeColor={ChartThemeColor.blue}
              containerComponent={
                <VictoryZoomContainer
                  zoomDomain={zoomPatrimoine}
                  onZoomDomainChange={(domain: any) => { if (!brush?.active) { setZoomPatrimoine(clampZoom(domain, MIN_ZOOM_PATRIMOINE_MS)); setIsManuallyZoomed(true); } }}
                  zoomDimension="x" allowPan={false} allowZoom={false}
                />
              }
            >
              <ChartAxis {...makeAxisStyle(zoomPatrimoine)} />
              <ChartAxis dependentAxis tickFormat={(y: number) => y >= 1000 ? `${(y / 1000).toFixed(0)}k€` : `${y}€`} style={depAxisStyle} />
              <ChartGroup>
                <ChartArea data={patrimoineData} interpolation="monotoneX" />
              </ChartGroup>
            </Chart>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
