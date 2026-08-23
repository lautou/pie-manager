# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CountryPerfConfig(Base):
    """A user-managed country in the market-performance leaderboard universe (see
    app/services/country_performance_service.py's Top-N ranking). `code` (ISO 3166-1
    alpha-2/3, lowercase) doubles as the macro_series_prices series-key suffix
    (f"country_{code}_equity"), so it's immutable once created. `currency` (ISO 4217,
    uppercase) drives whether the ranking needs an FX leg — "EUR" needs none, every other
    currency reads a shared f"fx_{currency.lower()}" series (deduped across countries that
    share a currency)."""

    __tablename__ = "country_perf_configs"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    index_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    index_label: Mapped[str] = mapped_column(String(80), nullable=False)
