# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add macro_regions table (user-managed growth/inflation regions)

Revision ID: pp99qq00rr11
Revises: oo88pp99qq00
Create Date: 2026-07-14

- macro_regions: user-managed region list (code, label, equity_ticker, bond_ticker) —
  replaces the hardcoded US/France/Monde region config. `code` doubles as the
  macro_series_prices series-key prefix, so it's immutable once created.
- Seeds the 3 existing regions. France now uses ^FCHI (CAC 40) instead of ^SBF120:
  confirmed via direct Yahoo queries that ^SBF120 has zero chart history from 2016
  onward (narrow period1/period2 windows for 2016-2018 and 2020-2021 both return no
  points), which made the France growth ratio flatten into a straight line for a
  decade. ^FCHI has continuous daily history over the full 26-year window.
"""
from alembic import op
import sqlalchemy as sa

revision = 'pp99qq00rr11'
down_revision = 'oo88pp99qq00'
branch_labels = None
depends_on = None

macro_regions = sa.table(
    'macro_regions',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('equity_ticker', sa.String),
    sa.column('bond_ticker', sa.String),
)


def upgrade() -> None:
    op.create_table(
        'macro_regions',
        sa.Column('code', sa.String(20), primary_key=True),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('equity_ticker', sa.String(30), nullable=False),
        sa.Column('bond_ticker', sa.String(30), nullable=False),
    )
    op.bulk_insert(macro_regions, [
        {'code': 'us', 'label': 'États-Unis', 'equity_ticker': '^SPXEW', 'bond_ticker': 'GOVT'},
        {'code': 'fr', 'label': 'France', 'equity_ticker': '^FCHI', 'bond_ticker': 'MTE.PA'},
        {'code': 'world', 'label': 'Monde', 'equity_ticker': 'MWEQ.L', 'bond_ticker': 'BNDW'},
    ])


def downgrade() -> None:
    op.drop_table('macro_regions')
