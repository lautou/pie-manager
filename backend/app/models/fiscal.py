# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FiscalCarryForward(Base):
    __tablename__ = "fiscal_carry_forward"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(nullable=False)
    amount_eur: Mapped[float] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "tax_year", name="uq_fiscal_carry_forward_portfolio_year"),
    )
