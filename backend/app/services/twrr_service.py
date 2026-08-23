# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, text
from datetime import date
from collections import defaultdict

from app.models import Pool, AssetPrice
from app.models.snapshot import DailySnapshot, DailyPoolSnapshot
from app.models.transaction import Transaction
from app.models.product import Product
from app.services.price_service import _to_eur, r2


async def fetch_pool_twrr_data(
    db: AsyncSession,
    portfolio_id: int,
    daily_list: list,
    snapshot_date_set: set,
    remap_flows,
) -> dict:
    """
    Fetches and computes TWRR data for pools (total, offensive, defensive, per-pool).

    Returns a dict with keys:
      - daily_list: deduplicated + sorted list of DailySnapshot objects
      - pools: {pool_id: Pool}
      - pool_daily: {date: {pool_id: value_eur}}
      - pool_flows: {pool_id: {date: float}}
      - strat_flows_off: {date: float}
      - strat_flows_def: {date: float}
      - total_flows: {}
    """
    # Pools
    pools_q = await db.execute(
        select(Pool).where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)  # noqa: E712
    )
    pools = {p.id: p for p in pools_q.scalars().all()}

    pool_snaps_q = await db.execute(
        select(DailySnapshot.date, DailyPoolSnapshot.pool_id, DailyPoolSnapshot.value_eur)
        .join(DailyPoolSnapshot, DailyPoolSnapshot.daily_snapshot_id == DailySnapshot.id)
        .where(DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.total_eur > 0)
        .order_by(DailySnapshot.date)
    )
    # {date: {pool_id: value_eur}}
    pool_daily: dict[date, dict[int, float]] = {}
    for row in pool_snaps_q.all():
        pool_daily.setdefault(row.date, {})
        pool_daily[row.date][row.pool_id] = row.value_eur

    # ── 3. Transaction flows per pool per date ─────────────────────────────
    # Performance: raw SQL intentionnel — 4-table JOIN with GROUP BY across
    # transactions, pool_products, pools, and products. The ORM equivalent
    # would require multiple subqueries or explicit join chaining that is
    # harder to read and offers no correctness benefit over this flat SQL.
    tx_pool_q = await db.execute(text("""
        SELECT t.date, pl.id AS pool_id, pl.strategy, pr.instrument_type,
               SUM(t.total_amount_eur) AS net_tx
        FROM transactions t
        JOIN pool_products pp ON pp.ticker = t.ticker
        JOIN pools pl ON pl.id = pp.pool_id
        JOIN products pr ON pr.ticker = t.ticker
        WHERE pl.portfolio_id = :uid AND t.portfolio_id = pl.portfolio_id
          AND t.ticker != 'LIQUIDITE.EURO'
          AND t.type = 'Actif'
        GROUP BY t.date, pl.id, pl.strategy, pr.instrument_type
    """), {"uid": portfolio_id})
    pool_flows: dict[int, dict[date, float]] = {}
    strat_flows_off: dict[date, float] = {}
    strat_flows_def: dict[date, float] = {}
    for row in tx_pool_q.all():
        pid, dt, net_tx, strat, itype = (
            row.pool_id, row.date, row.net_tx or 0.0, row.strategy, row.instrument_type
        )
        flow = net_tx if itype == "Cash" else -net_tx
        pool_flows.setdefault(pid, {})[dt] = (
            pool_flows.get(pid, {}).get(dt, 0.0) + flow
        )
        if strat == "Offensive":
            strat_flows_off[dt] = strat_flows_off.get(dt, 0.0) + flow
        else:
            strat_flows_def[dt] = strat_flows_def.get(dt, 0.0) + flow

    pool_flows = {pid: remap_flows(f) for pid, f in pool_flows.items()}
    strat_flows_off = remap_flows(strat_flows_off)
    strat_flows_def = remap_flows(strat_flows_def)

    # Option A: total_flows is empty (cash-less coherence)
    total_flows: dict[date, float] = {}

    return {
        "pools": pools,
        "pool_daily": pool_daily,
        "pool_flows": pool_flows,
        "strat_flows_off": strat_flows_off,
        "strat_flows_def": strat_flows_def,
        "total_flows": total_flows,
    }


