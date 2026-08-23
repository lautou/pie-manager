# SPDX-License-Identifier: AGPL-3.0-or-later
"""drop subcategory from transactions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18

Decision: fee type is encoded in the ticker (FRAIS.TAXE.EUR, FRAIS.COURTAGE.EUR, etc.)
The subcategory field was redundant with the typed-ticker convention and has been removed.
"""
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('transactions', 'subcategory')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('transactions', sa.Column('subcategory', sa.String(50), nullable=True))
