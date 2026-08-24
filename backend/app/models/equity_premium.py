# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EquityPremiumConfig(Base):
    """A user-managed country in the "Premium action" tab's equity-risk-premium universe (see
    app/services/equity_premium_service.py). `code` matches CountryPerfConfig.code's own
    2-3 lowercase-letter shape (same countries as the "Performance des actions" leaderboard,
    where data exists) — narrower than MacroRegion's [a-z0-9_]{2,20} shape, since the whole
    point is country parity with the existing leaderboard. `code` doubles as the
    macro_series_prices series-key suffix (f"premium_{code}_equity_yield"/
    f"premium_{code}_bond_yield"), so it's immutable once created. equity_ticker is a
    single-country equity ETF wrapper (never the raw index — raw indices have no trailingPE
    on Yahoo, confirmed empirically), bond_ticker is a country government-bond ETF exposing
    summaryDetail.yield. No `currency` column and no FX leg anywhere in this feature —
    unlike every other CRUD config table here — since earnings_yield and risk_free_rate are
    both dimensionless, same-country, same-currency ratios subtracted directly."""

    __tablename__ = "equity_premium_configs"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    equity_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    bond_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    equity_label: Mapped[str] = mapped_column(String(80), nullable=False)
    bond_label: Mapped[str] = mapped_column(String(80), nullable=False)
