"""
Generic (series, date, value) time-series storage on top of MacroSeriesPrice — shared by
every feature that stores a daily Yahoo Finance series keyed by an arbitrary string (macro
indicators' region/oil/gold series, country_performance's per-country index/FX series).

Extracted from macro_indicators_service.py, which now imports get_series from here for its
own ratio computation — this module owns nothing region- or ratio-specific.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_indicator import MacroSeriesPrice


async def replace_series_prices(db: AsyncSession, series: str, points: list[tuple[date, float]]) -> None:
    """
    Upserts a full history snapshot for one series. Yahoo's chart endpoint always returns
    the full requested range (never a diff), so replace-on-fetch is correct and simplest —
    it also self-heals against gaps or Yahoo revising past values. Does not commit.
    """
    if not points:
        return
    stmt = insert(MacroSeriesPrice).values(
        [{"series": series, "date": d, "value": v} for d, v in points]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_macro_series_price",
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)


async def get_series(db: AsyncSession, series: str) -> dict[date, float]:
    result = await db.execute(
        select(MacroSeriesPrice.date, MacroSeriesPrice.value)
        .where(MacroSeriesPrice.series == series)
        .order_by(MacroSeriesPrice.date)
    )
    return {row.date: row.value for row in result.all()}
