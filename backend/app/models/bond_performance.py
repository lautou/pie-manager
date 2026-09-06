# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BondPerfConfig(Base):
    """A user-managed country in the sovereign-bond-market performance leaderboard universe
    (see app/services/bond_performance_service.py). Same shape as CountryPerfConfig (code,
    label, ticker, currency) plus a human-readable `index_label` for the ticker, mirroring
    EquityPremiumConfig's equity_label/index_label convention. `code` (ISO 3166-1 alpha-2/3,
    lowercase) doubles as the macro_series_prices series-key suffix
    (f"bond_{code}_govt") — deliberately distinct from EquityPremiumConfig's own
    f"premium_{code}_bond_yield" (a yield snapshot, not a price series) to avoid confusing
    the two features' data. `currency` drives whether the trailing-performance ranking needs
    an FX leg — "EUR" needs none, every other currency reads a shared
    f"fx_{currency.lower()}" series (deduped across countries that share a currency)."""

    __tablename__ = "bond_perf_configs"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    index_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    index_label: Mapped[str] = mapped_column(String(80), nullable=False)
