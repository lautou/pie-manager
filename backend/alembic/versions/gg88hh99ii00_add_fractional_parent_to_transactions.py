# SPDX-License-Identifier: AGPL-3.0-or-later
"""add fractional_parent_id to transactions

Revision ID: gg88hh99ii00
Revises: ff77aa88bb99
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'gg88hh99ii00'
down_revision = 'ff77aa88bb99'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('transactions',
        sa.Column('fractional_parent_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_transactions_fractional_parent',
        'transactions', 'transactions',
        ['fractional_parent_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_transactions_fractional_parent', 'transactions', ['fractional_parent_id'])

    # Backfill: tag confirmed fractional order groups
    op.execute("UPDATE transactions SET fractional_parent_id = 247 WHERE id IN (248)")
    op.execute("UPDATE transactions SET fractional_parent_id = 242 WHERE id IN (243)")
    op.execute("UPDATE transactions SET fractional_parent_id = 515 WHERE id IN (516, 517, 518)")
    op.execute("UPDATE transactions SET fractional_parent_id = 394 WHERE id IN (395)")
    op.execute("UPDATE transactions SET fractional_parent_id = 403 WHERE id IN (404, 405)")
    op.execute("UPDATE transactions SET fractional_parent_id = 378 WHERE id IN (379, 380, 381)")
    # Fix IBKR fee tx 382: was linked to 380 (sibling) → must point to 378 (parent)
    op.execute("UPDATE transactions SET linked_transaction_id = 378 WHERE id = 382")


def downgrade() -> None:
    op.execute("UPDATE transactions SET linked_transaction_id = 380 WHERE id = 382")
    op.execute("UPDATE transactions SET fractional_parent_id = NULL WHERE fractional_parent_id IS NOT NULL")
    op.drop_index('ix_transactions_fractional_parent', table_name='transactions')
    op.drop_constraint('fk_transactions_fractional_parent', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'fractional_parent_id')
