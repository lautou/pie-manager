// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Shared hover-crosshair tooltip for custom time-series charts (drag-to-zoom + a vertical
 * dashed guide line + a compact dark tooltip: date header, then one colored-bullet row per
 * series). Extracted from IndexChart.tsx so every chart renders the exact same tooltip style
 * instead of falling back to Victory's default flyout (verbose legend names, no bullets, no
 * date) — see CLAUDE.md's "Custom drag-to-zoom chart checklist".
 */

export interface ChartCrosshairSeries {
  name: string;
  value: number;
  color: string;
}

export type ChartCrosshairState = {
  xPx: number;
  date: Date;
  series: ChartCrosshairSeries[];
  containerWidth: number;
} | null;

interface ChartCrosshairProps {
  crosshair: ChartCrosshairState;
}

export default function ChartCrosshair({ crosshair }: ChartCrosshairProps) {
  if (!crosshair) return null;

  return (
    <>
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
      <div
        data-testid="crosshair-tooltip"
        style={{
          position: 'absolute',
          left: crosshair.xPx + 8 > crosshair.containerWidth - 160
            ? crosshair.xPx - 160
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
        <div style={{ marginBottom: 2, fontSize: '0.75rem', color: '#ccc' }}>
          {crosshair.date.toLocaleDateString('fr-FR')}
        </div>
        {crosshair.series.map((s) => (
          <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, backgroundColor: s.color, flexShrink: 0 }} />
            <span>{s.name}: </span>
            <span style={{ fontWeight: 'bold' }}>{s.value.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </>
  );
}
