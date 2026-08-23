# SPDX-License-Identifier: AGPL-3.0-or-later
"""Broker rename: accounts→brokers, cash_balance_eur on portfolio_accounts, duplicate merge

Revision ID: ll55mm66nn77
Revises: kk33ll44mm55
Create Date: 2026-05-29

New data model:
- Broker (global) = one entity per financial institution
- portfolio_accounts (Account) = Broker x Portfolio, holds cash_balance_eur

Merges applied:
- Revolut (id=1 Portfolio 1 + id=8 Portfolio 2) → id=1 assigned to both portfolios
- IBKR   (id=2 Portfolio 1 + id=7 Portfolio 2) → id=2 assigned to both portfolios
- Degiro (id=5 Portfolio 1 + id=6 Portfolio 2) → id=5 assigned to both portfolios
"""
from alembic import op
import sqlalchemy as sa

revision = 'll55mm66nn77'
down_revision = 'kk33ll44mm55'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add cash_balance_eur to portfolio_accounts ───────────────────────
    op.add_column('portfolio_accounts',
        sa.Column('cash_balance_eur', sa.Float(), nullable=False, server_default='0.0'))

    # ── 2. Copy balances from accounts ──────────────────────────────────────
    op.execute("""
        UPDATE portfolio_accounts pa
        SET cash_balance_eur = (
            SELECT a.cash_balance_eur FROM accounts a WHERE a.id = pa.account_id
        )
    """)

    # ── 3. Merge duplicate accounts ──────────────────────────────────────────
    # For each pair (keep_id, remove_id):
    # - Reassign transactions from remove_id to keep_id
    # - Insert a portfolio_accounts row for keep_id with the portfolio from remove_id
    # - Delete the portfolio_accounts rows for remove_id
    # - Delete the duplicate account remove_id

    for keep_id, remove_id in [(1, 8), (2, 7), (5, 6)]:
        # Reassign transactions
        op.execute(f"UPDATE transactions SET account_id = {keep_id} WHERE account_id = {remove_id}")

        # Create portfolio_accounts row for keep_id using the portfolio from remove_id
        # (fetches portfolio_id and cash_balance_eur from remove_id)
        op.execute(f"""
            INSERT INTO portfolio_accounts (portfolio_id, account_id, cash_balance_eur)
            SELECT portfolio_id, {keep_id}, cash_balance_eur
            FROM portfolio_accounts
            WHERE account_id = {remove_id}
        """)

        # Delete portfolio_accounts rows for remove_id
        op.execute(f"DELETE FROM portfolio_accounts WHERE account_id = {remove_id}")

        # Delete the duplicate account
        op.execute(f"DELETE FROM accounts WHERE id = {remove_id}")

    # ── 4. Rename accounts → brokers ────────────────────────────────────────
    op.rename_table('accounts', 'brokers')
    op.execute("ALTER SEQUENCE accounts_id_seq RENAME TO brokers_id_seq")
    op.execute("ALTER INDEX accounts_pkey RENAME TO brokers_pkey")

    # ── 5. Rename portfolio_accounts.account_id → broker_id ─────────────────
    op.drop_constraint('portfolio_accounts_account_id_fkey', 'portfolio_accounts',
                       type_='foreignkey')
    op.drop_index('ix_portfolio_accounts_account', table_name='portfolio_accounts')
    op.alter_column('portfolio_accounts', 'account_id', new_column_name='broker_id')
    op.create_index('ix_portfolio_accounts_broker', 'portfolio_accounts', ['broker_id'])
    op.create_foreign_key('portfolio_accounts_broker_id_fkey', 'portfolio_accounts',
                          'brokers', ['broker_id'], ['id'], ondelete='CASCADE')

    # ── 6. Update FK transactions → brokers ──────────────────────────────────
    op.drop_constraint('transactions_account_id_fkey', 'transactions', type_='foreignkey')
    op.create_foreign_key('transactions_broker_id_fkey', 'transactions',
                          'brokers', ['account_id'], ['id'])

    # ── 7. Drop cash_balance_eur from brokers (migrated to portfolio_accounts) ─
    op.drop_column('brokers', 'cash_balance_eur')


def downgrade() -> None:
    # Restore cash_balance_eur on brokers (sum per broker, approximate)
    op.add_column('brokers',
        sa.Column('cash_balance_eur', sa.Float(), nullable=False, server_default='0.0'))
    op.execute("""
        UPDATE brokers b
        SET cash_balance_eur = (
            SELECT COALESCE(SUM(pa.cash_balance_eur), 0)
            FROM portfolio_accounts pa WHERE pa.broker_id = b.id
        )
    """)

    # Restore FK transactions → accounts (will be renamed below)
    op.drop_constraint('transactions_broker_id_fkey', 'transactions', type_='foreignkey')
    op.create_foreign_key('transactions_account_id_fkey', 'transactions',
                          'brokers', ['account_id'], ['id'])

    # Restore portfolio_accounts.broker_id → account_id
    op.drop_constraint('portfolio_accounts_broker_id_fkey', 'portfolio_accounts',
                       type_='foreignkey')
    op.drop_index('ix_portfolio_accounts_broker', table_name='portfolio_accounts')
    op.alter_column('portfolio_accounts', 'broker_id', new_column_name='account_id')
    op.create_index('ix_portfolio_accounts_account', 'portfolio_accounts', ['account_id'])

    # Rename brokers → accounts
    op.rename_table('brokers', 'accounts')
    op.execute("ALTER SEQUENCE brokers_id_seq RENAME TO accounts_id_seq")
    op.execute("ALTER INDEX brokers_pkey RENAME TO accounts_pkey")
    op.create_foreign_key('portfolio_accounts_account_id_fkey', 'portfolio_accounts',
                          'accounts', ['account_id'], ['id'], ondelete='CASCADE')

    # Drop cash_balance_eur from portfolio_accounts
    op.drop_column('portfolio_accounts', 'cash_balance_eur')

    # Note: restoring the deleted duplicates is not implemented (too complex)
