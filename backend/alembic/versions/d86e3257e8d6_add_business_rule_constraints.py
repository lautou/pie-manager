"""add_business_rule_constraints

Revision ID: d86e3257e8d6
Revises: d8933e9771e7
Create Date: 2026-05-16 00:00:00.000000

Adds CHECK constraints for:
  - pools.strategy  ('Offensive' | 'Defensive')
  - pools.target_pct (0 ≤ x ≤ 1)
  - transactions.type ('Actif' | 'Frais' | 'Revenu')

NOTE — transaction.user_id / account.user_id ownership consistency:
  Enforcing "transaction.user_id == account.user_id" at the DB level would
  require a composite FK which PostgreSQL does not support without a unique
  composite key on accounts(id, user_id).  This is left as a known gap and is
  enforced in the application layer (transactions POST handler, HTTP 400).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'd86e3257e8d6'
down_revision: Union[str, None] = 'd8933e9771e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_pool_strategy",
        "pools",
        "strategy IN ('Offensive', 'Defensive')",
    )
    op.create_check_constraint(
        "ck_pool_target_pct",
        "pools",
        "target_pct >= 0 AND target_pct <= 1",
    )
    op.create_check_constraint(
        "ck_transaction_type",
        "transactions",
        "type IN ('Actif', 'Frais', 'Revenu')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transaction_type", "transactions", type_="check")
    op.drop_constraint("ck_pool_target_pct", "pools", type_="check")
    op.drop_constraint("ck_pool_strategy", "pools", type_="check")
