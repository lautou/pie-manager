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
  - "backend/app/services/sector_performance_service.py"
  - "backend/app/services/performance_math.py"
  - "backend/app/tasks/sector_performance.py"
  - "backend/app/api/routers/sector_performance.py"
  - "frontend/src/components/SectorPerformanceSection.tsx"
  - "frontend/src/components/PerformanceBarChart.tsx"
  - "backend/app/models/equity_premium.py"
  - "backend/app/services/equity_premium_service.py"
  - "backend/app/tasks/equity_premium.py"
  - "backend/app/api/routers/equity_premium.py"
  - "frontend/src/components/EquityPremiumSection.tsx"
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

Second tab on the Indicateurs page (visible label "Performance des actions" — renamed from
"Performance des marchés" for clarity once the third tab stopped being commodity-only; the
component/table/route names still say "country"/"market" throughout, a deliberate
display-only rename, not worth the churn of renaming an already-populated live table/route),
`MarketPerformanceSection.tsx`,
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
excluded from ranking rather than distorting it with stale data. **The `asof()` lookup and the
actual multiplicative-FX math now live in the shared `app/services/performance_math.py`**
(extracted when `sector_performance_service.py` needed the identical computation for a second,
unrelated universe — see the "Sector performance" section below) — this service only owns the
CRUD, the per-currency FX cache, and the Top-N select/re-sort around it.

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

## Sector performance leaderboard (portfolio-independent)

Third tab on the Indicateurs page — visible label **"Performance des classes d'actifs"**,
renamed from "Performance par secteur" once the universe grew past pure commodities to include
currencies, equities, bonds, private equity, and crypto (see "Live-edited universe" below).
`SectorPerformanceSection.tsx`, a full CRUD mirror of the country leaderboard above — same
trailing-1-year EUR-adjusted math, same CRUD/manager shape — with one structural difference:
there's no Top-N/ranking concept at all. `sector_performance_service.compute_sector_performance()`
returns *every* configured `SectorPerfConfig` row that has valid data, sorted ascending by
`perf_pct` for the chart's left-to-right display — no truncation, whatever the universe size.
This is why `SectorManager` (the admin CRUD component, `GlobalConfigPage.tsx`) has no Top-N
`SettingField` next to it, unlike `MarketCountryManager`'s `country_perf.top_n`. Internal
identifiers (component/service/table/route names, i18n key namespace `sectorPerformance.*`)
all still say "sector" — a deliberate display-only rename, not worth the churn of renaming an
already-populated live table/route for a purely cosmetic change.

**Both the country and sector charts render through the same generic component,
`PerformanceBarChart.tsx`** (renamed from `CountryPerformanceChart.tsx` when this tab was
added — the component's own internals were always fully generic, only its name implied
country-specific data). `types/index.ts`'s `PerformanceEntry` is the single shared shape both
`CountryPerformanceEntry` and `SectorPerformanceEntry` alias.

**Original migration seed (`ww66xx77yy88`) — deliberately 4 commodity-ish rows, chosen to be
mutually non-overlapping.** Superseded since via live CRUD edits (see "Live-edited universe"
below) — kept here as a historical record of the initial ticker research, not the current
live state (this is user-managed data now, not something a doc snapshot should claim to
track — check `GET /api/indicators/sector-performance/sectors` for the actual current rows):

| code | label | ticker | Why this ticker, not a broader "commodities" ETF |
|---|---|---|---|
| `or` | Or | `GC=F` | Same ticker already used by the growth/inflation ratio's shared "gold" series (see above) — proven long-running history. |
| `petrole` | Pétrole | `CL=F` | Same ticker already used by the growth/inflation ratio's shared "oil" series. |
| `metaux` | Métaux industriels | `DBB` (Invesco DB Base Metals Fund) | — |
| `agriculture` | Agriculture | `DBA` (Invesco DB Agriculture Fund) | — |

