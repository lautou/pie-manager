// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Shared drag-to-zoom helpers for custom time-series Victory charts (mirrors
 * PerformancePage.tsx's makeAxisStyle/clampZoom). Extracted so every future chart pulls in
 * the same, already-correct tick granularity instead of re-deriving it — see CLAUDE.md's
 * "Drag-to-zoom chart checklist" for the full list of gotchas this encodes.
 */

export function clampZoomRange(domain: [Date, Date], minMs: number): [Date, Date] {
  const [s, e] = domain;
  const diff = e.getTime() - s.getTime();
  if (diff < minMs) {
    const center = (s.getTime() + e.getTime()) / 2;
    return [new Date(center - minMs / 2), new Date(center + minMs / 2)];
  }
  return domain;
}

/**
 * Adaptive tick format + Victory axis style for a zoomable time-series chart. Only two
 * granularities — day (zoomed to < 90 days) and month — never year-only: a year-only format
 * silently produces duplicate-looking ticks ("2001 2001 2001") once the chart is zoomed to a
 * span of roughly 1-3 years, since several evenly-spaced ticks then legitimately fall within
 * the same calendar year.
 */
export function timeAxisStyle(zoomDomain: [Date, Date] | undefined) {
  const zoomDays = zoomDomain
    ? (zoomDomain[1].getTime() - zoomDomain[0].getTime()) / 86_400_000
    : Infinity;
  return {
    tickFormat: (d: Date) => {
      const dt = d instanceof Date ? d : new Date(d);
      const yy = dt.getFullYear();
      const mm = String(dt.getMonth() + 1).padStart(2, '0');
      if (zoomDays < 90) {
        return `${yy}-${mm}-${String(dt.getDate()).padStart(2, '0')}`;
      }
      return `${yy}-${mm}`;
    },
    tickCount: 16,
    fixLabelOverlap: true,
    style: {
      tickLabels: { fontSize: 10, angle: -45, textAnchor: 'end' as const },
      grid: { stroke: '#d4d4d4', strokeWidth: 0.5 },
    },
  };
}
