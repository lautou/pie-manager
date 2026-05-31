"""add linked_transaction_id and subcategory to transactions

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-18

"""
from typing import Union
import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # linked_transaction_id: nullable self-referential FK for pairing related
    # transactions (e.g. EUR withdrawal funding a foreign-currency purchase).
    op.add_column(
        'transactions',
        sa.Column(
            'linked_transaction_id',
            sa.Integer(),
            sa.ForeignKey('transactions.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    # subcategory: optional classification for Frais transactions
    # (Courtage, Garde, Taxe, Change, Autre).
    op.add_column(
        'transactions',
        sa.Column('subcategory', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('transactions', 'subcategory')
    op.drop_column('transactions', 'linked_transaction_id')
