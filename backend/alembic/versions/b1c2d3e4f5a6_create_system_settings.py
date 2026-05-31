"""create system_settings table

Revision ID: b1c2d3e4f5a6
Revises: f6e5d4c3b2a1
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'f6e5d4c3b2a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(100), primary_key=True, nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('system_settings')
