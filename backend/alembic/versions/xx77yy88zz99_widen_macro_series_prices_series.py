# SPDX-License-Identifier: AGPL-3.0-or-later
"""Widen macro_series_prices.series from VARCHAR(20) to VARCHAR(40)

Revision ID: xx77yy88zz99
Revises: ww66xx77yy88
Create Date: 2026-08-24

- Found live (not by inspection) while testing the new "Performance par secteur" feature
  against a real throwaway Postgres container: `sector_perf_configs` seeds a code up to 20
  chars (SectorPerfConfig.code is String(20), wider than CountryPerfConfig.code's String(3),
  since these are French-word slugs not ISO codes) — the resulting series key
  f"sector_{code}_equity" can reach 34 chars (e.g. "sector_agriculture_equity" is already 25),
  well past the original 20-char limit that was sized for the much shorter
  f"{code}_equity"/f"country_{code}_equity"/f"fx_{currency}" keys already in use. A real
  INSERT failed with `StringDataRightTruncationError` — the pytest suite's create_all-based
  fixtures never caught this, since SQLAlchemy's Python-side String(20) type has no
  client-side length enforcement, only Postgres's own VARCHAR(20) column does.
- 40 chars comfortably covers every current and near-future series key shape with room to
  spare, without going so wide it stops catching a genuinely runaway key.
"""
from alembic import op
import sqlalchemy as sa

revision = 'xx77yy88zz99'
down_revision = 'ww66xx77yy88'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'macro_series_prices', 'series',
        existing_type=sa.String(20), type_=sa.String(40), existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'macro_series_prices', 'series',
        existing_type=sa.String(40), type_=sa.String(20), existing_nullable=False,
    )