A single "broad commodities" ETF (DBC, GSG, or the raw `^SPGSCI` index) was considered and
**rejected** for "Métaux industriels"/"Agriculture": every one of them embeds a real,
non-trivial precious-metals weight (DBC's live holdings, checked directly: ~5% Gold Future +
~1% Silver Future ≈ 12% of its actual commodity sleeve once cash/T-Bill collateral is excluded)
— using one would make that bar redundant with "Or" instead of a distinct signal. `DBB`/`DBA`
(Invesco's own mono-sector funds — the same family DBC is built from) contain **no** precious
metals and **no** energy, giving 4 genuinely orthogonal categories. A dedicated Bloomberg
ex-precious-metals index, `^BCOMXPM`, was also found and rejected: it resolves as a real Yahoo
symbol (metadata, a `longName`) but is **dead** — `regularMarketTime` frozen at May 2020,
`validRanges` collapsed to `["1d","5d"]` — the same dead-ticker signature as `^SBF120` earlier
in this file. All 4 seed tickers were verified live via Yahoo's chart endpoint before adoption:
`GC=F`/`CL=F` already proven elsewhere in this codebase; `DBB`/`DBA` confirmed with 4938 daily
points since 2007-01-05, fresh through 2026-08-21.

**Deliberately does NOT reuse the existing "gold"/"oil" `macro_series_prices` series**, even
though `or`/`petrole` fetch the exact same tickers (`GC=F`/`CL=F`) the growth/inflation ratio
already fetches under those series keys. Each `SectorPerfConfig` row — including `or`/
`petrole` — independently fetches its own ticker into its own `sector_{code}_equity` series
(`app/tasks/sector_performance.py`, structurally identical to `country_performance.py`'s task).
This was a deliberate trade: a small redundant daily Yahoo fetch, in exchange for a fully
generic, symmetric CRUD entity with zero special-casing between rows — consistent with how
`MacroRegion` and `CountryPerfConfig` already coexist as fully independent tables that can
track overlapping real-world entities (e.g. both have a "France"/`fr`-shaped row) without ever
cross-referencing each other.

**Series-key namespace**: `sector_{code}_equity` per sector (mirrors `country_{code}_equity`),
`fx_{currency}` per distinct non-EUR currency — same shared/deduped-per-currency convention as
country performance (in practice, since every seed row is USD, this means one shared `fx_usd`
fetch, but the code stays currency-generic, never hardcoded to USD).

**PgQueuer**: `refresh_sector_performance` runs on `30 5 * * *` UTC (05:30) — 15 minutes after
`refresh_country_performance`'s own `15 5 * * *` (05:15), continuing the existing
macro_indicators (05:00) → country_performance (05:15) → sector_performance (05:30) stagger so
three daily Yahoo-hitting jobs never fire at once. See `.claude/rules/background-jobs.md` for
the general PgQueuer schedule/entrypoint pattern this follows exactly.

**`SectorManager`'s edit/delete aria-labels use `"secteur {code}"`** (e.g. `"Modifier secteur
or"`), following the same disambiguation convention as `MarketCountryManager`'s `"pays
{code}"` above — applied defensively even though sector codes (`or`/`petrole`/`metaux`/
`agriculture`) don't currently collide with any 2-3-letter region/country code.

**Found only via a real Postgres integration test, not the pytest suite's `create_all`-based
fixtures**: `macro_series_prices.series` was `VARCHAR(20)` — plenty for `country_{code}_equity`
(country codes are 2-3 chars) but not for `sector_{code}_equity` once `SectorPerfConfig.code`
allows up to 20 chars (French-word slugs, not ISO codes) — `sector_agriculture_equity` alone is
25 characters. A real `INSERT` failed with `StringDataRightTruncationError`; SQLAlchemy's
Python-side `String(20)` type has no client-side length enforcement, so nothing caught this
until a real Postgres container ran the actual `INSERT`. Fixed by widening the column to
`VARCHAR(40)` (migration `xx77yy88zz99`) — comfortably covers every current and near-future
series key shape. Reinforces `.claude/rules/alembic-migrations.md`'s standing rule: always
verify a real migration against a throwaway Postgres container, never trust `create_all`-based
test fixtures alone for a schema change like this.

**Live-edited universe — grown well past the original 4-commodity seed via the admin CRUD UI
directly (no migration involved; new rows are ordinary user data, added/edited/deleted through
`SectorManager`/the API exactly like any other `SectorPerfConfig` row).** This is *why* the tab
was renamed to "Performance des classes d'actifs" — once the universe includes currencies,
equities, bonds, private equity, and crypto, "secteur" (sector) stopped being an accurate
description. Ticker research for each addition, in case a future edit needs to re-derive or
re-verify:

- **Or, replaced `GC=F` → `GLD`** (SPDR Gold Shares): switched from the raw futures
  contract to a physically-backed gold ETC/ETF proxy. Physical gold ETCs (iShares Physical
  Gold, SPDR Gold Shares, etc.) track the **LBMA Gold Price** (the official London gold
  benchmark), not a futures curve — `GLD` and `IAU` (iShares Gold Trust, lower fee, near-
  identical) are the two standard USD-denominated choices, both with real history since 2005.
- **Valeurs pétrolières (`energie`) → `XDW0.L`** (Xtrackers MSCI World Energy UCITS ETF):
  tracks the **MSCI World Energy Index** by name — holdings include Exxon Mobil (~19%),
  Chevron (~11%), Shell (~7%), TotalEnergies (~5%). This is equities of oil/gas *companies*,
  a deliberately different asset class from a commodity-futures "Pétrole" bar (which was
  removed entirely — `CL=F`/WTI is no longer tracked anywhere on this chart). Real history
  since 2010. `IXC` (iShares Global Energy ETF) was considered first but tracks an S&P index,
  not MSCI — swapped once the user specifically wanted an MSCI-branded index.
- **USD Monétaire → `XFFE.L`** (Xtrackers II USD Overnight Rate Swap UCITS ETF, accumulating
  share class): tracks the **Solactive FEDL Daily Total Return Index** (the US Fed Funds
  Effective Rate, compounded daily). **Critical gotcha found and avoided**: a plain USD
  money-market/T-bill ETF (`BIL`, `SGOV`) was tried first and rejected — these *distribute*
  their yield as cash dividends rather than accruing it into NAV, so their raw close price is
  designed to stay flat (confirmed live: `BIL`'s close moved only -0.065% over ~13 months
  despite a real ~4-5% yield). Since this app's price-fetching (`fetch_yahoo_history`) only
  ever reads unadjusted `close`, never dividends/`adjclose`, a distributing fund would show a
  near-zero, misleading "performance" here. `XFFE.L` is an *accumulating* (1C) share class —
  its price genuinely rises with the accrued rate (confirmed live: +4.2% over ~13 months,
  consistent with real short rates) — so it works correctly with this app's price-only
  convention. **Any future "cash-like" asset-class addition must check
  accumulating-vs-distributing before adopting a ticker**, not just verify it has history.
- **MSCI World → `^990100-USD-STRD`**: the raw MSCI World Index itself (not an ETF wrapper) —
  longest available history (since 2005) among MSCI World trackers checked (`URTH` since 2012,
  `IWDA.L` since 2009).
- **Immobilier → `RWO`** (SPDR Dow Jones Global Real Estate ETF): a **non-MSCI** fallback —
  searched specifically for an "MSCI World Real Estate"-branded ETF first, since one exists as
  a named MSCI index, but found no clean currently-live product tracking it: iShares uses FTSE
  EPRA/NAREIT (`IWDP`) and SPDR uses Dow Jones (`RWO`) for their global real-estate sector
  funds; Xtrackers *used to* offer a literal "MSCI World Real Estate UCITS ETF" under ticker
  `XDRE`, but that ticker now resolves on Yahoo to a completely different fund — "Xtrackers
  Developed Green Real Estate ESG UCITS ETF" — with only ~1.5 years of history under its new
  ESG mandate. **A ticker that used to track index X can silently be repurposed to track a
  different index Y entirely, under the same ticker** — always re-check what a ticker
  *currently* tracks via a fresh web search/Yahoo `longName`, never trust an old citation.
- **Obligations → `BNDW`** (Vanguard Total World Bond ETF): reused deliberately — this exact
  ticker is already the "Monde" region's bond leg for the growth/inflation ratio chart (see
  the seed table near the top of this file). Same redundant-fetch trade-off already accepted
  for `or`/`petrole` above (a second, independent `sector_obligations_equity` series fetches
  the same ticker `country_performance`-style, rather than reusing the "Monde" region's
  existing series).
