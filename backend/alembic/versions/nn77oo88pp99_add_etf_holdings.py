# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add ETF look-through holdings tables and bond-fund metrics on products

Revision ID: nn77oo88pp99
Revises: mm66nn77oo88
Create Date: 2026-07-14

- products.bond_duration / products.bond_maturity: bond-fund metrics from Yahoo's
  topHoldings.bondHoldings module (never surfaced in Yahoo's own UI, only in the raw API).
- products.holdings_updated_at: freshness marker for the new weekly fetch task.
- etf_holdings: top-10 underlying holdings per ETF/SICAV, or a synthetic self-row for a
  directly held stock (holding_ticker == parent_ticker, weight_pct == 1.0).
- etf_sector_weightings: sector breakdown per ETF/SICAV, or a synthetic 100% self-sector row
  for a directly held stock (sector = assetProfile.sectorKey, e.g. "energy").
"""
from alembic import op
import sqlalchemy as sa

revision = 'nn77oo88pp99'
down_revision = 'mm66nn77oo88'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('bond_duration', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('bond_maturity', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('holdings_updated_at', sa.DateTime(), nullable=True))

    op.create_table(
        'etf_holdings',
        sa.Column('parent_ticker', sa.String(50), sa.ForeignKey('products.ticker'), primary_key=True),
        sa.Column('holding_ticker', sa.String(20), primary_key=True),
        sa.Column('holding_name', sa.String(200), nullable=False),
        sa.Column('weight_pct', sa.Float(), nullable=False),
    )
    op.create_table(
        'etf_sector_weightings',
        sa.Column('parent_ticker', sa.String(50), sa.ForeignKey('products.ticker'), primary_key=True),
        sa.Column('sector', sa.String(30), primary_key=True),
        sa.Column('weight_pct', sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('etf_sector_weightings')
    op.drop_table('etf_holdings')
    op.drop_column('products', 'holdings_updated_at')
    op.drop_column('products', 'bond_maturity')
    op.drop_column('products', 'bond_duration')
