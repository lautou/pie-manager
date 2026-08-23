# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Pool(Base):
    __tablename__ = "pools"
    __table_args__ = (
        CheckConstraint("strategy IN ('Offensive', 'Defensive')", name="ck_pool_strategy"),
        CheckConstraint("target_pct >= 0 AND target_pct <= 1", name="ck_pool_target_pct"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy: Mapped[str] = mapped_column(String(20), nullable=False)  # "Offensive" | "Defensive"
    target_pct: Mapped[float] = mapped_column(Float, nullable=False)   # 0.25 = 25%
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # hex e.g. #1890FF

    portfolio: Mapped["Portfolio"] = relationship(back_populates="pools")
    products: Mapped[list["PoolProduct"]] = relationship(back_populates="pool")
    daily_pool_snapshots: Mapped[list["DailyPoolSnapshot"]] = relationship(back_populates="pool")
    monthly_pool_snapshots: Mapped[list["MonthlyPoolSnapshot"]] = relationship(back_populates="pool")


class PoolProduct(Base):
    __tablename__ = "pool_products"

    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("products.ticker"), primary_key=True)

    pool: Mapped["Pool"] = relationship(back_populates="products")
    product: Mapped["Product"] = relationship(back_populates="pool_links")
