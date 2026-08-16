---
paths:
  - "frontend/src/components/*Chart*.tsx"
  - "frontend/src/utils/chartZoom.ts"
  - "frontend/src/pages/PerformancePage.tsx"
  - "frontend/src/pages/RatioIndicatorChart.tsx"
---

## Custom drag-to-zoom chart checklist — read before building the next one

`RatioIndicatorChart.tsx` (Indicateurs macro page) is the second hand-rolled drag-to-zoom
chart in this app after `IndexChart.tsx`/`PerformancePage.tsx` (Performance page), and its
first build shipped 3 separate regressions that IndexChart's already-working implementation
doesn't have. All three came from re-deriving IndexChart's behavior from memory instead of
reusing/re-reading it. **`frontend/src/utils/chartZoom.ts` (`clampZoomRange`, `timeAxisStyle`)
now holds the shared, tested logic for #2 and #3 below — import it, don't re-derive it.** The
period-preset-button row (1M/3M/1Y/YTD/5Y/10Y/MAX) is the other reusable piece; copy its JSX
shape from `RatioIndicatorChart.tsx` for the next chart. `IndexChart.tsx` itself still has its
own separate, older copies of this logic (not yet migrated to the shared util — do that the
next time you touch it, but it isn't broken today so it wasn't done opportunistically here).

1. **Responsive width: measuring a ref in a `useEffect([])` when that ref mounts
   conditionally.** The standard pattern in this codebase is:
   ```tsx
   const containerRef = useRef<HTMLDivElement>(null);
   const [chartWidth, setChartWidth] = useState(900);
   useEffect(() => {
     const el = containerRef.current;
     if (!el) return;
     setChartWidth(Math.floor(el.getBoundingClientRect().width));
     const ro = new ResizeObserver(([entry]) => setChartWidth(Math.floor(entry.contentRect.width)));
     ro.observe(el);
     return () => ro.disconnect();
   }, []);  // ← BUG: empty deps
   ```
   If `<div ref={containerRef}>` only renders once loading finishes (`isLoading ? <Spinner/> :
   ... : <div ref={containerRef}>` — true for every chart in this app), `containerRef.current`
   is still `null` on the first render, the effect's `if (!el) return;` bails out, and the
   `ResizeObserver` is **never created**. When the container later mounts for real, the effect
   does **not** re-run (empty deps), so `chartWidth` stays frozen at its default forever —
   confirmed by reading the live SVG's `viewBox` in the browser (`document.querySelectorAll
   ('svg')`), which read `"0 0 900 320"` regardless of window size, while `clientWidth`
   changed on resize. The chart still *looks* right (Victory always CSS-scales its SVG to fill
   the container regardless of the `width` prop) — invisible until something does pixel math
   against the *real* screen size, at which point drag-to-zoom lands on a shifted, wrong date
   range. **Rule:** depend on whatever gates the ref's conditional render (e.g. `[isLoading,
   hasData]`), never `[]`, unless the ref'd element is unconditionally present on mount. This
   exact latent bug is still present in `PerformancePage.tsx`'s `chartContainerRef` — not yet
   fixed there since it wasn't the one reported broken, but do fix it opportunistically if that
   file is ever touched again.

2. **Native text-selection during the drag.** `victory-zoom-container`'s `onMouseDown` calls
   `evt.preventDefault()` *unconditionally* — even with `allowPan={false} allowZoom={false}`
   set (confirmed by reading `node_modules/victory-zoom-container/es/zoom-helpers.js`). A
   hand-rolled brush handler that skips this has **no** default protection against native
   browser drag-selection: the whole drag highlights every text node it passes over (axis
   labels, legend) with the browser's native selection color, layered underneath the intended
   brush rectangle. `userSelect: 'none'` on the container div is not sufficient by itself in
   every rendering engine (confirmed absent from both `IndexChart.tsx` and
   `RatioIndicatorChart.tsx`, yet only the latter showed the bug — the WebKitGTK-based Linux
   desktop wrapper, see `.claude/rules/distribution.md`'s "Native window integration" section,
   is the likely difference from a Chromium-based dev-browser test, which is why this survived
   a Chromium/Playwright
   verification pass). **Rule:** always call `e.preventDefault()` in the mousedown/brush-start
   handler itself — don't rely on CSS `user-select` alone, and don't assume a Chromium-based
   test catches this class of cross-engine rendering difference.

3. **Axis tick format must never be year-only.** A format that shows only the year once
   zoomed out past some threshold produces visibly duplicated labels ("2001 2001 2001 2002
   2002 2002") the moment the zoomed span covers roughly 1-3 years, since several
   evenly-spaced ticks then legitimately fall within the same calendar year. `timeAxisStyle`
   in `chartZoom.ts` only ever has two tiers — day-level (`yyyy-mm-dd`, zoomed to < 90 days) or
   month-level (`yyyy-mm`, everything else, including fully unzoomed) — plus `tickCount: 16`,
   `fixLabelOverlap: true`, and 45°-angled right-anchored labels, matching
   `PerformancePage.tsx`'s `makeAxisStyle` exactly. Use it for any new time-series chart
   instead of writing a fresh `tickFormat`.

4. **Preset-period buttons and the manual "↺ Réinitialiser zoom" button are both required, and
   are not the same control.** Clicking a preset (including MAX) always clears the "manually
   zoomed" state; a completed drag always sets it and clears the active preset. The reset
   button is shown *only* when a manual drag is active (no preset button highlighted) — it is
   not redundant with clicking MAX, because after a manual drag none of the preset buttons
   visually suggest "click here to get back". Removing it in favor of "just click MAX" was
   tried and explicitly reverted after user feedback — keep both.

5. **Hover tooltip: use the shared `ChartCrosshair` component, never Victory's default flyout
   (`ChartVoronoiContainer`/`ChartTooltip`).** The project's established tooltip style is a
   custom crosshair: a vertical dashed guide line + a dark rounded box showing a date header
   plus one row per series with a small colored bullet, short series name, and bold value —
   originally built inline in `IndexChart.tsx`, now extracted to
   `frontend/src/components/ChartCrosshair.tsx` and reused as-is by `RatioIndicatorChart.tsx`.
   Victory's own `ChartVoronoiContainer`/default flyout renders full legend-length text (e.g.
   "Croissance — Ratio (base 100)") with no color bullets and no shared styling — visibly
   inconsistent the moment two chart types sit near each other in the UI. **Rule:** for any new
   time-series chart, track the nearest data point by date on `mousemove` (skip this while a
   zoom-brush drag is active) and render `<ChartCrosshair crosshair={...} />` with **short**
   series names (no "(base 100)"/"(N ans)"/unit suffixes — those stay in the static legend
   below the chart, not the tooltip) — don't wire up `ChartVoronoiContainer` at all.

