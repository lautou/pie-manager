# SPDX-License-Identifier: AGPL-3.0-or-later
"""rename_product_currencies_to_currency

Revision ID: f1a2b3c4d5e6
Revises: d86e3257e8d6
Create Date: 2026-05-16 12:00:00.000000

Renames the `currencies` column to `currency` in `products` and
shrinks the type from String(100) to String(10), since only a single
currency code is now stored per product.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, tuple] = ('d86e3257e8d6', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('products', 'currencies',
                    new_column_name='currency',
                    type_=sa.String(10),
                    existing_type=sa.String(100),
                    existing_nullable=False)


def downgrade() -> None:
    op.alter_column('products', 'currency',
                    new_column_name='currencies',
                    type_=sa.String(100),
                    existing_type=sa.String(10),
                    existing_nullable=False)
