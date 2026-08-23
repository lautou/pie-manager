# SPDX-License-Identifier: AGPL-3.0-or-later
"""add include_fees_in_cump to accounts

Revision ID: hh99ii00jj11
Revises: gg88hh99ii00
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'hh99ii00jj11'
down_revision = 'bb33cc44dd55'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts',
        sa.Column('include_fees_in_cump', sa.Boolean(), nullable=False,
                  server_default=sa.text('TRUE')))
    # Degiro and IBKR: brokerage fees are not included in the cost basis (WACOP)
    op.execute("UPDATE accounts SET include_fees_in_cump = FALSE WHERE LOWER(name) LIKE '%degiro%'")
    op.execute("UPDATE accounts SET include_fees_in_cump = FALSE WHERE LOWER(name) LIKE '%ibkr%' OR LOWER(name) LIKE '%interactive%'")


def downgrade() -> None:
    op.drop_column('accounts', 'include_fees_in_cump')
