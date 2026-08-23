# SPDX-License-Identifier: AGPL-3.0-or-later
"""add color to pools and accounts

Revision ID: jj22kk33ll44
Revises: ii11jj22kk33
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'jj22kk33ll44'
down_revision = 'ii11jj22kk33'
branch_labels = None
depends_on = None

# Default palette — assigned sequentially by pool/account order
_POOL_DEFAULTS = ['#1890FF', '#FAAD14', '#A0522D', '#52C41A', '#722ED1', '#13C2C2']
_ACCOUNT_DEFAULTS = ['#1890FF', '#FAAD14', '#52C41A', '#FF4D4F', '#722ED1', '#13C2C2', '#FA8C16', '#EB2F96', '#2F54EB']


def upgrade() -> None:
    op.add_column('pools', sa.Column('color', sa.String(7), nullable=True))
    op.add_column('accounts', sa.Column('color', sa.String(7), nullable=True))

    # Assign default colors to existing pools by id order
    for i, color in enumerate(_POOL_DEFAULTS):
        op.execute(f"""
            UPDATE pools SET color = '{color}'
            WHERE id = (
                SELECT id FROM pools ORDER BY id LIMIT 1 OFFSET {i}
            ) AND color IS NULL
        """)

    # Assign default colors to existing accounts by id order
    for i, color in enumerate(_ACCOUNT_DEFAULTS):
        op.execute(f"""
            UPDATE accounts SET color = '{color}'
            WHERE id = (
                SELECT id FROM accounts ORDER BY id LIMIT 1 OFFSET {i}
            ) AND color IS NULL
        """)


def downgrade() -> None:
    op.drop_column('pools', 'color')
    op.drop_column('accounts', 'color')
