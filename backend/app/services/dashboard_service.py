# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date
from typing import Optional

from app.models import AssetPrice, Transaction, Product, PortfolioAccount
from app.services.price_service import r2, held_quantity


async def get_holdings(
    db: AsyncSession,
    portfolio_id: int,
    as_of: Optional[date] = None,
) -> dict[str, float]:
    """
    Returns {ticker: units_held} as positive numbers.

    Convention:
      - Cash products (LIQUIDITE.EURO, JPYEUR=X...): positive qty = you hold it
      - Stock/ETF products: negative qty = you bought/hold it

    Args:
        as_of: If provided, only transactions up to and including this date are
               considered.  If None, all transactions are included (latest state).
    """
    where_clauses = [
        Transaction.portfolio_id == portfolio_id,
        Transaction.type == "Actif",
    ]
    if as_of is not None:
        where_clauses.append(Transaction.date <= as_of)

    result = await db.execute(
        select(Transaction.ticker, func.sum(Transaction.quantity).label("qty"))
        .join(Product, Transaction.ticker == Product.ticker)
        .add_columns(Product.instrument_type)
        .where(*where_clauses)
        .group_by(Transaction.ticker, Product.instrument_type)
    )
    holdings: dict[str, float] = {}
    for row in result.all():
        ticker, qty, instrument_type = row.ticker, float(row.qty or 0), row.instrument_type
        held = held_quantity(qty, instrument_type)
        if held > 0:
            holdings[ticker] = held

    # Adjust forex holdings for fees paid in the foreign currency.
    # Example: FRAIS.COURTAGE.JPY (type=Frais, currency=JPY, total_amount=-165)
    # reduces the JPYEUR=X held position — the quantity=-1 in fee rows is the
    # number of fee events, not JPY units; total_amount holds the actual amount.
    if holdings:
        tc_clauses = [
            Transaction.portfolio_id == portfolio_id,
            Transaction.ticker.in_(list(holdings.keys())),
            Transaction.type == "Actif",
            Transaction.currency != "EUR",
        ]
        if as_of is not None:
            tc_clauses.append(Transaction.date <= as_of)

        tc_result = await db.execute(
            select(Transaction.ticker, Transaction.currency)
            .where(*tc_clauses)
            .distinct()
        )
        ticker_to_currency = {r.ticker: r.currency for r in tc_result.all()}
        foreign_currencies = list(set(ticker_to_currency.values()))

        if foreign_currencies:
            fee_clauses = [
                Transaction.portfolio_id == portfolio_id,
                Transaction.type == "Frais",
                Transaction.currency.in_(foreign_currencies),
            ]
            if as_of is not None:
                fee_clauses.append(Transaction.date <= as_of)

            fee_result = await db.execute(
                select(Transaction.currency, func.sum(Transaction.total_amount).label("adj"))
                .where(*fee_clauses)
                .group_by(Transaction.currency)
            )
            fee_by_currency = {r.currency: float(r.adj or 0) for r in fee_result.all()}

            for ticker, currency in ticker_to_currency.items():
                adj = fee_by_currency.get(currency, 0.0)
                if adj and ticker in holdings:
                    holdings[ticker] = max(0.0, holdings[ticker] + adj)

    return holdings


async def _get_latest_prices(
    db: AsyncSession, tickers: list[str]
) -> dict[str, tuple[float, str]]:
    """Returns {ticker: (price, currency)} for the latest known price of each ticker."""
    if not tickers:
        return {}
    subq = (
        select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
        .where(AssetPrice.ticker.in_(tickers))
        .group_by(AssetPrice.ticker)
        .subquery()
    )
    result = await db.execute(
        select(AssetPrice).join(
            subq,
            (AssetPrice.ticker == subq.c.ticker) & (AssetPrice.date == subq.c.max_date),
        )
    )
    return {row.ticker: (row.price, row.currency) for row in result.scalars().all()}


async def _get_spot_rates(db: AsyncSession, as_of: Optional[date] = None) -> dict[str, float]:
    """Returns {ticker: rate} for all forex tickers (e.g. GBPEUR=X) — the latest known rate,
    or the latest at or before `as_of` when given. The single shared implementation of
    "latest FX rate [at or before a date]" in this app — previously duplicated a 2nd time in
    snapshot_service.py using a different SQL strategy (DISTINCT ON) for the exact same
    result, a real drift risk if one copy were ever fixed without the other."""
    where_clauses = [AssetPrice.ticker.like("%EUR=X")]
    if as_of is not None:
        where_clauses.append(AssetPrice.date <= as_of)
    subq = (
        select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
        .where(*where_clauses)
        .group_by(AssetPrice.ticker)
        .subquery()
    )
    result = await db.execute(
        select(AssetPrice).join(
            subq,
            (AssetPrice.ticker == subq.c.ticker) & (AssetPrice.date == subq.c.max_date),
        )
    )
    return {row.ticker: row.price for row in result.scalars().all()}


async def _get_latest_holdings(db: AsyncSession, portfolio_id: int) -> dict[str, float]:
    """Convenience wrapper — delegates to get_holdings(as_of=None)."""
    return await get_holdings(db, portfolio_id)


async def _get_liquidity_eur(db: AsyncSession, portfolio_id: int) -> float:
    """
    Return total EUR cash across all accounts for the portfolio.

    Uses portfolio_accounts.cash_balance_eur — the authoritative balance updated
    exclusively through the UI (all transaction creates/updates/deletes call
    _update_account_cash_balance). The previous approach (summing LIQUIDITE.EURO
    transactions) was incorrect: it summed all historical deposits without
    subtracting the cash used to buy assets, producing wildly inflated values.
    """
    result = await db.execute(
        select(func.sum(PortfolioAccount.cash_balance_eur))
        .where(PortfolioAccount.portfolio_id == portfolio_id)
    )
    val = result.scalar_one_or_none()
    return r2(float(val)) if val else 0.0
