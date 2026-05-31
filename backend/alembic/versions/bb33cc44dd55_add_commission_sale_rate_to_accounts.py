"""add commission_sale_rate to accounts

Revision ID: bb33cc44dd55
Revises: aa22bb33cc44
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'bb33cc44dd55'
down_revision = 'aa22bb33cc44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts',
        sa.Column('commission_sale_rate', sa.Float(), nullable=False, server_default='0'))
    # auCoffre: 3% sur les ventes
    op.execute("UPDATE accounts SET commission_sale_rate = 0.03 WHERE LOWER(name) LIKE '%coffre%'")


def downgrade() -> None:
    op.drop_column('accounts', 'commission_sale_rate')
