# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add index_label to country_perf_configs (descriptive index name instead of raw ticker)

Revision ID: ss22tt33uu44
Revises: rr11ss22tt33
Create Date: 2026-07-19

The market-performance chart tooltip and admin CRUD table only showed the raw Yahoo ticker
(e.g. "^KS11") which means nothing to a non-technical reader, and made it hard to tell which
underlying index a given country's bar actually tracks — a real point of confusion surfaced
while comparing our leaderboard against an external reference chart that turned out to use
different indices for some countries (e.g. Shenzhen vs Shanghai for "Chine"). Adds a
human-readable label per country's index (index_label), backfilled for the 23 seeded
countries; any other pre-existing custom country falls back to its own ticker as a
placeholder label until edited — same pattern as qq00rr11ss22's equity_label/bond_label.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ss22tt33uu44'
down_revision = 'rr11ss22tt33'
branch_labels = None
depends_on = None

_LABELS = {
    'us': 'S&P 500',
    'jp': 'Nikkei 225',
    'gb': 'FTSE 100',
    'de': 'DAX 40',
    'fr': 'CAC 40',
    'cn': 'Shanghai Composite',
    'hk': 'Hang Seng',
    'in': 'BSE Sensex',
    'ca': 'S&P/TSX Composite',
    'au': 'S&P/ASX 200',
    'kr': 'KOSPI Composite',
    'br': 'Ibovespa',
    'mx': 'IPC Mexico',
    'ch': 'SMI (Swiss Market Index)',
    'es': 'IBEX 35',
    'it': 'FTSE MIB',
    'nl': 'AEX',
    'se': 'OMX Stockholm 30',
    'pl': 'WIG20 (ETF Total Return)',
    'sg': 'Straits Times Index',
    'za': 'FTSE/JSE Top 40',
    'be': 'BEL 20',
    'nz': 'NZX 50',
}


def upgrade() -> None:
    op.add_column('country_perf_configs', sa.Column('index_label', sa.String(80), nullable=True))

    for code, index_label in _LABELS.items():
        op.execute(
            sa.text("UPDATE country_perf_configs SET index_label = :il WHERE code = :code")
            .bindparams(il=index_label, code=code)
        )
    # Any other pre-existing custom country falls back to its own ticker as a placeholder.
    op.execute("UPDATE country_perf_configs SET index_label = index_ticker WHERE index_label IS NULL")

    op.alter_column('country_perf_configs', 'index_label', nullable=False)


def downgrade() -> None:
    op.drop_column('country_perf_configs', 'index_label')
