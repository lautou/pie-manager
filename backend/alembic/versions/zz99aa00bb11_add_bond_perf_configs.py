# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add bond_perf_configs table (sovereign bond market performance leaderboard)

Revision ID: zz99aa00bb11
Revises: yy88zz99aa00
Create Date: 2026-09-06

- bond_perf_configs: user-managed country list (code, label, index_ticker, currency,
  index_label) for the "Performance obligataire" tab on the Indicateurs page — a trailing-1-
  year, EUR-adjusted performance chart of 10-year sovereign bond markets, one bar per
  country, no Top-N truncation (structurally identical to sector_perf_configs, not
  country_perf_configs). `code` doubles as the macro_series_prices series-key suffix
  (f"bond_{code}_govt") — deliberately distinct from equity_premium_configs' own
  f"premium_{code}_bond_yield" (a yield snapshot, not a price series) to avoid confusing the
  two features' data despite both tracking government bond ETFs for overlapping countries.
- Every ticker AND every implied f"{currency}EUR=X" FX ticker was empirically verified
  against Yahoo's chart endpoint (400+ day window) before being included here, per this
  codebase's established discipline for macro-indicator seed data (see
  .claude/rules/macro-indicators.md's own documented ticker-verification history).
- 14 of the 15 countries in the reference performance chart researched for this feature are
  covered. Brazil is the one confirmed exclusion: a real single-country product exists
  (iShares Brazil LTN BRL Govt Bond UCITS ETF (DE), ISIN DE000A2QP4D2, ticker BLTN, Xetra)
  but resolves under none of 9 tested Yahoo exchange suffixes — a Yahoo data-coverage gap
  for this specific fund, not a market-availability gap. Add back via the admin UI if a
  working Yahoo listing is ever found.
- Two rows carry a methodological caveat, flagged in the frontend UI rather than excluded
  outright (a directionally-informative bar is still more useful than no bar at all, unlike
  a genuinely dead ticker):
    - Sweden (`XACT-OBLIGATION.ST`): tracks a mixed Swedish bond index (government +
      mortgage + municipal), not a pure sovereign-only product — no 100%-government Swedish
      bond ETF was found on the UCITS/Nasdaq Stockholm market.
    - Mexico (`MEXS.L`): tracks Mexico's USD-denominated international debt (UMS), not
      domestic MXN-denominated Bonos — no UCITS product on local-currency Mexican government
      debt was found.
- France (`IFRB.AS`) reuses the same iShares France Government Bond ETF already seeded in
  equity_premium_configs under `IFRB.L` (London listing) — that London listing has dead
  price history on Yahoo's chart endpoint, but the identical fund's Amsterdam listing
  doesn't, confirming that Yahoo's price-history availability for a UCITS ETF can differ by
  listing even when the underlying fund is the same. This ETF covers all maturities, not
  just 10 years — no pure 10-year single-country France product exists on the UCITS market
  (confirmed via justETF).
- Italy (`BTP10.MI`, Amundi Italy BTP Government Bond 10Y UCITS ETF Acc) is a genuine
  improvement over equity_premium_configs' own `XBTP.MI` (dead price history on Yahoo for
  this feature's purposes) — a real single-country, single-maturity (10y) product.
- South Korea (`148070.KS`, KOSEF 10yr KTB) is a new find not present anywhere else in this
  codebase — equity_premium_configs excludes `kr` entirely because its 3 candidate bond
  ETFs all resolve on Yahoo with an empty `summaryDetail.yield`, but this feature only needs
  *price* history, which `148070.KS` has cleanly (confirmed ~275+ daily points).
"""
from alembic import op
import sqlalchemy as sa

revision = 'zz99aa00bb11'
down_revision = 'yy88zz99aa00'
branch_labels = None
depends_on = None

bond_perf_configs = sa.table(
    'bond_perf_configs',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('index_ticker', sa.String),
    sa.column('currency', sa.String),
    sa.column('index_label', sa.String),
)

_SEED_COUNTRIES = [
    {'code': 'us', 'label': 'États-Unis', 'index_ticker': 'IEF', 'currency': 'USD',
     'index_label': 'Trésor américain 7-10 ans (IEF)'},
    {'code': 'gb', 'label': 'Royaume-Uni', 'index_ticker': 'IGLT.L', 'currency': 'GBP',
     'index_label': 'Gilts britanniques (IGLT)'},
    {'code': 'jp', 'label': 'Japon', 'index_ticker': '236A.T', 'currency': 'JPY',
     'index_label': "Obligations d'État japonaises 7-10 ans"},
    {'code': 'de', 'label': 'Allemagne', 'index_ticker': 'EXX6.DE', 'currency': 'EUR',
     'index_label': "Obligations d'État allemandes 10.5+ ans"},
    {'code': 'fr', 'label': 'France', 'index_ticker': 'IFRB.AS', 'currency': 'EUR',
     'index_label': "Obligations d'État françaises, toutes maturités (IFRB)"},
    {'code': 'ch', 'label': 'Suisse', 'index_ticker': 'CSBGC0.SW', 'currency': 'CHF',
     'index_label': "Obligations d'État suisses 7-15 ans"},
    {'code': 'es', 'label': 'Espagne', 'index_ticker': 'IS0P.DE', 'currency': 'EUR',
     'index_label': "Obligations d'État espagnoles"},
    {'code': 'it', 'label': 'Italie', 'index_ticker': 'BTP10.MI', 'currency': 'EUR',
     'index_label': 'BTP italiens 10 ans (Amundi BTP10)'},
    {'code': 'au', 'label': 'Australie', 'index_ticker': '5GOV.AX', 'currency': 'AUD',
     'index_label': "Obligations d'État australiennes 5-10 ans"},
    {'code': 'cn', 'label': 'Chine', 'index_ticker': 'CNYB.AS', 'currency': 'USD',
     'index_label': 'Obligations en CNY chinoises'},
    {'code': 'ca', 'label': 'Canada', 'index_ticker': 'XGB.TO', 'currency': 'CAD',
     'index_label': "Obligations d'État canadiennes"},
    {'code': 'in', 'label': 'Inde', 'index_ticker': 'INGB.AS', 'currency': 'USD',
     'index_label': "Obligations d'État indiennes (INGB.AS)"},
    {'code': 'kr', 'label': 'Corée du Sud', 'index_ticker': '148070.KS', 'currency': 'KRW',
     'index_label': "Obligations d'État coréennes 10 ans (KOSEF, 148070.KS)"},
    {'code': 'se', 'label': 'Suède', 'index_ticker': 'XACT-OBLIGATION.ST', 'currency': 'SEK',
     'index_label': "Obligations suédoises mixtes — État, hypothécaire, municipal (XACT)"},
    {'code': 'mx', 'label': 'Mexique', 'index_ticker': 'MEXS.L', 'currency': 'USD',
     'index_label': "Dette internationale mexicaine en USD, UMS (Finamex) — pas les Bonos en pesos"},
]


def upgrade() -> None:
    op.create_table(
        'bond_perf_configs',
        sa.Column('code', sa.String(3), primary_key=True),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('index_ticker', sa.String(30), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('index_label', sa.String(80), nullable=False),
    )
    op.bulk_insert(bond_perf_configs, _SEED_COUNTRIES)


def downgrade() -> None:
    op.drop_table('bond_perf_configs')
