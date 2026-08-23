# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EtfHolding(Base):
    """
    A single top-10 underlying holding of an ETF/SICAV or, for a directly held stock, a
    synthetic self-row (holding_ticker == parent_ticker, weight_pct == 1.0) so pool-level
    look-through aggregation never needs to special-case "is this an ETF or a direct stock".
    Replaced wholesale (delete + reinsert) on each successful fetch — Yahoo always returns a
    full top-10 snapshot, never a diff.
    """
    __tablename__ = "etf_holdings"

    parent_ticker: Mapped[str] = mapped_column(ForeignKey("products.ticker"), primary_key=True)
    holding_ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    holding_name: Mapped[str] = mapped_column(String(200), nullable=False)
    weight_pct: Mapped[float] = mapped_column(Float, nullable=False)  # 0.1863 = 18.63%


class EtfSectorWeighting(Base):
    """
    A single GICS-like sector weighting for an ETF/SICAV, or a synthetic 100% self-sector row
    for a directly held stock (sector = assetProfile.sectorKey, e.g. "energy"). `sector` is
    always the raw lowercase Yahoo key (never the capitalized display form) so ETF and direct
    stock rows merge on the same key during pool-level aggregation — frontend i18n maps the raw
    key to a display label.
    """
    __tablename__ = "etf_sector_weightings"

    parent_ticker: Mapped[str] = mapped_column(ForeignKey("products.ticker"), primary_key=True)
    sector: Mapped[str] = mapped_column(String(30), primary_key=True)
    weight_pct: Mapped[float] = mapped_column(Float, nullable=False)
