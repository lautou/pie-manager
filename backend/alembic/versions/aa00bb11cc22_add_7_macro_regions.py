# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add 7 more macro_regions (Allemagne, UK, Japon, Chine, Inde, Canada, Suisse)

Revision ID: aa00bb11cc22
Revises: zz99aa00bb11
Create Date: 2026-09-06

Extends the growth/inflation quadrant indicator from 3 regions (US/France/Monde) to 10.
All 10 tickers verified live against Yahoo's actual chart/price-history endpoint before being
shipped (period1=2000-01-01, not just a short recent window):

- Equity: raw index tickers preferred over ETFs when they give longer continuous history,
  matching this table's own existing precedent (^FCHI over ^SBF120 for France, see
  pp99qq00rr11). ^GDAXI/^FTSE/^N225/^GSPTSE/^SSMI all have dense history back to 2000.
  For China, `000001.SS` (Shanghai Composite) was chosen over `FXI` (iShares China
  Large-Cap ETF) for the same longer-history reason (2000 vs 2004 start) — `^SSEC` 404s.
  For India, `^BSESN` (Sensex, 2000+) was chosen over `^NSEI` (Nifty 50, 2007+) likewise.
- Bond: reused directly from `bond_perf_configs` (this app's sovereign-bond-performance
  indicator, seeded in zz99aa00bb11) rather than re-researched — same asset class (10y-ish
  government bonds), already live-verified this session — for 5 of the 7 regions.
  Japan (`236A.T`, only 495 points from 2024-08) and India (`INGB.AS`, only 657 points
  from 2024) were both replaced after a follow-up web search specifically for longer-history
  alternatives, real-verified against Yahoo's chart endpoint before being picked:
  - Japan: `XJSE.DE` (Xtrackers II Japan Government Bond UCITS ETF 1C, LU0952581584,
    all-maturities FTSE JGB index, launched 2013-12) — 3238 points back to 2013-12-02, vs.
    236A.T's 495. Broader maturity band than the 7-10y `bond_perf_configs` pick, traded off
    deliberately for ~6x more history.
  - India: `TIGR.L` (L&G India INR Government Bond UCITS ETF USD Dist, tracks the J.P.Morgan
    India Government FAR Bonds index, launched 2021-10, London listing) — 1224 points back
    to 2021-10-28, vs. INGB.AS's 657. Still far short of the equity tickers' 2000+ history —
    India's UCITS-wrapped local-currency govt bond market is simply young across every
    issuer checked (confirmed via justETF: no INR sovereign bond ETF older than 2021
    exists) — but a real, confirmed improvement over the original pick.
"""
from alembic import op
import sqlalchemy as sa

revision = 'aa00bb11cc22'
down_revision = 'zz99aa00bb11'
branch_labels = None
depends_on = None

macro_regions = sa.table(
    'macro_regions',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('equity_ticker', sa.String),
    sa.column('bond_ticker', sa.String),
    sa.column('equity_label', sa.String),
    sa.column('bond_label', sa.String),
)

_NEW_REGIONS = [
    {'code': 'de', 'label': 'Allemagne', 'equity_ticker': '^GDAXI', 'bond_ticker': 'EXX6.DE',
     'equity_label': 'DAX', 'bond_label': "Obligations d'État allemandes 10.5+ ans"},
    {'code': 'gb', 'label': 'Royaume-Uni', 'equity_ticker': '^FTSE', 'bond_ticker': 'IGLT.L',
     'equity_label': 'FTSE 100', 'bond_label': 'Gilts britanniques (IGLT)'},
    {'code': 'jp', 'label': 'Japon', 'equity_ticker': '^N225', 'bond_ticker': 'XJSE.DE',
     'equity_label': 'Nikkei 225', 'bond_label': "Obligations d'État japonaises (toutes échéances)"},
    {'code': 'cn', 'label': 'Chine', 'equity_ticker': '000001.SS', 'bond_ticker': 'CNYB.AS',
     'equity_label': 'Shanghai Composite', 'bond_label': 'Obligations en CNY chinoises'},
    {'code': 'in', 'label': 'Inde', 'equity_ticker': '^BSESN', 'bond_ticker': 'TIGR.L',
     'equity_label': 'BSE Sensex', 'bond_label': "Obligations d'État indiennes (JPM FAR, INR)"},
    {'code': 'ca', 'label': 'Canada', 'equity_ticker': '^GSPTSE', 'bond_ticker': 'XGB.TO',
     'equity_label': 'S&P/TSX Composite', 'bond_label': "Obligations d'État canadiennes"},
    {'code': 'ch', 'label': 'Suisse', 'equity_ticker': '^SSMI', 'bond_ticker': 'CSBGC0.SW',
     'equity_label': 'Swiss Market Index', 'bond_label': "Obligations d'État suisses 7-15 ans"},
]


def upgrade() -> None:
    op.bulk_insert(macro_regions, _NEW_REGIONS)


def downgrade() -> None:
    codes = tuple(r['code'] for r in _NEW_REGIONS)
    op.execute(
        sa.text("DELETE FROM macro_regions WHERE code IN :codes")
        .bindparams(sa.bindparam('codes', expanding=True))
        .bindparams(codes=list(codes))
    )
