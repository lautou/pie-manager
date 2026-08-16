---
paths:
  - "frontend/src/pages/GlobalConfigPage.tsx"
  - "frontend/src/components/SettingField.tsx"
  - "backend/app/tasks/macro_indicators.py"
  - "backend/app/api/routers/products.py"
  - "frontend/src/components/ChartCrosshair.tsx"
  - "frontend/src/components/RatioIndicatorChart.tsx"
  - "frontend/src/components/IndexChart.tsx"
  - "frontend/src/pages/PerformancePage.tsx"
  - "frontend/src/components/MarketPerformanceSection.tsx"
  - "frontend/src/components/GrowthInflationSection.tsx"
  - "backend/app/services/country_performance_service.py"
  - "backend/app/tasks/yahoo_fetch.py"
  - "backend/app/tasks/prices.py"
  - "backend/app/tasks/etf_holdings.py"
---

## Macro indicators — growth/inflation ratio page (portfolio-independent)

New global page `/indicators` (outside `/portfolio/:id/*`, uses `GlobalLayout` like `/config`)
showing two "base 100" ratio charts with a rolling moving average, for a selectable **region**:
**growth** (region equity index / WTI oil `CL=F`, oil shared across regions) and **inflation**
(region government bond ETF / gold `GC=F`, gold shared across regions). Ratio below its own
moving average = recession / inflationary regime, per the user's macro reading — this is a
display convention, not something the backend interprets. Each chart's legend spells out the
real "X / Y (base 100)" ratio using **human-readable descriptive names** (e.g. "CAC 40 /
Pétrole (WTI)"), never the raw Yahoo ticker (e.g. "^FCHI / CL=F" means nothing to a
non-technical reader) — see `equity_label`/`bond_label` below. Falls back to the raw ticker
only if a label is ever empty (defensive, shouldn't happen since the fields are required in
the UI). Also shows a one-line interpretation of what "above"/"below" means for that pair
(gold vs. bonds, equities vs. energy) — sourced from i18n, not hardcoded per region.

**Inflation deliberately uses bond ETF *prices*, never a yield**, uniformly across all
regions — a yield and a bond price move inversely, so mixing a yield-based region with
price-based ones would flip the "ratio below MA" reading's direction between regions.

