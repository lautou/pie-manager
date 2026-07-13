from sqlalchemy import Boolean, String, Text
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

    prices: Mapped[list["AssetPrice"]] = relationship(back_populates="product")
    pool_links: Mapped[list["PoolProduct"]] = relationship(back_populates="product")
