---
paths:
  - "backend/app/services/etf_holdings_service.py"
  - "backend/app/tasks/etf_holdings.py"
  - "frontend/src/components/TickerLink.tsx"
  - "frontend/src/components/EtfCompositionModal.tsx"
  - "frontend/src/components/PoolAllocationSection.tsx"
---

## ETF look-through holdings — sector/company allocation

Two new tables — `etf_holdings` (top-10 underlying holdings) and `etf_sector_weightings`
(sector breakdown) — keyed by `parent_ticker`. A directly held stock (`instrument_type='Action'`)
gets a **synthetic self-row** in both (`holding_ticker=parent_ticker`, `weight_pct=1.0`), so
`compute_pool_lookthrough()` in `app/services/etf_holdings_service.py` never special-cases
"ETF vs direct stock" — every position in a pool feeds the same `by_company`/`by_sector`
accumulators keyed by underlying ticker/sector, which is what merges a stock held directly
with the same stock found inside one or more ETFs in the pool (e.g. TotalEnergies held
directly as `TTE.PA` and inside `STN.PA` at 18.63% — confirmed on real portfolio data).

**Data source**: Yahoo Finance's unofficial `quoteSummary` endpoint (`query2.finance.yahoo.com`,
module `topHoldings` for funds, `assetProfile` for a direct stock's `sectorKey`) — a
**different, more fragile mechanism** than the price-sync `chart` endpoint above. It requires
a session cookie + CSRF "crumb" token (`app/tasks/yahoo_fetch.py`'s `get_yahoo_session_crumb`/
`fetch_quote_summary_module` — extracted here from this module's original, sole-owner copy once
`app/tasks/equity_premium.py` needed the identical mechanism for module `summaryDetail`, see
`.claude/rules/macro-indicators.md`'s "Equity risk premium leaderboard" section) fetched fresh
each run; if that fails, the whole task aborts cleanly (old data stays in place,
`products.holdings_updated_at` just doesn't advance).

**Crumb endpoint gotcha, confirmed empirically**: `query2.finance.yahoo.com/v1/test/getcrumb`
returns `406 Not Acceptable` when the request sends `Accept: application/json` — it's the
`Accept` header specifically, not the `User-Agent` (isolated both independently; swapping only
the `Accept` header to `*/*` flips 406→200, a real crumb, and a working `quoteSummary` fetch).
`YAHOO_HEADERS`'s `Accept` is `*/*` for exactly this reason — `quoteSummary` itself returns
JSON regardless of the `Accept` header sent, so this is safe for every request the module
makes. This had silently never worked in production since the feature was introduced
(`products.holdings_updated_at` was `NULL` for all 21 eligible products) until this fix.

Only the top 10 holdings are ever
available (never full composition — coverage varies 19-97% of fund assets depending on the
ETF), so `by_company` always carries an explicit `"__OTHER__"` bucket for the untracked
remainder rather than implying completeness. `products.bond_duration`/`bond_maturity` are also
captured for bond funds — present in Yahoo's API but never shown on Yahoo's own site.

Runs weekly via PgQueuer (`0 4 * * 0` UTC, Sunday) plus once at backend startup, mirroring the
price-sync task's structure — see the root `CLAUDE.md`'s "Background job processing" section for the Celery→PgQueuer
cutover and the cron UTC-shift gotcha.

**Frontend**: `TickerLink` (`frontend/src/components/TickerLink.tsx`) renders a ticker as
clickable only for `instrument_type` ETF/SICAV-FCP/Action (never Cash/Or physique/Obligation/
Frais — no composition data exists for those), opening `EtfCompositionModal`. Both are shared
components wired into every page that displays a ticker (Comptes, Produits et frais, Positions,
Transactions, Performance, Dashboard) — a single reusable pair rather than one-off modals per
page. `PoolAllocationSection` (on the Positions page, per pool) shows the merged sector/company
breakdown via `GET /api/pools/{pool_id}/allocation`.

