"""rename_users_to_portfolios

Revision ID: d8933e9771e7
Revises: c65f3ee73576
Create Date: 2026-05-15 07:56:17.911226

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd8933e9771e7'
down_revision: Union[str, None] = 'c65f3ee73576'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('users', 'portfolios')


def downgrade() -> None:
    op.rename_table('portfolios', 'users')
