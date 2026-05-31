"""rename_user_id_to_portfolio_id

Revision ID: e1f2a3b4c5d6
Revises: d8933e9771e7
Create Date: 2026-05-16 10:00:00.000000

Renames the `user_id` FK column to `portfolio_id` in all tables that
reference `portfolios.id`:
  - accounts
  - transactions
  - pools
  - daily_snapshots  (also updates the UniqueConstraint name)
  - monthly_snapshots (also updates the UniqueConstraint name)

pool_products and daily_pool_snapshots do NOT have a direct user_id column
(they reference pools.id and daily_snapshots.id respectively).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd8933e9771e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # accounts
    op.alter_column('accounts', 'user_id', new_column_name='portfolio_id')

    # transactions
    op.alter_column('transactions', 'user_id', new_column_name='portfolio_id')

    # pools
    op.alter_column('pools', 'user_id', new_column_name='portfolio_id')

    # daily_snapshots — rename column AND the unique constraint
    op.alter_column('daily_snapshots', 'user_id', new_column_name='portfolio_id')
    op.drop_constraint('uq_daily_snapshot', 'daily_snapshots', type_='unique')
    op.create_unique_constraint('uq_daily_snapshot', 'daily_snapshots', ['portfolio_id', 'date'])

    # monthly_snapshots — rename column AND the unique constraint
    op.alter_column('monthly_snapshots', 'user_id', new_column_name='portfolio_id')
    op.drop_constraint('uq_monthly_snapshot', 'monthly_snapshots', type_='unique')
    op.create_unique_constraint('uq_monthly_snapshot', 'monthly_snapshots', ['portfolio_id', 'date'])


def downgrade() -> None:
    # monthly_snapshots
    op.drop_constraint('uq_monthly_snapshot', 'monthly_snapshots', type_='unique')
    op.alter_column('monthly_snapshots', 'portfolio_id', new_column_name='user_id')
    op.create_unique_constraint('uq_monthly_snapshot', 'monthly_snapshots', ['user_id', 'date'])

    # daily_snapshots
    op.drop_constraint('uq_daily_snapshot', 'daily_snapshots', type_='unique')
    op.alter_column('daily_snapshots', 'portfolio_id', new_column_name='user_id')
    op.create_unique_constraint('uq_daily_snapshot', 'daily_snapshots', ['user_id', 'date'])

    # pools
    op.alter_column('pools', 'portfolio_id', new_column_name='user_id')

    # transactions
    op.alter_column('transactions', 'portfolio_id', new_column_name='user_id')

    # accounts
    op.alter_column('accounts', 'portfolio_id', new_column_name='user_id')