- **Private Equity → `PSP`** (Invesco Global Listed Private Equity ETF): tracks the **Red
  Rocks Global Listed Private Equity Index** — real private equity has no daily price by
  nature (illiquid), so this is the standard listed-PE-proxy approach (a basket of publicly
  traded PE firms/BDCs — Blackstone, KKR, Apollo, etc.). Real history since 2006.
- **Bitcoin → `BTC-USD`**: a direct Yahoo crypto ticker, no ETF/proxy needed. Real history
  since 2014.
- **Dette d'entreprises → `LQD`** (iShares iBoxx $ Investment Grade Corporate Bond ETF): the
  most liquid/longest-history (since 2005) investment-grade corporate bond ETF, deliberately
  distinct from "Obligations" above (government/aggregate bonds) so the two bars carry
  different, non-redundant credit-risk information. USD investment-grade only, not a truly
  global corporate-bond benchmark (`PICB`, ex-USD G10 corporates, is the international
  alternative but far less liquid) — accepted as the standard, most-recognized choice anyway.

## Equity risk premium leaderboard (portfolio-independent)

Fourth tab on the Indicateurs page, visible label **"Premium action"** — the implied Fed
Model/Damodaran equity risk premium (`earnings_yield − risk_free_rate`, 10-year government
bond convention), one bar per country: `premium_pct = (1/trailingPE − bond_yield) * 100`.
Green (`>= 0`) means equities look cheap relative to bonds; red means the opposite.
`EquityPremiumSection.tsx` reuses the same generic `PerformanceBarChart.tsx` as the two
leaderboards above, via a new opt-in `colorBySign` prop (green `#3E8635`/red `#C9190B`, the
same signed-value convention already used in `PerformancePage.tsx`/`AccountsSummaryPage.tsx`)
— the two existing charts pass nothing and stay on the uniform blue `BAR_COLOR`.

