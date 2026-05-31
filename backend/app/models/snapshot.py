from datetime import date

from sqlalchemy import Date, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"
    __table_args__ = (UniqueConstraint("portfolio_id", "date", name="uq_daily_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_eur: Mapped[float] = mapped_column(Float, nullable=False)
    offensive_eur: Mapped[float] = mapped_column(Float, default=0.0)
    defensive_eur: Mapped[float] = mapped_column(Float, default=0.0)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="daily_snapshots")
    pool_snapshots: Mapped[list["DailyPoolSnapshot"]] = relationship(
        back_populates="daily_snapshot", cascade="all, delete-orphan"
    )


class DailyPoolSnapshot(Base):
    __tablename__ = "daily_pool_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("daily_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id"), nullable=False)
    value_eur: Mapped[float] = mapped_column(Float, nullable=False)

    daily_snapshot: Mapped["DailySnapshot"] = relationship(back_populates="pool_snapshots")
    pool: Mapped["Pool"] = relationship(back_populates="daily_pool_snapshots")


class MonthlySnapshot(Base):
    __tablename__ = "monthly_snapshots"
    __table_args__ = (UniqueConstraint("portfolio_id", "date", name="uq_monthly_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)  # snapshot date (end of month)
    total_eur: Mapped[float] = mapped_column(Float, nullable=False)
    offensive_eur: Mapped[float] = mapped_column(Float, default=0.0)
    defensive_eur: Mapped[float] = mapped_column(Float, default=0.0)
    contributions_eur: Mapped[float] = mapped_column(Float, default=0.0)
    performance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    performance_index: Mapped[float] = mapped_column(Float, default=100.0)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="monthly_snapshots")
    pool_snapshots: Mapped[list["MonthlyPoolSnapshot"]] = relationship(
        back_populates="monthly_snapshot", cascade="all, delete-orphan"
    )


class MonthlyPoolSnapshot(Base):
    __tablename__ = "monthly_pool_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    monthly_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("monthly_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id"), nullable=False)
    value_eur: Mapped[float] = mapped_column(Float, nullable=False)

    monthly_snapshot: Mapped["MonthlySnapshot"] = relationship(back_populates="pool_snapshots")
    pool: Mapped["Pool"] = relationship(back_populates="monthly_pool_snapshots")
