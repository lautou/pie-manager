# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add sector_perf_configs table (fixed 4-row commodity/sector performance leaderboard)

Revision ID: ww66xx77yy88
Revises: vv55ww66xx77
Create Date: 2026-08-24

- sector_perf_configs: user-managed CRUD table (code, label, index_ticker, currency,
  index_label) backing the "Performance par secteur" tab on the Indicateurs page — a single
  bar chart with exactly 4 bars, trailing-1-year EUR-adjusted performance, same math as
  country_performance_service.py's ranking (no Top-N truncation, only 4 rows). Mirrors
  country_perf_configs' shape exactly (see rr11ss22tt33/ss22tt33uu44), with index_label
  included from the start this time — no separate backfill migration needed.
- `code` is a lowercase French-word slug (not an ISO code, hence String(20) vs
  CountryPerfConfig.code's String(3)) — doubles as the macro_series_prices series-key
  suffix (sector_{code}_equity), immutable once created.
- Seeds exactly 4 rows. Deliberately does NOT reuse the existing "oil"/"gold"
  macro_series_prices series already fetched by app/tasks/macro_indicators.py for the
  growth/inflation charts — "or"/"petrole" fetch their own independent
  sector_or_equity/sector_petrole_equity series from the same GC=F/CL=F tickers, a small
  accepted redundancy in exchange for a fully generic, symmetric CRUD entity (see
  app/models/sector_performance.py's docstring).
- Every ticker verified live via Yahoo's chart endpoint before inclusion: GC=F/CL=F already
  have long-established continuous history elsewhere in this codebase; DBB (Invesco DB Base
  Metals Fund) and DBA (Invesco DB Agriculture Fund) confirmed via direct chart API calls to
  have 4938 daily points since 2007-01-05, fresh through 2026-08-21. A broader "commodities"
  ETF (DBC, GSG, ^SPGSCI) was deliberately rejected for "Métaux industriels"/"Agriculture":
  all embed a real precious-metals weight (DBC's live holdings: ~5% Gold Future + ~1% Silver
  futures), which would make those bars redundant with "Or" instead of a distinct signal.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ww66xx77yy88'
down_revision = 'vv55ww66xx77'
branch_labels = None
depends_on = None

sector_perf_configs = sa.table(
    'sector_perf_configs',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('index_ticker', sa.String),
    sa.column('currency', sa.String),
    sa.column('index_label', sa.String),
)

_SEED_SECTORS = [
    {'code': 'or', 'label': 'Or', 'index_ticker': 'GC=F', 'currency': 'USD',
     'index_label': 'Or (COMEX)'},
    {'code': 'petrole', 'label': 'Pétrole', 'index_ticker': 'CL=F', 'currency': 'USD',
     'index_label': 'Pétrole (WTI)'},
    {'code': 'metaux', 'label': 'Métaux industriels', 'index_ticker': 'DBB', 'currency': 'USD',
     'index_label': 'Invesco DB Base Metals Fund'},
    {'code': 'agriculture', 'label': 'Agriculture', 'index_ticker': 'DBA', 'currency': 'USD',
     'index_label': 'Invesco DB Agriculture Fund'},
]


def upgrade() -> None:
    op.create_table(
        'sector_perf_configs',
        sa.Column('code', sa.String(20), primary_key=True),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('index_ticker', sa.String(30), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('index_label', sa.String(80), nullable=False),
    )
    op.bulk_insert(sector_perf_configs, _SEED_SECTORS)


def downgrade() -> None:
    op.drop_table('sector_perf_configs')
