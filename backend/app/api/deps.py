# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared FastAPI router helpers — the "fetch by column or 404" and "block delete while
referenced" shapes hand-copied across brokers.py/pools.py/products.py/portfolios.py/fiscal.py
before being collapsed here.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute


async def get_or_404(
    db: AsyncSession, column: InstrumentedAttribute, value: Any, detail: str = "Not found"
) -> Any:
    """Fetch the single row where `column == value`, or raise a 404.

    `column` is any mapped column (e.g. `Broker.id`, `Product.ticker`) — its owning model is
    resolved from the column itself, so one helper covers every primary-key shape in this app.
    """
    result = await db.execute(select(column.class_).where(column == value))
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail=detail)
    return instance


async def ensure_unreferenced(
    db: AsyncSession, column: InstrumentedAttribute, value: Any, detail_fn: Callable[[int], str]
) -> None:
    """Raise a 400 (via `detail_fn(count)`) if any row references `value` through `column` —
    e.g. transactions still pointing at a broker/product about to be deleted."""
    count = (await db.execute(
        select(func.count()).select_from(column.class_).where(column == value)
    )).scalar_one()
    if count > 0:
        raise HTTPException(status_code=400, detail=detail_fn(count))
