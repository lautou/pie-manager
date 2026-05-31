from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Many-to-many accounts via portfolio_accounts join table
    account_links: Mapped[list["PortfolioAccount"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    pools: Mapped[list["Pool"]] = relationship(back_populates="portfolio")
    daily_snapshots: Mapped[list["DailySnapshot"]] = relationship(back_populates="portfolio")
    monthly_snapshots: Mapped[list["MonthlySnapshot"]] = relationship(back_populates="portfolio")
