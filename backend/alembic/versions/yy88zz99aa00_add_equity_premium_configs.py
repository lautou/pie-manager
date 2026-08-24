# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add equity_premium_configs table (implied equity risk premium leaderboard)

Revision ID: yy88zz99aa00
Revises: xx77yy88zz99
Create Date: 2026-08-24

- equity_premium_configs: user-managed CRUD table (code, label, equity_ticker, bond_ticker,
  equity_label, bond_label) backing the "Premium action" tab on the Indicateurs page — one
  bar per country, premium_pct = (1/trailingPE - bond_yield) * 100 (Fed Model/Damodaran
  implied equity risk premium, 10-year government bond convention). Structurally closer to
  macro_regions (equity+bond ticker pair) than to country_perf_configs/sector_perf_configs —
  but deliberately has NO `currency` column, since both legs are same-country, same-currency
  dimensionless yields subtracted directly (no FX anywhere in this feature).
- `code` matches country_perf_configs' 2-3-lowercase-letter shape (country parity with the
  "Performance des actions" leaderboard) — narrower than macro_regions' [a-z0-9_]{2,20}.
  Doubles as the macro_series_prices series-key suffix (premium_{code}_equity_yield /
  premium_{code}_bond_yield, max 24/22 chars — comfortably fits the String(40) `series`
  column widened in xx77yy88zz99), immutable once created.
- Seeds the 14 countries with confirmed live Yahoo data (summaryDetail.trailingPE on the
  equity ETF, summaryDetail.yield on the bond ETF — re-verified live via direct quoteSummary
  calls immediately before writing this migration, not from memory; hk/in/sg were added in a
  second verification pass after an initial 11-country pass had wrongly excluded them). The
  remaining countries in the "Performance des actions" universe have no workable Yahoo
  bond-yield data, for one of 2 distinct root causes documented in
  .claude/rules/macro-indicators.md's "Equity risk premium leaderboard" section — this is a
  live-editable CRUD universe, not a closed list.
"""
from alembic import op
import sqlalchemy as sa

revision = 'yy88zz99aa00'
down_revision = 'xx77yy88zz99'
branch_labels = None
depends_on = None

equity_premium_configs = sa.table(
    'equity_premium_configs',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('equity_ticker', sa.String),
    sa.column('bond_ticker', sa.String),
    sa.column('equity_label', sa.String),
    sa.column('bond_label', sa.String),
)

_SEED_COUNTRIES = [
    {'code': 'us', 'label': 'États-Unis', 'equity_ticker': 'SPY', 'bond_ticker': 'IEF',
     'equity_label': 'S&P 500 (SPY)', 'bond_label': 'Trésor américain 7-10 ans (IEF)'},
    {'code': 'gb', 'label': 'Royaume-Uni', 'equity_ticker': 'EWU', 'bond_ticker': 'IGLT.L',
     'equity_label': 'FTSE UK (EWU)', 'bond_label': 'Gilts britanniques (IGLT)'},
    {'code': 'jp', 'label': 'Japon', 'equity_ticker': 'EWJ', 'bond_ticker': '236A.T',
     'equity_label': 'Actions japonaises (EWJ)', 'bond_label': "Obligations d'État japonaises 7-10 ans"},
    {'code': 'de', 'label': 'Allemagne', 'equity_ticker': 'EWG', 'bond_ticker': 'EXX6.DE',
     'equity_label': 'Actions allemandes (EWG)', 'bond_label': "Obligations d'État allemandes 10.5+ ans"},
    {'code': 'fr', 'label': 'France', 'equity_ticker': 'EWQ', 'bond_ticker': 'IFRB.L',
     'equity_label': 'Actions françaises (EWQ)', 'bond_label': "Obligations d'État françaises"},
    {'code': 'ch', 'label': 'Suisse', 'equity_ticker': 'EWL', 'bond_ticker': 'CSBGC0.SW',
     'equity_label': 'Actions suisses (EWL)', 'bond_label': "Obligations d'État suisses 7-15 ans"},
    {'code': 'es', 'label': 'Espagne', 'equity_ticker': 'EWP', 'bond_ticker': 'IS0P.DE',
     'equity_label': 'Actions espagnoles (EWP)', 'bond_label': "Obligations d'État espagnoles"},
    {'code': 'it', 'label': 'Italie', 'equity_ticker': 'EWI', 'bond_ticker': 'XBTP.MI',
     'equity_label': 'Actions italiennes (EWI)', 'bond_label': 'BTP italiens'},
    {'code': 'au', 'label': 'Australie', 'equity_ticker': 'EWA', 'bond_ticker': '5GOV.AX',
     'equity_label': 'Actions australiennes (EWA)', 'bond_label': "Obligations d'État australiennes 5-10 ans"},
    {'code': 'cn', 'label': 'Chine', 'equity_ticker': 'FXI', 'bond_ticker': 'CNYB.AS',
     'equity_label': 'Actions chinoises (FXI)', 'bond_label': 'Obligations en CNY chinoises'},
    {'code': 'ca', 'label': 'Canada', 'equity_ticker': 'EWC', 'bond_ticker': 'XGB.TO',
     'equity_label': 'Actions canadiennes (EWC)', 'bond_label': "Obligations d'État canadiennes"},
    {'code': 'hk', 'label': 'Hong Kong', 'equity_ticker': 'EWH', 'bond_ticker': '2819.HK',
     'equity_label': 'Actions hong-kongaises (EWH)', 'bond_label': 'ABF Hong Kong Bond Index Fund (2819.HK)'},
    {'code': 'in', 'label': 'Inde', 'equity_ticker': 'INDA', 'bond_ticker': 'INGB.AS',
     'equity_label': 'Actions indiennes (INDA)', 'bond_label': "Obligations d'État indiennes (INGB.AS)"},
    {'code': 'sg', 'label': 'Singapour', 'equity_ticker': 'EWS', 'bond_ticker': 'A35.SI',
     'equity_label': 'Actions singapouriennes (EWS)', 'bond_label': 'ABF Singapore Bond Index Fund (A35.SI)'},
]


def upgrade() -> None:
    op.create_table(
        'equity_premium_configs',
        sa.Column('code', sa.String(3), primary_key=True),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('equity_ticker', sa.String(30), nullable=False),
        sa.Column('bond_ticker', sa.String(30), nullable=False),
        sa.Column('equity_label', sa.String(80), nullable=False),
        sa.Column('bond_label', sa.String(80), nullable=False),
    )
    op.bulk_insert(equity_premium_configs, _SEED_COUNTRIES)


def downgrade() -> None:
    op.drop_table('equity_premium_configs')
