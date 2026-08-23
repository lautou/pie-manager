# SPDX-License-Identifier: AGPL-3.0-or-later
"""global accounts: replace portfolio_id FK with portfolio_accounts join table

Revision ID: kk33ll44mm55
Revises: jj22kk33ll44
Create Date: 2026-05-29

Accounts become global entities (no longer portfolio-scoped).
A new portfolio_accounts join table handles the many-to-many relationship.
"""
from alembic import op
import sqlalchemy as sa

revision = 'kk33ll44mm55'
down_revision = 'jj22kk33ll44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the join table
    op.create_table(
        'portfolio_accounts',
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.PrimaryKeyConstraint('portfolio_id', 'account_id'),
    )
    op.create_index('ix_portfolio_accounts_account', 'portfolio_accounts', ['account_id'])

    # 2. Populate from existing account.portfolio_id
    op.execute("""
        INSERT INTO portfolio_accounts (portfolio_id, account_id)
        SELECT portfolio_id, id FROM accounts
        WHERE portfolio_id IS NOT NULL
    """)

    # 3. Drop the old portfolio_id FK and column
    # The FK was created with the legacy name "accounts_user_id_fkey" (column was renamed from user_id)
    op.drop_constraint('accounts_user_id_fkey', 'accounts', type_='foreignkey')
    op.drop_column('accounts', 'portfolio_id')


def downgrade() -> None:
    # Restore portfolio_id (assign first portfolio from join table, or NULL)
    op.add_column('accounts',
        sa.Column('portfolio_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE accounts a
        SET portfolio_id = (
            SELECT pa.portfolio_id FROM portfolio_accounts pa
            WHERE pa.account_id = a.id
            ORDER BY pa.portfolio_id LIMIT 1
        )
    """)
    op.create_foreign_key(
        'accounts_portfolio_id_fkey', 'accounts', 'portfolios',
        ['portfolio_id'], ['id']
    )
    op.drop_index('ix_portfolio_accounts_account', table_name='portfolio_accounts')
    op.drop_table('portfolio_accounts')
