# SPDX-License-Identifier: AGPL-3.0-or-later
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import Portfolio


async def get_all_portfolios(db: AsyncSession) -> list[Portfolio]:
    result = await db.execute(select(Portfolio).order_by(Portfolio.name))
    return list(result.scalars().all())


async def get_portfolio_by_id(db: AsyncSession, portfolio_id: int) -> Portfolio | None:
    return await db.get(Portfolio, portfolio_id)


async def get_portfolio_by_name(db: AsyncSession, name: str) -> Portfolio | None:
    result = await db.execute(select(Portfolio).where(Portfolio.name == name))
    return result.scalar_one_or_none()


async def create_portfolio(db: AsyncSession, name: str) -> Portfolio:
    portfolio = Portfolio(name=name)
    db.add(portfolio)
    await db.flush()
    return portfolio