**Regions are a user-managed CRUD list, not a hardcoded set.** `MacroRegion` model
(`code` PK, `label`, `equity_ticker`, `bond_ticker`, `equity_label`, `bond_label`) is managed
entirely from **Configuration générale** (`GlobalConfigPage.tsx`'s `RegionManager`, mirroring
`ProductManager`'s table + modal + `ConfirmModal`-delete shape) — the user adds/edits/removes
regions themselves, no code change needed. `code` is immutable once created (it doubles as the
`macro_series_prices` series-key prefix: `f"{code}_equity"`/`f"{code}_bond"` — renaming it
would orphan history). `equity_label`/`bond_label` (e.g. "CAC 40", "Obligations zone euro
10-15 ans") are required fields in the add/edit form — the whole point of the feature is a
human-readable legend, so leaving them optional would silently regress to raw tickers for any
region the user forgets to fill in. Deleting the last remaining region is rejected (the page
must always have at least one). Seeded regions (migration `pp99qq00rr11`, labels backfilled by
`qq00rr11ss22`):

| Region | Growth (equity) | Inflation (bond ETF) |
|---|---|---|
| US | `^SPXEW` "S&P 500 Equal Weight" | `GOVT` "Obligations Trésor américain" (iShares U.S. Treasury Bond ETF) |
| France | `^FCHI` "CAC 40" (see data-gap gotcha below) | `MTE.PA` "Obligations zone euro 10-15 ans" (Amundi Euro Government Bond 10-15Y — **Eurozone, not pure France OAT**) |
| Monde | `MWEQ.L` "Actions Monde (Equal Weight)" (Invesco MSCI World Equal Weight UCITS ETF) | `BNDW` "Obligations Monde" (Vanguard Total World Bond ETF) |

The shared oil/gold tickers get the same treatment: `macro.ticker.oil.label`/
`macro.ticker.gold.label` SystemSetting keys (default "Pétrole (WTI)"/"Or"), surfaced as two
more `SettingField`s next to the existing ticker fields in the same "Indicateurs macro" card —
`get_macro_settings(db)` returns them as `oil_label`/`gold_label` alongside the existing
`oil`/`gold` ticker keys.

**Two Yahoo tickers were confirmed dead via real QA testing, not caught by mocked unit
tests** — always empirically curl-verify a ticker's chart history depth before adopting it:
- The raw MSCI World Equal Weighted index code `^129857-USD-STRD` returns a live quote on
  Yahoo but **zero historical chart data** (confirmed via explicit `period1`/`period2` even
  over a 10-year window — only 1 point, today, ever comes back). Replaced by `MWEQ.L`, the
  equal-weight ETF tracking the same index (real daily history, ~470 points since Sept 2024).
- `^SBF120` (originally used for France) has **zero chart history from 2016 onward**
  (confirmed via narrow 2016-2018 and 2020-2021 windows, both 0 points) — visible on the
  frontend as the growth ratio line flattening to a constant value once the underlying series
  stops updating. Replaced by `^FCHI` (CAC 40), verified to have a continuous 26-year daily
  history with no gaps.

Single generic table `macro_series_prices` (`series`, `date`, `value`, unique on
`(series, date)`), decoupled from `products`/portfolios and from the region list itself —
`compute_ratio_indicator(db, numerator_series, denominator_series, ma_years)` only ever sees
plain series-key strings, with no notion of "region" at all. This is why generalizing from a
single hardcoded region to 3, then to a fully dynamic N-region CRUD system required **zero**
changes to this function — validating the payoff of keeping it series-key-based from the start.
The moving average is a time-based (not point-count) O(n) sliding window, since fixed-N-point
windows are imprecise once holidays/gaps exist in the series.

Oil/gold tickers + the moving-average duration (default 7 years, **one setting shared by every
region's charts**, not per-graph) are configurable via the generic `SystemSetting` key/value
store (`macro.ticker.oil`, `macro.ticker.gold`, `macro.ma_years`) — surfaced as `SettingField`
inputs (shared component, `frontend/src/components/SettingField.tsx`) under **Configuration
générale**'s "Indicateurs macro" card, alongside the region table. Nothing is hardcoded: adding
a region or changing a ticker/MA-duration never requires a code change.

`GET /api/indicators/growth|inflation` take a `region` query param, 404 on an unknown region
code (a real missing resource, not a fixed-enum check) — response includes both the resolved
`numerator_ticker`/`denominator_ticker` (raw tickers, kept for reference) and
`numerator_label`/`denominator_label` (the descriptive names the frontend actually renders in
the legend) so the frontend never needs to duplicate region/settings data to build either.
`GET/POST/PUT/DELETE /api/indicators/regions` mirror `products.py`'s CRUD shape.

**Critical data-source gotcha**: `app/tasks/macro_indicators.py` fetches full history every run
using **explicit `period1`/`period2` Unix-timestamp params**, never `range=max`. Confirmed
empirically: `range=max&interval=1d` gets silently downsampled by Yahoo to ~monthly granularity
for long spans (only ~168 points over 42 years for `^GSPC`), while explicit `period1`/`period2`
returns true uncapped daily data (6500+ points over 26 years). Re-fetching full history each run
(not just "today") is cheap and self-heals gaps/revisions, mirroring the ETF holdings task's
replace-on-fetch approach. Runs daily via PgQueuer (`0 5 * * *` UTC) plus once at backend
startup — see `.claude/rules/background-jobs.md` for the Celery→PgQueuer cutover and the cron
UTC-shift gotcha. The task builds its fetch list from `list_regions(db)` at runtime plus
oil/gold — it scales to however many regions exist, no hardcoded ticker count anywhere.

Manual trigger (`POST /api/indicators/refresh`) + status polling
(`GET /api/indicators/sync-status`, backed by the `job_runs` table, not Redis — see
`.claude/rules/background-jobs.md`) mirror the ETF holdings task's pattern rather than
price-sync's fixed-4s-guess, since a full refetch's duration isn't a safe constant to assume.
There is no manual "Actualiser maintenant" button on the page itself
(removed — daily auto-sync makes a manual trigger low-value); the endpoint remains for ops/curl
use, and the page still shows "Dernière synchro" and auto-invalidates its queries when a sync
completes.

**Chart zoom** (`RatioIndicatorChart.tsx`) mirrors `IndexChart.tsx`'s characteristics
end-to-end: drag-to-select via raw mouse events with `e.preventDefault()` on mousedown, a
translucent brush overlay, a `MIN_ZOOM_MS` floor, a shared `ChartCrosshair` hover tooltip
(colored bullet + short series name + value, date header — see `frontend/src/components/
ChartCrosshair.tsx`, also used by `IndexChart.tsx`), and **both** a preset-period button row
(1M/3M/1Y/YTD/5Y/10Y/MAX, same set as `PerformancePage.tsx`'s time scale selector) **and** a
separate "↺ Réinitialiser zoom" button shown only while a manual drag is active (no preset
highlighted) — see `.claude/rules/chart-zoom.md`'s "Custom drag-to-zoom chart checklist" for why
these two controls are not interchangeable. It deliberately has no `containerComponent`/
`VictoryZoomContainer` at all: the custom mouse handlers on the wrapping `<div>` do all the work
(brush AND crosshair), so Victory's own container is unnecessary. Clicking a preset anchors the
range on the **dataset's latest point** (`data.dates[last]`), not `new Date()`, since this data
only updates via the nightly PgQueuer sync. A manual drag clears the active-preset highlight (it
rarely lands exactly on a preset boundary). See `.claude/rules/chart-zoom.md` — every item in it
was found and fixed while responding to live user bug reports against this exact chart, in the
order: wrong zoom range → native text-selection during drag → duplicate axis year labels →
missing reset button → verbose Victory-default hover tooltip.

## Country market performance leaderboard (portfolio-independent)

Second tab on the Indicateurs page ("Performance des marchés", `MarketPerformanceSection.tsx`),
deliberately kept separate from the growth/inflation tab (`GrowthInflationSection.tsx`) via
PatternFly `Tabs` — a static ranked bar chart (categorical x-axis, no time series) has nothing
in common with the region-scoped ratio line charts, so mixing them on one view was rejected.

**Ranking**: `country_performance_service.compute_country_performance()` ranks every configured
`CountryPerfConfig` row by trailing-1-year, **EUR-adjusted** performance —
`(index_latest × fx_latest) / (index_anchor × fx_anchor) − 1`, multiplicative (never additive,
since a local-currency move and an FX move compound). EUR-currency countries skip the FX
factor entirely. Only the top N (`SystemSetting country_perf.top_n`, default 15) are returned,
sorted ascending for the chart (worst-of-the-top-N left, best right). A country whose index or
FX series has no snapshot within `ASOF_TOLERANCE_DAYS` (10) of "today" or "~1 year ago" is
excluded from ranking rather than distorting it with stale data.

**Storage reuses `MacroSeriesPrice`** (no new price table) via a distinct series-key
namespace: `country_{code}_equity` per country, `fx_{currency}` per **distinct non-EUR
currency** (shared/deduped across countries with the same currency). `CountryPerfConfig`
(code/label/index_ticker/currency/index_label) is a separate, user-editable table — no "last
remaining row" delete guard, unlike `MacroRegion` (an empty universe just yields an empty
chart).

**`index_label`** (e.g. "KOSPI Composite", "CAC 40", "Shanghai Composite") is a
human-readable name for `index_ticker`, mirroring `MacroRegion.equity_label`/`bond_label` —
added via migration `ss22tt33uu44` after comparing our leaderboard against an external
reference chart revealed that different sources track different underlying indices for the
same country (e.g. Shenzhen vs Shanghai for "Chine"). Shown in the chart's hover tooltip
(`"{country} — {index_label}: {pct}%"`) and as its own column in `MarketCountryManager`, so
which index feeds a bar is never ambiguous.

**Shared Yahoo fetch helper**: `app/tasks/yahoo_fetch.py` (`fetch_yahoo_chart`/
`fetch_yahoo_history`) was extracted here from what used to be near-identical private copies in
`prices.py`/`macro_indicators.py`/`etf_holdings.py` — this task was the third occurrence of the
same duplication, the trigger for finally factoring it out. The equivalent Redis-status helper,
`app/tasks/sync_status.py` (`get_redis`/`write_status`), was deleted in the PgQueuer cutover
(issue #66) — status for these 4 tasks now goes through the shared `job_runs` table instead, see
`.claude/rules/background-jobs.md`.

**Seed list ticker gotchas** (found via empirical Yahoo verification before trusting the
migration seed, same discipline as `^SBF120` above): Poland's `WIG20.WA` returns exactly 1
data point regardless of window (dead) — replaced with `ETFBW20TR.WA`, an ETF tracking the
same index. Taiwan (TWD) and Turkey (TRY) are excluded from the seed entirely: their direct
`{CCY}EUR=X` crosses (`TWDEUR=X`, `TRYEUR=X`) are also always 1 point — only the *reverse*
cross (`EURTWD=X`/`EURTRY=X`) has real history, which would need a per-currency reciprocal
special case to support, not worth it for 2 currencies.

**Known pitfall — aria-label collisions between independent CRUD managers on the same
page**: `MarketCountryManager`'s edit/delete buttons originally used the same
`"{action} {code}"` aria-label pattern as `RegionManager`'s. Since both managers can have a
row with the same code (e.g. `fr`, seeded in both `macro_regions` and
`country_perf_configs`), their buttons collided (`"Modifier fr"` × 2) on the same
Configuration générale page — a real accessibility bug and a Playwright strict-mode
violation, only caught by a live browser check (unit tests used non-overlapping fixture
codes, which hid it). Fixed by adding a disambiguating noun (`"Modifier pays fr"`). When
adding a second CRUD table whose codes can overlap with an existing one on the same page,
disambiguate the action labels up front.

