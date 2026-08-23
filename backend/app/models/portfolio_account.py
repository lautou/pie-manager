# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PortfolioAccount(Base):
    """Account = Broker × Portfolio association.

    Represents a concrete brokerage account: one broker used within one portfolio.
    Holds the per-portfolio cash balance (cash_balance_eur) updated by every transaction.
    """
    __tablename__ = "portfolio_accounts"

    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    broker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("brokers.id", ondelete="CASCADE"), primary_key=True
    )
    cash_balance_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="account_links")
    broker: Mapped["Broker"] = relationship(back_populates="portfolio_links")
