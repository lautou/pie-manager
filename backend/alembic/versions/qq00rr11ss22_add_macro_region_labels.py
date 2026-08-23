# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add equity_label/bond_label to macro_regions (descriptive names instead of raw tickers)

Revision ID: qq00rr11ss22
Revises: pp99qq00rr11
Create Date: 2026-07-14

The growth/inflation chart legends showed the raw Yahoo ticker (e.g. "^FCHI / CL=F") which
means nothing to a non-technical reader. Adds a human-readable label per instrument
(equity_label, bond_label), backfilled for the 3 seeded regions; any other pre-existing
custom region falls back to its own ticker as a placeholder label until edited.
"""
from alembic import op
import sqlalchemy as sa

revision = 'qq00rr11ss22'
down_revision = 'pp99qq00rr11'
branch_labels = None
depends_on = None

_LABELS = {
    'us': ('S&P 500 Equal Weight', 'Obligations Trésor américain'),
    'fr': ('CAC 40', 'Obligations zone euro 10-15 ans'),
    'world': ('Actions Monde (Equal Weight)', 'Obligations Monde'),
}


def upgrade() -> None:
    op.add_column('macro_regions', sa.Column('equity_label', sa.String(80), nullable=True))
    op.add_column('macro_regions', sa.Column('bond_label', sa.String(80), nullable=True))

    for code, (equity_label, bond_label) in _LABELS.items():
        op.execute(
            sa.text("UPDATE macro_regions SET equity_label = :el, bond_label = :bl WHERE code = :code")
            .bindparams(el=equity_label, bl=bond_label, code=code)
        )
    # Any other pre-existing custom region falls back to its own ticker as a placeholder.
    op.execute("UPDATE macro_regions SET equity_label = equity_ticker WHERE equity_label IS NULL")
    op.execute("UPDATE macro_regions SET bond_label = bond_ticker WHERE bond_label IS NULL")

    op.alter_column('macro_regions', 'equity_label', nullable=False)
    op.alter_column('macro_regions', 'bond_label', nullable=False)


def downgrade() -> None:
    op.drop_column('macro_regions', 'bond_label')
    op.drop_column('macro_regions', 'equity_label')
