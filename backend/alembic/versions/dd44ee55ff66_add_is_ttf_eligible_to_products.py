"""add is_ttf_eligible to products

Revision ID: dd44ee55ff66
Revises: aa11bb22cc33
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'dd44ee55ff66'
down_revision = 'aa11bb22cc33'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products',
        sa.Column('is_ttf_eligible', sa.Boolean(), nullable=False,
                  server_default=sa.text('FALSE')))
    op.execute("""
        UPDATE products
        SET is_ttf_eligible = TRUE
        WHERE ticker IN ('AI.PA', 'TTE.PA', 'SU.PA', 'MC.PA')
    """)


def downgrade() -> None:
    op.drop_column('products', 'is_ttf_eligible')
