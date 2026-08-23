# SPDX-License-Identifier: AGPL-3.0-or-later
"""create fiscal carry forward

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-19

Adds the fiscal_carry_forward table for tracking tax carry-forward losses
(moins-values reportables) per portfolio per year.
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: str = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fiscal_carry_forward',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('tax_year', sa.Integer(), nullable=False),
        sa.Column('amount_eur', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('portfolio_id', 'tax_year', name='uq_fiscal_carry_forward_portfolio_year'),
    )


def downgrade() -> None:
    op.drop_table('fiscal_carry_forward')