**Structurally the odd one out among the three leaderboard tabs — a point-in-time snapshot,
not a trailing-window return, and no FX anywhere.** `trailingPE`/bond `yield` are Yahoo
"current" fields with no historical date attached (unlike the chart endpoint's dated price
history), so `app/tasks/equity_premium.py` always writes `date.today()` as the single point
each run — `asof()`'s existing tolerance window (reused a 3rd time from
`performance_math.py`) absorbs a missed day exactly like every other series in this app. Both
legs (earnings yield, bond yield) are same-country, same-currency, dimensionless ratios
subtracted directly — `EquityPremiumConfig` deliberately has **no `currency` column**, the one
structural difference from `MacroRegion`/`CountryPerfConfig`/`SectorPerfConfig`, and
`compute_equity_premiums()` has no `TRAILING_WINDOW_DAYS`, no anchor date, no per-currency FX
cache — the single biggest simplification versus `compute_trailing_performance()`.

**Crumb-authenticated `quoteSummary`, not the plain chart endpoint** — a country equity ETF's
trailingPE and a country bond ETF's yield are only exposed via `quoteSummary`'s
`summaryDetail` module, never `fetch_yahoo_history`'s chart endpoint. This makes
`equity_premium.py` structurally closer to `etf_holdings.py` than to
`country_performance.py`/`sector_performance.py`. `get_yahoo_session_crumb`/
`fetch_quote_summary_module` were extracted from `etf_holdings.py` (their original, sole
owner) into the shared `app/tasks/yahoo_fetch.py` once this task needed the identical
mechanism for a second, unrelated module (`summaryDetail` vs. `topHoldings`/`assetProfile`) —
see `.claude/rules/etf-holdings.md` for the crumb endpoint's own `Accept: */*`/406 gotcha,
not re-explained here.

