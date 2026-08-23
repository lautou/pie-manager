# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add country_perf_configs table (Top-N market-performance leaderboard universe)

Revision ID: rr11ss22tt33
Revises: qq00rr11ss22
Create Date: 2026-07-19

- country_perf_configs: user-managed country list (code, label, index_ticker, currency) for
  the "Performance des marchés" tab on the Indicateurs page — a trailing-1-year, EUR-adjusted
  ranking, Top N (SystemSetting country_perf.top_n, default 15) taken from this universe.
  `code` doubles as the macro_series_prices series-key suffix (country_{code}_equity), so
  it's immutable once created; reuses the existing macro_series_prices table rather than a
  new one (see app/services/country_performance_service.py).
- Seeds an initial universe of 23 major-economy indices. Deliberately larger than the
  default top_n=15 so the leaderboard is a genuine "best of the universe" selection, not
  "all of them, always" — a curated pool that's periodically extended via the admin CRUD UI.
- Every index ticker AND every implied f"{currency}EUR=X" FX ticker was empirically verified
  against Yahoo's chart endpoint (450-day window, matching the task's HISTORY_WINDOW_DAYS)
  before being included here — this codebase has a documented history of tickers that look
  plausible but return zero/downsampled chart history (see pp99qq00rr11's ^SBF120 case).
  Two findings from that verification pass, already reflected below:
    - Poland: 'WIG20.WA' returns exactly 1 data point (dead, same symptom as ^SBF120) —
      replaced with 'ETFBW20TR.WA' (an ETF tracking the WIG20 Total Return index), which
      has full daily history.
    - Taiwan (TWD) and Turkey (TRY) are excluded entirely: their direct f"{ccy}EUR=X"
      crosses (TWDEUR=X, TRYEUR=X) return exactly 1 point regardless of window size — Yahoo
      only has a live quote for these, no history. The reverse crosses (EURTWD=X, EURTRY=X)
      DO have full history but represent the opposite direction (units of TWD/TRY per 1 EUR,
      not EUR per unit) — supporting them would need a per-currency reciprocal special case,
      which isn't worth adding for 2 currencies when the app's established convention is a
      single uniform f"{ccy}EUR=X" direction. Add back via the admin UI if a working direct
      source is found later.
"""
from alembic import op
import sqlalchemy as sa

revision = 'rr11ss22tt33'
down_revision = 'qq00rr11ss22'
branch_labels = None
depends_on = None

country_perf_configs = sa.table(
    'country_perf_configs',
    sa.column('code', sa.String),
    sa.column('label', sa.String),
    sa.column('index_ticker', sa.String),
    sa.column('currency', sa.String),
)

_SEED_COUNTRIES = [
    {'code': 'us', 'label': 'États-Unis', 'index_ticker': '^GSPC', 'currency': 'USD'},
    {'code': 'jp', 'label': 'Japon', 'index_ticker': '^N225', 'currency': 'JPY'},
    {'code': 'gb', 'label': 'Royaume-Uni', 'index_ticker': '^FTSE', 'currency': 'GBP'},
    {'code': 'de', 'label': 'Allemagne', 'index_ticker': '^GDAXI', 'currency': 'EUR'},
    {'code': 'fr', 'label': 'France', 'index_ticker': '^FCHI', 'currency': 'EUR'},
    {'code': 'cn', 'label': 'Chine', 'index_ticker': '000001.SS', 'currency': 'CNY'},
    {'code': 'hk', 'label': 'Hong Kong', 'index_ticker': '^HSI', 'currency': 'HKD'},
    {'code': 'in', 'label': 'Inde', 'index_ticker': '^BSESN', 'currency': 'INR'},
    {'code': 'ca', 'label': 'Canada', 'index_ticker': '^GSPTSE', 'currency': 'CAD'},
    {'code': 'au', 'label': 'Australie', 'index_ticker': '^AXJO', 'currency': 'AUD'},
    {'code': 'kr', 'label': 'Corée du Sud', 'index_ticker': '^KS11', 'currency': 'KRW'},
    {'code': 'br', 'label': 'Brésil', 'index_ticker': '^BVSP', 'currency': 'BRL'},
    {'code': 'mx', 'label': 'Mexique', 'index_ticker': '^MXX', 'currency': 'MXN'},
    {'code': 'ch', 'label': 'Suisse', 'index_ticker': '^SSMI', 'currency': 'CHF'},
    {'code': 'es', 'label': 'Espagne', 'index_ticker': '^IBEX', 'currency': 'EUR'},
    {'code': 'it', 'label': 'Italie', 'index_ticker': 'FTSEMIB.MI', 'currency': 'EUR'},
    {'code': 'nl', 'label': 'Pays-Bas', 'index_ticker': '^AEX', 'currency': 'EUR'},
    {'code': 'se', 'label': 'Suède', 'index_ticker': '^OMX', 'currency': 'SEK'},
    {'code': 'pl', 'label': 'Pologne', 'index_ticker': 'ETFBW20TR.WA', 'currency': 'PLN'},
    {'code': 'sg', 'label': 'Singapour', 'index_ticker': '^STI', 'currency': 'SGD'},
    {'code': 'za', 'label': 'Afrique du Sud', 'index_ticker': '^JN0U.JO', 'currency': 'ZAR'},
    {'code': 'be', 'label': 'Belgique', 'index_ticker': '^BFX', 'currency': 'EUR'},
    {'code': 'nz', 'label': 'Nouvelle-Zélande', 'index_ticker': '^NZ50', 'currency': 'NZD'},
]


def upgrade() -> None:
    op.create_table(
        'country_perf_configs',
        sa.Column('code', sa.String(3), primary_key=True),
        sa.Column('label', sa.String(50), nullable=False),
        sa.Column('index_ticker', sa.String(30), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
    )
    op.bulk_insert(country_perf_configs, _SEED_COUNTRIES)


def downgrade() -> None:
    op.drop_table('country_perf_configs')
