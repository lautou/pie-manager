# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    # Generic classification: "Actif" (any financial instrument, including cash)
    # or "Frais" (fee line item). Kept deliberately coarse — see instrument_type
    # / fee_type below for the actual typology.
    ticker: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # Sub-classification when category == "Actif": ETF / SICAV-FCP / Action /
    # Obligation / Or physique / Cash. Null for Frais products.
    instrument_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Sub-classification when category == "Frais": Courtage / Tenue de compte /
    # Intérêts négatifs / Bourse / TTF / Impôts / Conversion. Null for Actif products.
    fee_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # ISO 4217 currency code for this product (e.g. "EUR", "USD", "GBP")
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True for French large-caps subject to TTF (French Financial Transaction Tax) at 0.4%
    is_ttf_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                                   server_default="false")
    # Bond-fund metrics (Yahoo's topHoldings.bondHoldings) — only meaningful for
    # instrument_type == "Obligation". Not exposed by Yahoo's own UI for these funds
    # (verified by inspecting every tab of a bond fund's page) but present in the raw API.
    bond_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    bond_maturity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Last successful ETF-holdings/sector-weightings fetch — see app/tasks/etf_holdings.py.
    holdings_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    prices: Mapped[list["AssetPrice"]] = relationship(back_populates="product")
    pool_links: Mapped[list["PoolProduct"]] = relationship(back_populates="product")
