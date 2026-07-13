"""
Capital gains service using the WACOP (Weighted Average Cost Of Purchase) method
(known as CUMP in France — Coût Unitaire Moyen Pondéré).

Business rules:
- CUMP is computed per (portfolio_id, ticker) pair.
- Standard assets (Actif): BUY = qty < 0 / SELL = qty > 0.
- Cash forex (JPYEUR=X etc.): sign is INVERTED — qty > 0 = holding position
  (buying JPY), qty < 0 = reducing position (selling JPY). Detected by
  instrument_type='Cash' AND ticker does NOT start with 'LIQUIDITE.'.
- LIQUIDITE.* tickers (LIQUIDITE.EURO, LIQUIDITE.USD, …) are pure cash-account
  entries — not financial instruments — and are excluded entirely.
- CUMP resets to 0 when position reaches 0 (full sell or below tolerance).
- Realized PV per sell = (unit_price_eur - cump_at_sell) × qty_sold.
- Cumulative realized PV is tracked across cycles (never resets).
- Transactions of type 'Frais' and 'Revenu' are ignored.
- Products with instrument_type='Or physique' (OR.PHYSIQUE) are excluded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.transaction import Transaction

# Floating-point tolerance: positions below this are treated as zero.
_QTY_EPSILON = 0.001


@dataclass
class CapitalGainsEvent:
    """A single realized gain/loss event (one sell transaction)."""
    date: date
    ticker: str
    product_name: str
    qty_sold: float
    cump_at_sell: float
    sell_price_eur: float
    realized_pv: float
    account_id: int


@dataclass
class TickerCapitalGains:
    """Aggregated capital gains data for a single (portfolio, ticker) pair."""
    ticker: str
    product_name: str
    cump: float                 # Current CUMP (0.0 if no position held)
    qty_held: float             # Current quantity held (units)
    cost_basis_eur: float       # cump × qty_held
    current_value_eur: float    # Filled by the endpoint (0.0 here)
    unrealized_pv: float        # current_value_eur - cost_basis_eur (filled by endpoint)
    realized_pv_total: float    # Cumulative realized PV across all cycles
    events: list[CapitalGainsEvent] = field(default_factory=list)


@dataclass
class PortfolioCapitalGains:
    """Full capital gains report for a portfolio (optionally filtered by account)."""
    portfolio_id: int
    tickers: list[TickerCapitalGains]
    total_unrealized_pv: float  # Sum over tickers (filled by endpoint)
    total_realized_pv: float    # Sum of all realized PV events
    total_pv: float             # total_unrealized_pv + total_realized_pv (filled by endpoint)


async def compute_capital_gains(
    db: AsyncSession,
    portfolio_id: int,
    account_id: int | None = None,
) -> PortfolioCapitalGains:
    """
    Compute CUMP-based capital gains for all eligible tickers in the portfolio.

    Args:
        db: Async SQLAlchemy session.
        portfolio_id: Portfolio to analyse.
        account_id: If provided, restrict to transactions on that account only.

    Returns:
        PortfolioCapitalGains with current_value_eur=0.0 and unrealized_pv=0.0
        for each ticker (the endpoint is responsible for filling those fields from
        live prices).
    """
    # ── 1. Fetch all products to determine categories ────────────────────────
    products_result = await db.execute(select(Product))
    product_map: dict[str, Product] = {p.ticker: p for p in products_result.scalars().all()}

    # ── 1b. Fetch accounts with include_fees_in_cump flag ────────────────────
    from app.models.broker import Broker
    from app.models.portfolio_account import PortfolioAccount
    acct_result = await db.execute(
        select(Broker.id, Broker.include_fees_in_cump)
        .join(PortfolioAccount, PortfolioAccount.broker_id == Broker.id)
        .where(PortfolioAccount.portfolio_id == portfolio_id)
    )
    fees_in_cump_by_account: dict[int, bool] = {
        row[0]: row[1] for row in acct_result.all()
    }

    # ── 2. Fetch transactions in chronological order ─────────────────────────
    where_clauses = [Transaction.portfolio_id == portfolio_id]
    if account_id is not None:
        where_clauses.append(Transaction.account_id == account_id)

    tx_result = await db.execute(
        select(Transaction)
        .where(*where_clauses)
        .order_by(Transaction.date.asc(), Transaction.id.asc())
    )
    transactions = tx_result.scalars().all()

    # ── 2b. Build linked-fee cost lookup (brokerage + TTF per buy transaction) ──
    # Only include fees for accounts where include_fees_in_cump = True.
    # Accounts with include_fees_in_cump = False (e.g. Degiro, IBKR) exclude brokerage from WACOP.
    fees_account_ids = {
        aid for aid, include in fees_in_cump_by_account.items() if include
    }
    fees_query = (
        select(
            Transaction.linked_transaction_id,
            sa_func.sum(sa_func.abs(Transaction.total_amount_eur)),
        )
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.type == "Frais",
            Transaction.linked_transaction_id.isnot(None),
            Transaction.account_id.in_(fees_account_ids) if fees_account_ids
            else sa.literal(False),
        )
        .group_by(Transaction.linked_transaction_id)
    )
    if account_id is not None:
        fees_query = fees_query.where(Transaction.account_id == account_id)
    fee_rows = await db.execute(fees_query)
    fees_by_parent: dict[int, float] = {r[0]: float(r[1]) for r in fee_rows.all()}

    # ── 3. Apply CUMP algorithm per ticker ───────────────────────────────────
    # State per ticker
    cump_by_ticker: dict[str, float] = {}
    qty_held_by_ticker: dict[str, float] = {}
    realized_pv_by_ticker: dict[str, float] = {}
    events_by_ticker: dict[str, list[CapitalGainsEvent]] = {}

    for tx in transactions:
        ticker = tx.ticker

        # Skip fee/dividend transactions — they don't affect CUMP
        if tx.type in ("Frais", "Revenu"):
            continue

        # Skip Or physique products (OR.PHYSIQUE) — special total-value pricing
        product = product_map.get(ticker)
        if product is not None and product.instrument_type == "Or physique":
            continue

        # Skip LIQUIDITE.* tickers — pure cash-account entries (deposits /
        # withdrawals), not financial instruments with capital gains.
        # Covers LIQUIDITE.EURO, LIQUIDITE.USD, LIQUIDITE.JPY, etc.
        if ticker.startswith("LIQUIDITE."):
            continue

        # Determine sign convention.
        # Cash forex products (JPYEUR=X, USDEUR=X …) hold qty > 0 = position.
        # Their BUY/SELL is the opposite of standard assets.
        is_cash_forex = (product is not None and product.instrument_type == "Cash")
        is_buy  = (tx.quantity > 0) if is_cash_forex else (tx.quantity < 0)
        is_sell = (tx.quantity < 0) if is_cash_forex else (tx.quantity > 0)

        # Initialise state for first encounter
        if ticker not in cump_by_ticker:
            cump_by_ticker[ticker] = 0.0
            qty_held_by_ticker[ticker] = 0.0
            realized_pv_by_ticker[ticker] = 0.0
            events_by_ticker[ticker] = []

        cump = cump_by_ticker[ticker]
        qty_held = qty_held_by_ticker[ticker]

        if is_buy:
            # ── BUY ─────────────────────────────────────────────────────────
            # Include linked Frais (courtage + TTF) in the cost basis
            cost = abs(tx.total_amount_eur) + fees_by_parent.get(tx.id, 0.0)
            qty_bought = abs(tx.quantity)
            new_qty = qty_held + qty_bought
            if new_qty > 0:  # pragma: no branch
                cump = (cump * qty_held + cost) / new_qty
            qty_held = new_qty

        elif is_sell:
            # ── SELL ─────────────────────────────────────────────────────────
            qty_sold = abs(tx.quantity)
            pv = (tx.unit_price_eur - cump) * qty_sold
            realized_pv_by_ticker[ticker] += pv

            product_name = product.name if product else ticker
            events_by_ticker[ticker].append(
                CapitalGainsEvent(
                    date=tx.date,
                    ticker=ticker,
                    product_name=product_name,
                    qty_sold=qty_sold,
                    cump_at_sell=cump,
                    sell_price_eur=tx.unit_price_eur,
                    realized_pv=pv,
                    account_id=tx.account_id,
                )
            )
            qty_held -= qty_sold
            if qty_held <= _QTY_EPSILON:
                qty_held = 0.0
                cump = 0.0  # Full position closed → reset CUMP

        # Persist updated state
        cump_by_ticker[ticker] = cump
        qty_held_by_ticker[ticker] = qty_held

    # ── 4. Build result objects ───────────────────────────────────────────────
    ticker_results: list[TickerCapitalGains] = []
    total_realized_pv = 0.0

    for ticker, cump in cump_by_ticker.items():
        qty_held = qty_held_by_ticker[ticker]
        realized_pv_total = realized_pv_by_ticker[ticker]
        total_realized_pv += realized_pv_total
        cost_basis_eur = cump * qty_held

        product = product_map.get(ticker)
        product_name = product.name if product else ticker

        ticker_results.append(
            TickerCapitalGains(
                ticker=ticker,
                product_name=product_name,
                cump=round(cump, 6),
                qty_held=round(qty_held, 6),
                cost_basis_eur=round(cost_basis_eur, 2),
                current_value_eur=0.0,   # filled by endpoint
                unrealized_pv=0.0,       # filled by endpoint
                realized_pv_total=round(realized_pv_total, 2),
                events=events_by_ticker[ticker],
            )
        )

    # Sort by ticker for deterministic output
    ticker_results.sort(key=lambda t: t.ticker)

    return PortfolioCapitalGains(
        portfolio_id=portfolio_id,
        tickers=ticker_results,
        total_unrealized_pv=0.0,   # filled by endpoint
        total_realized_pv=round(total_realized_pv, 2),
        total_pv=0.0,              # filled by endpoint
    )