async def fetch_position_twrr_data(
    db: AsyncSession,
    portfolio_id: int,
    all_dates: list[date],
    remap_flows,
) -> dict[str, list[dict]]:
    """
    Fetches and computes per-position TWRR data.

    Returns {product_name: [{date, index}, ...]} for all non-cash positions.
    """
    from app.api.routers.snapshots import _compute_twrr

    non_cash_non_fee = (
        Product.category != "Frais",
        or_(Product.instrument_type != "Cash", Product.instrument_type.is_(None)),
    )
    pos_tickers_q = await db.execute(
        select(Transaction.ticker, Product.instrument_type, Product.name.label("product_name"))
        .join(Product, Transaction.ticker == Product.ticker)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.ticker != "LIQUIDITE.EURO",
            Transaction.type == "Actif",
            *non_cash_non_fee,
        )
        .distinct()
        .order_by(Transaction.ticker)
    )
    pos_tickers = [(r.ticker, r.instrument_type, r.product_name) for r in pos_tickers_q.all()]

    if not pos_tickers:
        return {}

    all_tx_q = await db.execute(
        select(
            Transaction.date,
            Transaction.ticker,
            Transaction.quantity,
            Transaction.total_amount_eur,
            Product.instrument_type,
        )
        .join(Product, Transaction.ticker == Product.ticker)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.ticker != "LIQUIDITE.EURO",
            Transaction.type == "Actif",
            *non_cash_non_fee,
        )
        .order_by(Transaction.ticker, Transaction.date)
    )

    tx_by_ticker: dict[str, list] = defaultdict(list)
    pos_raw_flows: dict[str, dict[date, float]] = defaultdict(dict)
    for row in all_tx_q.all():
        tx_by_ticker[row.ticker].append((row.date, row.quantity, row.total_amount_eur, row.instrument_type))
        f = -(row.total_amount_eur or 0.0)
        d = row.date
        pos_raw_flows[row.ticker][d] = pos_raw_flows[row.ticker].get(d, 0.0) + f

    ticker_list = [t for t, _, _ in pos_tickers]
    prices_q = await db.execute(
        select(
            AssetPrice.ticker,
            AssetPrice.date,
            AssetPrice.price,
            AssetPrice.currency,
        )
        .where(AssetPrice.ticker.in_(ticker_list))
        .order_by(AssetPrice.ticker, AssetPrice.date)
    )
    prices_by_ticker: dict[str, list] = defaultdict(list)
    for row in prices_q.all():
        prices_by_ticker[row.ticker].append((row.date, row.price, row.currency))

    # Latest FX spot rates
    fx_subq = (
        select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
        .where(AssetPrice.ticker.like("%EUR=X"))
        .group_by(AssetPrice.ticker)
        .subquery()
    )
    fx_result = await db.execute(
        select(AssetPrice).join(
            fx_subq,
            (AssetPrice.ticker == fx_subq.c.ticker) & (AssetPrice.date == fx_subq.c.max_date),
        )
    )
    spot_rates: dict[str, float] = {row.ticker: row.price for row in fx_result.scalars().all()}

    twrr_positions: dict[str, list[dict]] = {}
    for ticker, instrument_type, product_name in pos_tickers:
        txs = tx_by_ticker.get(ticker, [])
        prices = prices_by_ticker.get(ticker, [])
        if not txs or not prices:
            continue

        value_series: list[tuple[date, float]] = []
        cum_raw_qty = 0.0
        tx_idx = 0
        price_idx = 0

        for snap_dt in all_dates:
            while tx_idx < len(txs) and txs[tx_idx][0] <= snap_dt:
                cum_raw_qty += txs[tx_idx][1]
                tx_idx += 1
            while price_idx < len(prices) - 1 and prices[price_idx + 1][0] <= snap_dt:
                price_idx += 1
            if not prices or prices[price_idx][0] > snap_dt:
                continue
            raw_price = prices[price_idx][1]
            currency = prices[price_idx][2]
            price = _to_eur(raw_price, currency, spot_rates)

            if instrument_type == "Or physique":
                held = max(0.0, abs(cum_raw_qty)) if cum_raw_qty != 0 else 0.0
                value = price if held > 0 else 0.0
            else:
                held = max(0.0, -cum_raw_qty)
                value = r2(held * price)

            if value > 0:
                value_series.append((snap_dt, value))

        if not value_series:
            continue

        remapped = remap_flows(pos_raw_flows.get(ticker, {}))
        label = product_name or ticker
        twrr_positions[label] = _compute_twrr(value_series, remapped)

    return twrr_positions