**Stores the computed ratio, never the raw P/E** — `1/trailingPE` (a decimal earnings yield)
and the raw decimal `summaryDetail.yield` are written straight to `MacroSeriesPrice`, so
`compute_equity_premiums()`'s own math is a plain subtraction with no division at read time.
Series-key convention: `premium_{code}_equity_yield` (max 24 chars) / `premium_{code}_bond_yield`
(max 22 chars) — both comfortably inside the `String(40)` `macro_series_prices.series` column
already widened for `sector_performance` above. **Don't confuse this prefix with
`country_{code}_equity`** (the country-leaderboard series for the same countries) — textually
distinct, but easy to eyeball-confuse when debugging `macro_series_prices` rows by hand for a
country present in both universes.

**Per-leg graceful failure, not per-country**: if a country's equity leg succeeds but its bond
leg fails (a transient Yahoo hiccup, or one of the excluded countries below if ever
re-added), the equity series is still written — `compute_equity_premiums()` excludes that
country at read time based on what's actually in the `macro_series_prices` table, so a leg
that starts working again self-heals with zero code change.

**PgQueuer**: `refresh_equity_premium` runs on `45 5 * * *` UTC (05:45) — continuing the
established stagger one slot past `refresh_sector_performance`'s `30 5 * * *`: macro_indicators
(05:00) → country_performance (05:15) → sector_performance (05:30) → equity_premium (05:45), so
4 daily Yahoo-hitting jobs never fire at once.

