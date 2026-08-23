# SPDX-License-Identifier: AGPL-3.0-or-later
"""add commission_profile to accounts

Revision ID: aa22bb33cc44
Revises: ff77aa88bb99
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'aa22bb33cc44'
down_revision = 'gg88hh99ii00'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts',
        sa.Column('commission_profile', sa.String(50), nullable=True))
    op.execute("""
        UPDATE accounts SET commission_profile = 'revolut_fx'
        WHERE LOWER(name) LIKE '%revolut%'
    """)


def downgrade() -> None:
    op.drop_column('accounts', 'commission_profile')
