# SPDX-License-Identifier: AGPL-3.0-or-later
"""add commission_schedule to accounts

Revision ID: aa11bb22cc33
Revises: f6e5d4c3b2a1
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'aa11bb22cc33'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('commission_schedule', JSONB, nullable=True))

    op.execute("""
        UPDATE accounts
        SET commission_schedule = '[{"up_to": null, "type": "flat", "value": 3.0}]'::jsonb
        WHERE LOWER(name) LIKE '%degiro%'
    """)
    op.execute("""
        UPDATE accounts
        SET commission_schedule = '[
            {"up_to": 198,  "type": "percent", "value": 0.005},
            {"up_to": 500,  "type": "flat",    "value": 0.99},
            {"up_to": 1000, "type": "flat",    "value": 1.90},
            {"up_to": 2000, "type": "flat",    "value": 2.90},
            {"up_to": 4400, "type": "flat",    "value": 3.80},
            {"up_to": null, "type": "percent", "value": 0.0009}
        ]'::jsonb
        WHERE LOWER(name) LIKE '%bourse%'
    """)
    op.execute("""
        UPDATE accounts
        SET commission_schedule = '[
            {"up_to": 8333,   "type": "flat",    "value": 1.25},
            {"up_to": 193333, "type": "percent", "value": 0.00015},
            {"up_to": null,   "type": "flat",    "value": 29.0}
        ]'::jsonb
        WHERE LOWER(name) LIKE '%ibkr%' OR LOWER(name) LIKE '%interactive%'
    """)


def downgrade() -> None:
    op.drop_column('accounts', 'commission_schedule')
