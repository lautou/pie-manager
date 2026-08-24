# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SectorPerfConfig(Base):
    """A user-managed commodity/sector row in the "Performance par secteur" tab's fixed
    4-row universe (see app/services/sector_performance_service.py). `code` is a lowercase
    French-word slug (e.g. "or", "petrole", "metaux", "agriculture") — longer than
    CountryPerfConfig.code (ISO alpha-2/3) since these aren't ISO codes, hence String(20).
    `code` doubles as the macro_series_prices series-key suffix (f"sector_{code}_equity"),
    so it's immutable once created. `currency` (ISO 4217, uppercase) drives whether the
    performance calc needs an FX leg — "EUR" needs none, every other currency reads a shared
    f"fx_{currency.lower()}" series (deduped across sectors that share a currency), exactly
    like CountryPerfConfig. Deliberately NOT special-cased against the existing oil/gold
    macro_series_prices series used by the growth/inflation ratio charts — this row fetches
    its own independent sector_{code}_equity series even for "or"/"petrole" (GC=F/CL=F),
    trading a small redundant Yahoo fetch for a fully generic, symmetric CRUD entity with no
    special-casing."""

    __tablename__ = "sector_perf_configs"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    index_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    index_label: Mapped[str] = mapped_column(String(80), nullable=False)
