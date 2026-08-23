# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add macro_series_prices table (global growth/inflation indicators)

Revision ID: oo88pp99qq00
Revises: nn77oo88pp99
Create Date: 2026-07-14

- macro_series_prices: daily value per macro series ('sp500', 'oil', 'us10y', 'gold'),
  decoupled from products/portfolios — these are not portfolio holdings, just the raw
  Yahoo Finance series feeding the growth (SP500/oil) and inflation (US10Y/gold) ratio
  indicators shown on the new global /indicators page.
"""
from alembic import op
import sqlalchemy as sa

revision = 'oo88pp99qq00'
down_revision = 'nn77oo88pp99'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'macro_series_prices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('series', sa.String(20), nullable=False, index=True),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('value', sa.Float(), nullable=False),
        sa.UniqueConstraint('series', 'date', name='uq_macro_series_price'),
    )


def downgrade() -> None:
    op.drop_table('macro_series_prices')
