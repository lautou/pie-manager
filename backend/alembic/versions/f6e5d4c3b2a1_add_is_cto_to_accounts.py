"""add is_cto to accounts

Revision ID: f6e5d4c3b2a1
Revises: c3d4e5f6a7b8
Create Date: 2026-05-22

is_cto = True → Compte-Titres Ordinaire (taxable brokerage account, capital losses deductible)
is_cto = False → PEA, life insurance, or other tax-advantaged/different-regime accounts
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6e5d4c3b2a1'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('is_cto', sa.Boolean(), nullable=False, server_default='false'))
    # Degiro and IBKR are CTOs
    op.execute("UPDATE accounts SET is_cto = TRUE WHERE name IN ('Degiro', 'IBKR')")


def downgrade() -> None:
    op.drop_column('accounts', 'is_cto')
