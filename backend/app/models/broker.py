import sqlalchemy as sa
from sqlalchemy import JSON, Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Broker(Base):
    """Global broker entity (Degiro, IBKR, Revolut…).

    Configuration (commissions, allowed tickers, FX params) shared across all portfolios.
    Per-portfolio cash balance is tracked on the PortfolioAccount join table.
    """
    __tablename__ = "brokers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    is_cto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    commission_schedule: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_tickers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    withdrawal_fee_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    withdrawal_first_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    commission_profile: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    monthly_free_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    above_monthly_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    weekend_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    commission_sale_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    include_fees_in_cump: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    portfolio_links: Mapped[list["PortfolioAccount"]] = relationship(
        back_populates="broker", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="broker")
