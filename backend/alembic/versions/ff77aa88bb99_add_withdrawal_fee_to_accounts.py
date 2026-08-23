# SPDX-License-Identifier: AGPL-3.0-or-later
"""add withdrawal_fee_eur and withdrawal_first_free to accounts

Revision ID: ff77aa88bb99
Revises: ee55ff66aa11
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'ff77aa88bb99'
down_revision = 'ee55ff66aa11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('withdrawal_fee_eur', sa.Float(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('withdrawal_first_free', sa.Boolean(), nullable=False, server_default='false'))

    # BourseDirect: 6€ flat, no first-free
    op.execute("UPDATE accounts SET withdrawal_fee_eur = 6.0, withdrawal_first_free = false WHERE LOWER(name) LIKE '%bourse%'")
    # IBKR: 8€ EUR SEPA, first withdrawal of month free
    op.execute("UPDATE accounts SET withdrawal_fee_eur = 8.0, withdrawal_first_free = true WHERE LOWER(name) LIKE '%ibkr%' OR LOWER(name) LIKE '%interactive%'")
    # auCoffre: 20€, first withdrawal of month free
    op.execute("UPDATE accounts SET withdrawal_fee_eur = 20.0, withdrawal_first_free = true WHERE LOWER(name) LIKE '%coffre%'")


def downgrade() -> None:
    op.drop_column('accounts', 'withdrawal_first_free')
    op.drop_column('accounts', 'withdrawal_fee_eur')
