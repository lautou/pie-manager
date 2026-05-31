"""add fx commission params to accounts (generic monthly-limit model)

Replaces the hardcoded commission_profile='revolut_fx' with configurable fields:
  - monthly_free_eur : free FX volume per calendar month (null = no limit)
  - above_monthly_rate : rate applied on volume exceeding the free limit
  - weekend_rate : rate applied on weekends (null = same as above_monthly_rate)

Revision ID: ii11jj22kk33
Revises: hh99ii00jj11
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'ii11jj22kk33'
down_revision = 'hh99ii00jj11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('monthly_free_eur', sa.Float(), nullable=True))
    op.add_column('accounts', sa.Column('above_monthly_rate', sa.Float(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('weekend_rate', sa.Float(), nullable=True))

    # Pre-populate Revolut: 1000€/month free, 1% beyond, 1% on weekends
    op.execute("""
        UPDATE accounts
        SET monthly_free_eur = 1000,
            above_monthly_rate = 0.01,
            weekend_rate = 0.01
        WHERE LOWER(name) LIKE '%revolut%'
    """)


def downgrade() -> None:
    op.drop_column('accounts', 'weekend_rate')
    op.drop_column('accounts', 'above_monthly_rate')
    op.drop_column('accounts', 'monthly_free_eur')