**`EquityPremiumManager`'s edit/delete aria-labels use `"prime {code}"`** (e.g. `"Modifier
prime de"`) — this is the one CRUD manager on the Configuration générale page where the
disambiguation convention (see the country-leaderboard section's "Known pitfall" above) is
not merely defensive: `EquityPremiumConfig`'s codes (`us`/`de`/`fr`/...) are deliberately the
*same* 2-3-letter country codes as `MacroRegion`'s and `CountryPerfConfig`'s, so a bare
`"{action} {code}"` label would collide with both on the same page.

**`EquityPremiumConfig` is the second CRUD table in this app with a "last remaining row"
delete guard** (`ValueError` if count ≤ 1), after `MacroRegion` — deliberately unlike
`CountryPerfConfig`/`SectorPerfConfig`, which have none:

| | `MacroRegion` | `CountryPerfConfig` | `SectorPerfConfig` | `EquityPremiumConfig` |
|---|---|---|---|---|
| Code shape | `[a-z0-9_]{2,20}` | `[a-z]{2,3}` | `[a-z]{2,20}` | `[a-z]{2,3}` |
| `currency` column | no (n/a) | yes | yes | **no** (no FX in this feature) |
| Last-row delete guard | **yes** | no | no | **yes** |
| Series-key shape | `{code}_equity`/`{code}_bond` | `country_{code}_equity` | `sector_{code}_equity` | `premium_{code}_equity_yield`/`premium_{code}_bond_yield` |

The guard exists here (and on `MacroRegion`) because an emptied table makes the entire tab
permanently blank with no chart at all — unlike `CountryPerfConfig`/`SectorPerfConfig`, where
an empty universe still degrades gracefully to a working, if empty, chart shell.

**Live-editable universe, not a closed list — same framing as the sector-performance universe
above.** The seed migration (`yy88zz99aa00`) covers 14 of the 23 "Performance des actions"
countries with confirmed working Yahoo data as of 2026-08; the other 9 are absent for one of
2 distinct root causes (re-verified live immediately before writing this doc, not from
memory), so a future contributor doesn't have to re-run this research from scratch if Yahoo
ever starts exposing one of them. **This list went through two verification passes**: the
first pass found 11 countries and wrongly excluded Hong Kong, India, and Singapore as
"no usable bond product" — a second, more thorough pass (re-searching each excluded country's
candidate bond ETFs rather than accepting the first pass's negative result) found real,
Yahoo-listed government/quasi-government bond ETFs for all three with live `summaryDetail.yield`
data, confirmed independently via direct `quoteSummary` calls before adding them. Lesson
reinforced: a first "no data found" pass for a country is not authoritative — see this file's
own "cherche bien sur le web" precedent for France/Germany/Switzerland/UK earlier in this same
feature's research, which needed the identical second-pass correction.

**14 confirmed rows** (equity ETF confirmed to expose `summaryDetail.trailingPE`, bond ETF
confirmed to expose `summaryDetail.yield`, both re-verified live via direct `quoteSummary`
calls the same day this migration was written):

| code | equity ETF | bond ETF |
|---|---|---|
| us | SPY | IEF |
| gb | EWU | IGLT.L |
| jp | EWJ | 236A.T |
| de | EWG | EXX6.DE |
| fr | EWQ | IFRB.L |
| ch | EWL | CSBGC0.SW |
| es | EWP | IS0P.DE |
| it | EWI | XBTP.MI |
| au | EWA | 5GOV.AX |
| cn | FXI | CNYB.AS |
| ca | EWC | XGB.TO |
| hk | EWH | 2819.HK (ABF Hong Kong Bond Index Fund) |
| in | INDA | INGB.AS (iShares India INR Government Bond) |
| sg | EWS | A35.SI (ABF Singapore Bond Index Fund) |

**9 excluded countries**, split by root cause. Only 2 distinct causes apply — an initial
"Hong Kong has no genuine sovereign bond market" theory did not survive verification (Hong
Kong does issue Exchange Fund Notes/Bills and a real tracking ETF exists, see above), so no
"structurally inapplicable" category is used here:

- **(a) a real bond ETF exists and resolves on Yahoo, but its `summaryDetail.yield` field
  comes back empty/missing** — the equity leg works fine for all three; only the bond leg is
  blocked, so any of these three self-heals with zero code change the moment Yahoo populates
  the field:
  | code | equity ETF (works) | bond ETF tried | issue |
  |---|---|---|---|
  | kr | EWY | 365780.KS / 272910.KS / 114470.KS (KRX-listed Korea treasury bond ETFs) | all 3 resolve on Yahoo, `summaryDetail.yield` is empty `{}` on every one |
  | za | EZA | STXGOV.JO (Satrix Govt Bond) | resolves, `summaryDetail.yield` is empty `{}`; `ETFGOVI.JO` doesn't resolve at all |
  | nl | (n/a, EUR — would reuse an existing Eurozone equity ETF) | INLD.AS / SNLD.L (iShares Netherlands Govt Bond, formerly `A1J0BG`) | confirmed **liquidated in 2017** — ticker still resolves on Yahoo but yield is empty; no replacement single-country NL product exists |

- **(b) no single-country government bond ETF product exists at all** — only pan-regional,
  Eurozone-aggregate, or broad emerging-market baskets hold that country's debt, with no
  standalone single-country wrapper listed on an exchange Yahoo indexes:
  | code | equity ETF (works) | note |
  |---|---|---|
  | br | EWZ | iShares Brazil LTN ETF (`BLTN`, ISIN DE000A2QP4D2, launched Sept 2025) is a real product but doesn't resolve on Yahoo under any exchange suffix tried (`BLTN`/`BLTN.DE`/`BLTN.F`/`BLTN.MI`/`BLTN.L`) |
  | mx | (would need its own equity ETF check) | only broad EM baskets (`VWOB`, `IGOV`) hold Mexican debt — no single-country MXN wrapper found |
  | se | (would need its own equity ETF check) | only pan-European/Nordic baskets exist |
  | pl | (would need its own equity ETF check) | only broad EM local-currency bond funds exist |
  | be | (would need its own equity ETF check) | appears only as a sub-weight inside Euro-area aggregate funds |
  | nz | (would need its own equity ETF check) | appears only inside broad international bond funds |

`br`'s equity leg (`EWZ`) already works — if a future contributor finds `BLTN` under a
different ticker/exchange suffix, `br` moves to the confirmed table with zero other research
needed. The other 5 (`mx`/`se`/`pl`/`be`/`nz`) were only checked for a bond product, not
their equity leg, since the bond side already blocks them either way.

