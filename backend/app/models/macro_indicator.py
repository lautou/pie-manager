# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date

from sqlalchemy import Date, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MacroSeriesPrice(Base):
    """Daily value for a global macro series (S&P 500, WTI, US 10Y yield, gold) —
    decoupled from `products`/portfolios, these are not portfolio holdings."""

    __tablename__ = "macro_series_prices"
    __table_args__ = (UniqueConstraint("series", "date", name="uq_macro_series_price"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class MacroRegion(Base):
    """A user-managed macro region (US / France / Monde / ...) — equity + bond ticker pair
    for the growth/inflation ratios. `code` doubles as the macro_series_prices series-key
    prefix (f"{code}_equity" / f"{code}_bond"), so it's immutable once created."""

    __tablename__ = "macro_regions"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    equity_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    bond_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    equity_label: Mapped[str] = mapped_column(String(80), nullable=False)
    bond_label: Mapped[str] = mapped_column(String(80), nullable=False)
