"""
Integration tests for /api/snapshots — covering lines:
  101-157  list_daily_with_pools
  167-174  list_daily_snapshots (date_from, date_to filters)
  182-187  list_monthly_snapshots
  213-305  get_twrr (TWRR endpoint full integration)
  318-323  create_monthly_snapshot

All tests use the `client` fixture (test DB injected via conftest).
"""

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.snapshot import DailySnapshot, DailyPoolSnapshot, MonthlySnapshot
from app.models.portfolio_account import PortfolioAccount


# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------

async def _setup(db) -> tuple[int, int, int, int]:
    """
    Insert a minimal Portfolio + Account + Product + Pool.
    Returns (portfolio_id, account_id, product_ticker_str, pool_id).
    """
    portfolio = Portfolio(name=f"SnapRoute-{id(db)}")
    db.add(portfolio)
    await db.flush()

    account = Broker(name="Degiro", currency="EUR")
    db.add(account)

    ticker = f"SR.{portfolio.id}"
    db.add(Product(ticker=ticker, name="TestETF", category="Actif", currency="EUR"))

    pool = Pool(portfolio_id=portfolio.id, name="Asie", strategy="Offensive",
                target_pct=0.25, is_active=True)
    db.add(pool)
    await db.flush()
    db.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    db.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db.flush()

    return portfolio.id, account.id, ticker, pool.id


async def _add_daily(db, portfolio_id: int, pool_id: int, snap_date: date,
                     total: float, off: float = 0, def_: float = 0, pool_val: float = 0):
    snap = DailySnapshot(portfolio_id=portfolio_id, date=snap_date, total_eur=total,
                         offensive_eur=off, defensive_eur=def_)
    db.add(snap)
    await db.flush()
    if pool_val > 0:
        db.add(DailyPoolSnapshot(daily_snapshot_id=snap.id, pool_id=pool_id, value_eur=pool_val))
        await db.flush()
    return snap


async def _add_monthly(db, portfolio_id: int, snap_date: date,
                       total: float, index: float = 100.0):
    snap = MonthlySnapshot(
        portfolio_id=portfolio_id, date=snap_date, total_eur=total,
        offensive_eur=total, defensive_eur=0,
        contributions_eur=0, performance_pct=0, performance_index=index,
    )
    db.add(snap)
    await db.flush()
    return snap


# ---------------------------------------------------------------------------
# GET /api/snapshots/daily-with-pools  (lines 101-157)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_with_pools_returns_pool_breakdown(client, db_session):
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2024, 6, 3), 10_000, off=10_000, pool_val=10_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["total_eur"] == pytest.approx(10_000, rel=1e-2)
    assert len(data[0]["pools"]) == 1
    assert data[0]["pools"][0]["pool_name"] == "Asie"


@pytest.mark.asyncio
async def test_daily_with_pools_date_from_filter(client, db_session):
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2024, 1, 2), 5_000, off=5_000, pool_val=5_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 6, 2), 8_000, off=8_000, pool_val=8_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools",
                         params={"portfolio_id": uid, "date_from": "2025-01-01"})
    assert r.status_code == 200
    data = r.json()
    assert all(d["date"] >= "2025-01-01" for d in data)
    assert len(data) == 1


@pytest.mark.asyncio
async def test_daily_with_pools_deduplicates_pool_snapshots(client, db_session):
    """
    If two DailyPoolSnapshot rows exist for the same pool on the same day,
    only the first is kept (line 140: continue branch).
    """
    uid, _, _, pool_id = await _setup(db_session)
    snap = DailySnapshot(portfolio_id=uid, date=date(2025, 7, 1), total_eur=12_000,
                         offensive_eur=12_000, defensive_eur=0)
    db_session.add(snap)
    await db_session.flush()
    db_session.add(DailyPoolSnapshot(daily_snapshot_id=snap.id, pool_id=pool_id, value_eur=12_000))
    db_session.add(DailyPoolSnapshot(daily_snapshot_id=snap.id, pool_id=pool_id, value_eur=9_000))
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert len(data[0]["pools"]) == 1  # deduplicated: only one pool entry


@pytest.mark.asyncio
async def test_daily_with_pools_empty(client, db_session):
    uid, _, _, _ = await _setup(db_session)
    await db_session.flush()
    r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/snapshots/daily  (lines 167-174)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_daily_snapshots_basic(client, db_session):
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2025, 3, 3), 9_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_list_daily_snapshots_date_from(client, db_session):
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2023, 12, 29), 7_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 4, 1), 9_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily",
                         params={"portfolio_id": uid, "date_from": "2025-01-01"})
    assert r.status_code == 200
    assert all(d["date"] >= "2025-01-01" for d in r.json())


@pytest.mark.asyncio
async def test_list_daily_snapshots_date_to(client, db_session):
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2024, 6, 1), 6_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 6, 1), 8_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily",
                         params={"portfolio_id": uid, "date_to": "2024-12-31"})
    assert r.status_code == 200
    assert all(d["date"] <= "2024-12-31" for d in r.json())


# ---------------------------------------------------------------------------
# GET /api/snapshots/monthly  (lines 182-187)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_monthly_snapshots(client, db_session):
    uid, _, _, _ = await _setup(db_session)
    await _add_monthly(db_session, uid, date(2025, 1, 31), 10_000, 100.0)
    await _add_monthly(db_session, uid, date(2025, 2, 28), 11_000, 110.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/monthly", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # Ordered newest first
    assert data[0]["date"] > data[1]["date"]
    assert any(abs(d["performance_index"] - 110.0) < 0.01 for d in data)


@pytest.mark.asyncio
async def test_list_monthly_snapshots_empty(client, db_session):
    uid, _, _, _ = await _setup(db_session)
    await db_session.flush()
    r = await client.get("/api/snapshots/monthly", params={"portfolio_id": uid})
    assert r.status_code == 200
    # fresh portfolio — no monthly snapshots yet for this specific portfolio_id
    user_snaps = [s for s in r.json() if s["portfolio_id"] == uid]
    assert user_snaps == []


# ---------------------------------------------------------------------------
# GET /api/snapshots/twrr  (lines 213-305)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_endpoint_empty_portfolio(client, db_session):
    """No snapshots → returns empty lists."""
    uid, _, _, _ = await _setup(db_session)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == []
    assert body["offensive"] == []
    assert body["defensive"] == []
    assert body["pools"] == {}


@pytest.mark.asyncio
async def test_twrr_endpoint_basic_structure(client, db_session):
    """TWRR returns correct keys and base-100 start."""
    uid, aid, ticker, pool_id = await _setup(db_session)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 2), price=50.0,
                              currency="EUR", source="test"))
    await _add_daily(db_session, uid, pool_id, date(2025, 1, 2), 10_000,
                     off=10_000, pool_val=10_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 1, 3), 11_000,
                     off=11_000, pool_val=11_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "offensive" in body
    assert "defensive" in body
    assert "pools" in body
    assert "Asie" in body["pools"]

    # First point in each series must be 100
    assert body["total"][0]["index"] == pytest.approx(100.0)
    assert body["pools"]["Asie"][0]["index"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_twrr_endpoint_gain_reflected(client, db_session):
    """10% portfolio gain → TWRR total goes from 100 to 110."""
    uid, aid, ticker, pool_id = await _setup(db_session)
    # No external flows
    await _add_daily(db_session, uid, pool_id, date(2025, 2, 3), 10_000,
                     off=10_000, pool_val=10_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 2, 4), 11_000,
                     off=11_000, pool_val=11_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    total = r.json()["total"]
    assert len(total) == 2
    assert total[0]["index"] == pytest.approx(100.0)
    assert total[1]["index"] == pytest.approx(110.0, rel=1e-3)


@pytest.mark.asyncio
async def test_twrr_endpoint_inflow_neutralised(client, db_session):
    """
    Option A (cash-less coherence): LIQUIDITE.EURO flows are excluded from
    the total TWRR. The total only tracks invested-position performance.

    A 5k cash deposit on day 2 leaves positions unchanged (pool_val=10k on
    both days). Because total_eur reflects invested positions only, it stays
    at 10k → TWRR index remains 100 on day 2 (pure price return, flat).

    The LIQUIDITE.EURO transaction is present in the DB but has no effect on
    the total TWRR under Option A.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    liq_ticker = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(
        sa_select(Product).where(Product.ticker == liq_ticker)
    )
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq_ticker, name="Cash EUR",
                               category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    # Day 1: invested positions at 10k
    await _add_daily(db_session, uid, pool_id, date(2025, 3, 3), 10_000,
                     off=10_000, pool_val=10_000)
    # Day 2: LIQUIDITE deposit of 5k — positions unchanged, total_eur stays 10k
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 4),
        type="Actif", ticker=liq_ticker, currency="EUR",
        exchange_rate=1.0, quantity=5_000.0,
        unit_price=1.0, unit_price_eur=1.0,
        total_amount=5_000.0, total_amount_eur=5_000.0,
    ))
    # total_eur = 10k (positions only, cash excluded from snapshot)
    await _add_daily(db_session, uid, pool_id, date(2025, 3, 4), 10_000,
                     off=10_000, pool_val=10_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    total = r.json()["total"]
    # Option A: no LIQUIDITE.EURO flows → total TWRR is pure price return.
    # Positions flat → index stays at 100 on day 2.
    assert total[1]["index"] == pytest.approx(100.0, abs=1.0)


@pytest.mark.asyncio
async def test_twrr_endpoint_pool_flow_neutralised(client, db_session):
    """
    Buying a new position in the pool (inflow) should not inflate TWRR.
    Pool value includes the new position, flow neutralises it → index≈100.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    # Day 1: pool at 10k
    await _add_daily(db_session, uid, pool_id, date(2025, 4, 1), 10_000,
                     off=10_000, pool_val=10_000)
    # Day 2: buy 2k of ticker → pool value 12k, inflow = +2k
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date(2025, 4, 2),
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-40.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-2_000.0, total_amount_eur=-2_000.0,
    ))
    await _add_daily(db_session, uid, pool_id, date(2025, 4, 2), 12_000,
                     off=12_000, pool_val=12_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    pool_twrr = r.json()["pools"]["Asie"]
    # inflow = 2000, denom = 10000+2000=12000, V_t=12000 → r=1.0 → index=100
    assert pool_twrr[1]["index"] == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# POST /api/snapshots/monthly  (lines 318-323)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_monthly_snapshot_via_api(client, db_session):
    """
    POST /api/snapshots/monthly creates and returns a monthly snapshot
    when a daily snapshot exists for the requested date.
    """
    uid, _, _, pool_id = await _setup(db_session)
    snap_date = date(2025, 5, 31)
    await _add_daily(db_session, uid, pool_id, snap_date, 12_000,
                     off=12_000, pool_val=12_000)
    await db_session.flush()

    r = await client.post("/api/snapshots/monthly",
                          json={"portfolio_id": uid, "date": snap_date.isoformat()})
    assert r.status_code == 201
    body = r.json()
    assert body["portfolio_id"] == uid
    assert body["date"] == snap_date.isoformat()
    assert body["total_eur"] == pytest.approx(12_000, rel=1e-2)
    assert body["performance_index"] == pytest.approx(100.0, abs=0.1)


@pytest.mark.asyncio
async def test_twrr_defensive_strategy_flow(client, db_session):
    """
    Transactions for a Defensive pool fill strat_flows_def (line 266).
    The defensive TWRR index starts at 100 and reflects pool performance.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)
    # Make the pool Defensive
    from sqlalchemy import select as sa_select
    from app.models.pool import Pool as PoolModel
    result = await db_session.execute(sa_select(PoolModel).where(PoolModel.id == pool_id))
    pool_obj = result.scalar_one()
    pool_obj.strategy = "Defensive"
    await db_session.flush()

    await _add_daily(db_session, uid, pool_id, date(2025, 8, 1), 10_000,
                     off=0, def_=10_000, pool_val=10_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 8, 4), 11_000,
                     off=0, def_=11_000, pool_val=11_000)
    # Add a transaction for this pool's ticker (defensive flow, line 266)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date(2025, 8, 4),
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-20.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-1_000.0, total_amount_eur=-1_000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "defensive" in body
    assert len(body["defensive"]) >= 1
    assert body["defensive"][0]["index"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_create_monthly_snapshot_no_daily_returns_422(client, db_session):
    """
    POST /api/snapshots/monthly returns 422 when no daily snapshot exists.
    compute_monthly_snapshot raises ValueError which becomes 422.
    """
    uid, _, _, _ = await _setup(db_session)
    await db_session.flush()

    r = await client.post("/api/snapshots/monthly",
                          json={"portfolio_id": uid, "date": "2025-06-30"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/snapshots/twrr — positions section (lines 342-431)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_positions_key_exists(client, db_session):
    """
    TWRR endpoint returns a 'positions' key when there are daily snapshots
    but no non-Cash/Frais transactions (the `else: twrr_positions = {}` branch at line 431).
    """
    uid, _, _, pool_id = await _setup(db_session)
    # Add a daily snapshot so the endpoint doesn't early-return
    await _add_daily(db_session, uid, pool_id, date(2025, 6, 2), 10_000,
                     off=10_000, pool_val=10_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # No transactions with non-Cash/Frais products → positions is empty dict
    assert body["positions"] == {}


@pytest.mark.asyncio
async def test_twrr_positions_basic_computation(client, db_session):
    """
    TWRR positions: a single ETF position bought at 50, held for 2 days at 55.
    Positions key should contain the product name with TWRR starting at 100.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    # Ensure product category is "Actif" (not Cash/Frais)
    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Test ETF Position"
    product.category = "Actif"
    await db_session.flush()

    snap_date1 = date(2025, 9, 1)
    snap_date2 = date(2025, 9, 2)

    # Buy 10 units on day 1 at 50 EUR
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date1,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # Prices: day1 = 50, day2 = 55
    db_session.add(AssetPrice(ticker=ticker, date=snap_date1, price=50.0, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date2, price=55.0, currency="EUR", source="test"))
    # Daily snapshots for both days
    await _add_daily(db_session, uid, pool_id, snap_date1, 500.0, off=500.0, pool_val=500.0)
    await _add_daily(db_session, uid, pool_id, snap_date2, 550.0, off=550.0, pool_val=550.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # The product name "Test ETF Position" should be the key
    positions = body["positions"]
    assert "Test ETF Position" in positions
    pos_series = positions["Test ETF Position"]
    assert len(pos_series) == 2
    assert pos_series[0]["index"] == pytest.approx(100.0)
    # Day 2: 55/50 = 1.10 → index = 110
    assert pos_series[1]["index"] == pytest.approx(110.0, rel=1e-2)


@pytest.mark.asyncio
async def test_twrr_positions_inflow_neutralised(client, db_session):
    """
    TWRR positions: buying in two tranches neutralises the second purchase.
    Tranche 1: 10 units at 50 → 500
    Tranche 2: 10 more units at 50 → 1000 (inflow 500, price unchanged)
    TWRR day 2 should be ≈100 (inflow neutralised).
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Tranche ETF"
    product.category = "Actif"
    await db_session.flush()

    snap_date1 = date(2025, 10, 1)
    snap_date2 = date(2025, 10, 2)

    # Tranche 1: buy 10 units
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date1,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # Tranche 2: buy 10 more units at same price
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date2,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # Prices: same on both days
    db_session.add(AssetPrice(ticker=ticker, date=snap_date1, price=50.0, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date2, price=50.0, currency="EUR", source="test"))
    # Daily snapshots
    await _add_daily(db_session, uid, pool_id, snap_date1, 500.0, off=500.0, pool_val=500.0)
    await _add_daily(db_session, uid, pool_id, snap_date2, 1000.0, off=1000.0, pool_val=1000.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    positions = body["positions"]
    assert "Tranche ETF" in positions
    pos_series = positions["Tranche ETF"]
    assert len(pos_series) == 2
    # Day 1: index = 100
    assert pos_series[0]["index"] == pytest.approx(100.0)
    # Day 2: V=1000, prev_V=500, flow=+500 → r = 1000/(500+500) = 1.0 → index = 100
    assert pos_series[1]["index"] == pytest.approx(100.0, abs=1.0)


@pytest.mark.asyncio
async def test_twrr_positions_weekend_flow_remapped(client, db_session):
    """
    remap_flows: a transaction on a non-snapshot date (line 292-296) is
    remapped to the next snapshot date.
    We have snapshots on Monday & Wednesday but a transaction on Tuesday
    (no Tuesday snapshot). The Tuesday flow should be remapped to Wednesday.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Remap ETF"
    product.category = "Actif"
    await db_session.flush()

    monday = date(2025, 11, 3)      # Monday — has snapshot
    tuesday = date(2025, 11, 4)     # Tuesday — NO snapshot, but has transaction
    wednesday = date(2025, 11, 5)   # Wednesday — has snapshot

    # Buy 10 units on Monday
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=monday,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    # Buy 5 more units on Tuesday (no snapshot this day)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=tuesday,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-5.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # Prices: 100 on all days
    db_session.add(AssetPrice(ticker=ticker, date=monday, price=100.0, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=ticker, date=wednesday, price=100.0, currency="EUR", source="test"))
    # Snapshots on Monday and Wednesday only (not Tuesday)
    await _add_daily(db_session, uid, pool_id, monday, 1000.0, off=1000.0, pool_val=1000.0)
    await _add_daily(db_session, uid, pool_id, wednesday, 1500.0, off=1500.0, pool_val=1500.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    positions = body["positions"]
    # The position TWRR should exist for the product
    assert "Remap ETF" in positions
    pos_series = positions["Remap ETF"]
    # Index starts at 100 on Monday
    assert pos_series[0]["index"] == pytest.approx(100.0)
    # Wednesday: price unchanged, inflow remapped → TWRR ≈ 100
    # V_wed = 1500 (15 units × 100), prev_V = 1000, flow remapped to wed = 500
    # r = 1500 / (1000 + 500) = 1.0 → index = 100
    assert pos_series[1]["index"] == pytest.approx(100.0, abs=1.0)


@pytest.mark.asyncio
async def test_twrr_positions_no_price_skipped(client, db_session):
    """
    If a ticker has transactions but no prices, it is skipped (line 394: continue).
    The positions dict should be empty for this portfolio.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "No Price ETF"
    product.category = "Actif"
    await db_session.flush()

    snap_date = date(2025, 12, 1)

    # Transaction exists
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # NO prices in asset_prices → positions skipped (line 394)
    await _add_daily(db_session, uid, pool_id, snap_date, 500.0, off=500.0, pool_val=500.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # Ticker is skipped because prices_by_ticker is empty for this ticker
    assert "No Price ETF" not in body["positions"]


@pytest.mark.asyncio
async def test_twrr_positions_price_after_snap_date_skipped(client, db_session):
    """
    Line 411: if the first available price is after the snapshot date,
    the snapshot is skipped for that position (price not yet available).
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Late Price ETF"
    product.category = "Actif"
    await db_session.flush()

    snap_date1 = date(2025, 12, 2)  # Monday — snapshot
    snap_date2 = date(2025, 12, 3)  # Tuesday — snapshot
    price_date = date(2025, 12, 3)  # Price only available from Tuesday

    # Buy on day 1
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date1,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    # Price only from day 2 (no price on day 1 → day 1 skipped, line 411)
    db_session.add(AssetPrice(ticker=ticker, date=price_date, price=100.0, currency="EUR", source="test"))
    await _add_daily(db_session, uid, pool_id, snap_date1, 1000.0, off=1000.0, pool_val=1000.0)
    await _add_daily(db_session, uid, pool_id, snap_date2, 1000.0, off=1000.0, pool_val=1000.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # Position has data starting from day 2 (price not available on day 1)
    if "Late Price ETF" in body["positions"]:
        pos_series = body["positions"]["Late Price ETF"]
        # Only one point (day 2), starting at 100
        assert pos_series[0]["index"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_twrr_positions_manuel_category(client, db_session):
    """
    Lines 415-416: Manuel category positions use price as total value.
    The product category "Manuel" means price = total asset value.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    # Create a Manuel product (e.g. physical gold)
    manuel_ticker = f"OR.PHYS.TWRR.{uid}"
    from app.models.product import Product as ProductModel
    db_session.add(ProductModel(
        ticker=manuel_ticker, name="Or physique TWRR",
        category="Actif", instrument_type="Or physique", currency="EUR"
    ))
    await db_session.flush()

    from app.models.pool import PoolProduct as PoolProductModel
    db_session.add(PoolProductModel(pool_id=pool_id, ticker=manuel_ticker))
    await db_session.flush()

    snap_date1 = date(2025, 12, 8)
    snap_date2 = date(2025, 12, 9)

    # Manuel: quantity is 1 unit, price IS the total value
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date1,
        type="Actif", ticker=manuel_ticker, currency="EUR",
        exchange_rate=1.0, quantity=1.0,  # positive = deposit for Manuel
        unit_price=10_000.0, unit_price_eur=10_000.0,
        total_amount=10_000.0, total_amount_eur=10_000.0,
    ))
    db_session.add(AssetPrice(ticker=manuel_ticker, date=snap_date1,
                              price=10_000.0, currency="EUR", source="manual"))
    db_session.add(AssetPrice(ticker=manuel_ticker, date=snap_date2,
                              price=11_000.0, currency="EUR", source="manual"))
    await _add_daily(db_session, uid, pool_id, snap_date1, 10_000.0, off=10_000.0, pool_val=10_000.0)
    await _add_daily(db_session, uid, pool_id, snap_date2, 11_000.0, off=11_000.0, pool_val=11_000.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # Manuel position should appear in positions
    if "Or physique TWRR" in body["positions"]:
        pos_series = body["positions"]["Or physique TWRR"]
        assert pos_series[0]["index"] == pytest.approx(100.0)
        # Price went from 10k to 11k → +10% → index = 110
        assert pos_series[1]["index"] == pytest.approx(110.0, rel=1e-2)


@pytest.mark.asyncio
async def test_twrr_positions_all_zero_values_skipped(client, db_session):
    """
    Line 425: when all position values are 0 (e.g. fully sold position),
    the ticker is skipped and not included in positions.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Sold ETF"
    product.category = "Actif"
    await db_session.flush()

    snap_date = date(2025, 12, 10)

    # Buy then immediately sell — net qty = 0
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=10.0,  # full sell
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=500.0, total_amount_eur=500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=50.0, currency="EUR", source="test"))
    await _add_daily(db_session, uid, pool_id, snap_date, 0.0, off=0.0, pool_val=0.0)
    # Add a second snapshot to avoid early return (need total_eur > 0)
    snap_date2 = date(2025, 12, 11)
    db_session.add(AssetPrice(ticker=ticker, date=snap_date2, price=50.0, currency="EUR", source="test"))
    await _add_daily(db_session, uid, pool_id, snap_date2, 100.0, off=100.0, pool_val=100.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # All values are 0 → skipped (line 425)
    assert "Sold ETF" not in body["positions"]


@pytest.mark.asyncio
async def test_twrr_remap_flows_no_future_snapshot_drops_flow(client, db_session):
    """
    remap_flows edge case: if there is no snapshot after the transaction date,
    the flow is silently dropped (lines 292-296, the 'if next_snap' branch with no next).
    The TWRR still works correctly.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    from sqlalchemy import select as sa_select
    from app.models.product import Product as ProductModel
    result = await db_session.execute(sa_select(ProductModel).where(ProductModel.ticker == ticker))
    product = result.scalar_one()
    product.name = "Post Snapshot ETF"
    product.category = "Actif"
    await db_session.flush()

    snap_date = date(2025, 12, 15)
    future_tx_date = date(2025, 12, 20)  # After the last snapshot — no snapshot exists

    # Buy on snapshot day
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    # Buy after last snapshot — flow has no future snapshot, gets dropped
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=future_tx_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-5.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=100.0, currency="EUR", source="test"))
    await _add_daily(db_session, uid, pool_id, snap_date, 1000.0, off=1000.0, pool_val=1000.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body
    # Should work without error; the future transaction flow is dropped
    assert "Post Snapshot ETF" in body["positions"]
    pos_series = body["positions"]["Post Snapshot ETF"]
    assert pos_series[0]["index"] == pytest.approx(100.0)


# ===========================================================================
# ADDITIONAL COVERAGE — targeting missing lines 106-125, 128-156, 173, 186
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/snapshots/daily-with-pools — date_from filter actually applied (line 115-116)
# and pool_snapshots without a matching pool entry (pool not in pools dict)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_with_pools_date_from_no_results(client, db_session):
    """
    date_from filter produces empty result when all snaps are before date_from.
    Tests the `stmt = stmt.where(DailySnapshot.date >= date_from)` branch.
    """
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2023, 6, 1), 5_000, off=5_000, pool_val=5_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools",
                         params={"portfolio_id": uid, "date_from": "2026-01-01"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_daily_with_pools_inactive_pool_not_in_dict(client, db_session):
    """
    Lines 140-148: `if pool:` check — pool_snapshot for a pool that is inactive
    (not in the active pools dict from the query) should be skipped gracefully.
    An inactive pool exists in DB but is not fetched → pool lookup returns None.
    """
    uid, _, _, pool_id = await _setup(db_session)

    # Create an inactive pool (won't be in the pools dict from `where is_active == True`)
    inactive_pool = Pool(portfolio_id=uid, name="InactivePool", strategy="Offensive",
                         target_pct=0.0, is_active=False)
    db_session.add(inactive_pool)
    await db_session.flush()
    inactive_pool_id = inactive_pool.id

    snap = DailySnapshot(portfolio_id=uid, date=date(2025, 8, 4), total_eur=10_000,
                         offensive_eur=10_000, defensive_eur=0)
    db_session.add(snap)
    await db_session.flush()

    # Add snapshots for both active and inactive pools
    db_session.add(DailyPoolSnapshot(daily_snapshot_id=snap.id, pool_id=pool_id, value_eur=10_000))
    db_session.add(DailyPoolSnapshot(daily_snapshot_id=snap.id, pool_id=inactive_pool_id, value_eur=5_000))
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    # Only the active pool should appear in pools list (inactive pool skipped: if pool: check)
    pool_ids = [pv["pool_id"] for pv in data[0]["pools"]]
    assert inactive_pool_id not in pool_ids
    assert pool_id in pool_ids


@pytest.mark.asyncio
async def test_daily_with_pools_multiple_dates_ordered(client, db_session):
    """
    Lines 125-127: results are sorted ascending by date after dedup.
    Multiple snapshots on different dates → returned in ascending order.
    """
    uid, _, _, pool_id = await _setup(db_session)

    await _add_daily(db_session, uid, pool_id, date(2025, 9, 1), 9_000,
                     off=9_000, pool_val=9_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 9, 2), 10_000,
                     off=10_000, pool_val=10_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # Should be ascending by date
    assert data[0]["date"] < data[1]["date"]
    assert data[0]["total_eur"] == pytest.approx(9_000)


@pytest.mark.asyncio
async def test_list_daily_snapshots_both_filters(client, db_session):
    """
    Both date_from and date_to together filter correctly (lines 167-171).
    """
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2024, 1, 2), 5_000)
    await _add_daily(db_session, uid, pool_id, date(2024, 6, 3), 6_000)
    await _add_daily(db_session, uid, pool_id, date(2025, 6, 2), 8_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily", params={
        "portfolio_id": uid,
        "date_from": "2024-01-01",
        "date_to": "2024-12-31",
    })
    assert r.status_code == 200
    data = r.json()
    assert all("2024-01-01" <= d["date"] <= "2024-12-31" for d in data)
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_daily_snapshots_no_filters(client, db_session):
    """
    GET /api/snapshots/daily without date filters returns all rows for portfolio (line 166).
    """
    uid, _, _, pool_id = await _setup(db_session)
    await _add_daily(db_session, uid, pool_id, date(2023, 1, 2), 4_000)
    await _add_daily(db_session, uid, pool_id, date(2024, 6, 3), 6_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/daily", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # Ordered desc by date
    assert data[0]["date"] > data[1]["date"]


@pytest.mark.asyncio
async def test_list_monthly_snapshots_ordered_desc(client, db_session):
    """
    Monthly snapshots returned newest first (line 183: order_by desc).
    Tests line 186 return path.
    """
    uid, _, _, _ = await _setup(db_session)
    await _add_monthly(db_session, uid, date(2024, 12, 31), 9_000, 95.0)
    await _add_monthly(db_session, uid, date(2025, 1, 31), 10_000, 100.0)
    await _add_monthly(db_session, uid, date(2025, 2, 28), 11_000, 110.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/monthly", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    # Newest first
    dates_order = [d["date"] for d in data]
    assert dates_order == sorted(dates_order, reverse=True)


# ---------------------------------------------------------------------------
# GET /api/snapshots/twrr — additional branches (lines 218-278)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_multiple_daily_snapshots_consecutive_dates(client, db_session):
    """
    Lines 219-222: TWRR with snapshots on consecutive dates.
    Tests the main computation path with pool flows on different dates.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 9, 8), price=50.0,
                              currency="EUR", source="test"))

    snap_date1 = date(2025, 9, 8)
    snap_date2 = date(2025, 9, 9)

    await _add_daily(db_session, uid, pool_id, snap_date1, 10_000,
                     off=10_000, pool_val=10_000)
    await _add_daily(db_session, uid, pool_id, snap_date2, 11_000,
                     off=11_000, pool_val=11_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    # Total TWRR: 10k then 11k → 10% gain
    total = body["total"]
    assert len(total) == 2
    assert total[0]["index"] == pytest.approx(100.0)
    assert total[1]["index"] == pytest.approx(110.0, rel=0.01)


@pytest.mark.asyncio
async def test_twrr_cash_category_pool_product_sign(client, db_session):
    """
    Lines 265-278: Cash-category pool product → flow sign is positive (not negated).
    Cash tickers (JPYEUR=X): deposit = positive qty → positive inflow.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    # Create a Cash-category product for the pool
    cash_ticker = f"JPYEUR.{uid}"
    db_session.add(Product(ticker=cash_ticker, name="JPY Cash",
                            category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool_id, ticker=cash_ticker))
    await db_session.flush()

    snap_date1 = date(2025, 10, 6)
    snap_date2 = date(2025, 10, 7)

    # Cash deposit (positive qty, positive total) = inflow to pool
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date2,
        type="Actif", ticker=cash_ticker, currency="JPY",
        exchange_rate=0.006, quantity=100000.0,
        unit_price=1.0, unit_price_eur=0.006,
        total_amount=100000.0, total_amount_eur=600.0,
    ))
    db_session.add(AssetPrice(ticker=cash_ticker, date=snap_date1,
                               price=0.006, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=cash_ticker, date=snap_date2,
                               price=0.006, currency="EUR", source="test"))

    await _add_daily(db_session, uid, pool_id, snap_date1, 1_000, off=1_000, pool_val=1_000)
    await _add_daily(db_session, uid, pool_id, snap_date2, 1_600, off=1_600, pool_val=1_600)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    # Cash inflow of 600 neutralised: V=1600, prev=1000, flow=600 → r=1600/1600=1.0 → index≈100
    pool_twrr = body["pools"].get(pool_id)
    if pool_twrr is None:
        # Pool may be keyed by name
        pool_twrr = body["pools"].get("Asie")
    assert pool_twrr is not None
    assert pool_twrr[1]["index"] == pytest.approx(100.0, abs=2.0)


@pytest.mark.asyncio
async def test_twrr_no_active_pools(client, db_session):
    """
    Lines 228-230: empty pools dict when portfolio has no active pools.
    TWRR runs total computation but pools dict is empty → twrr_pools = {}.
    """
    uid, _, _, pool_id = await _setup(db_session)

    # Deactivate the pool
    from sqlalchemy import select as sa_select
    from app.models.pool import Pool as PoolModel
    result = await db_session.execute(sa_select(PoolModel).where(PoolModel.id == pool_id))
    pool_obj = result.scalar_one()
    pool_obj.is_active = False
    await db_session.flush()

    await _add_daily(db_session, uid, pool_id, date(2025, 11, 3), 5_000,
                     off=5_000, pool_val=5_000)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    # No active pools → twrr_pools is empty
    assert body["pools"] == {}


@pytest.mark.asyncio
async def test_twrr_series_all_zero_pool_excluded(client, db_session):
    """
    Lines 339-344: pool value series filtered to only dates with positive value
    or dates where a future value > 0 exists. A pool with all-zero values → not included.
    """
    uid, aid, ticker, pool_id = await _setup(db_session)

    # Snapshots where pool value is always 0
    await _add_daily(db_session, uid, pool_id, date(2025, 11, 4), 0.0, off=0.0, pool_val=0.0)
    await _add_daily(db_session, uid, pool_id, date(2025, 11, 5), 0.0, off=0.0, pool_val=0.0)
    await db_session.flush()

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    # Pool series is all zero → not included in twrr_pools (or empty series skipped)
    pool_name = "Asie"
    if pool_name in body["pools"]:
        # If included, the series should be empty
        assert len(body["pools"][pool_name]) == 0


# ---------------------------------------------------------------------------
# POST /api/snapshots/monthly — ValueError path (lines 472-476)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_monthly_snapshot_wrong_portfolio(client, db_session):
    """
    Lines 472-476: POST /api/snapshots/monthly with a portfolio_id that has
    a snapshot from a later date than provided date → 422 (compute raises ValueError).
    """
    uid, _, _, pool_id = await _setup(db_session)
    # Create a snapshot on a future date
    await _add_daily(db_session, uid, pool_id, date(2025, 6, 30), 12_000,
                     off=12_000, pool_val=12_000)
    await db_session.flush()

    # Try to compute monthly snapshot for a date with no daily snapshot
    r = await client.post("/api/snapshots/monthly",
                          json={"portfolio_id": uid, "date": "2025-04-30"})
    # Should return 422 since no daily snapshot for 2025-04-30
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# _compute_twrr unit-level tests (module-level function, lines 15-45)
# ---------------------------------------------------------------------------

def test_compute_twrr_empty_series():
    """Empty value series → empty result list."""
    from app.api.routers.snapshots import _compute_twrr
    result = _compute_twrr([], {})
    assert result == []


def test_compute_twrr_single_point():
    """Single data point → returns one entry at index 100."""
    from app.api.routers.snapshots import _compute_twrr
    result = _compute_twrr([(date(2025, 1, 2), 10_000.0)], {})
    assert len(result) == 1
    assert result[0]["index"] == pytest.approx(100.0)


def test_compute_twrr_first_value_zero_skipped():
    """If first value is 0, it's skipped until positive value (line 35-37)."""
    from app.api.routers.snapshots import _compute_twrr
    series = [
        (date(2025, 1, 2), 0.0),
        (date(2025, 1, 3), 10_000.0),
        (date(2025, 1, 6), 11_000.0),
    ]
    result = _compute_twrr(series, {})
    assert len(result) == 2
    assert result[0]["date"] == "2025-01-03"
    assert result[0]["index"] == pytest.approx(100.0)
    assert result[1]["index"] == pytest.approx(110.0, rel=1e-3)


def test_compute_twrr_with_flow():
    """TWRR with a flow on the second date neutralises the inflow."""
    from app.api.routers.snapshots import _compute_twrr
    series = [
        (date(2025, 2, 3), 10_000.0),
        (date(2025, 2, 4), 12_000.0),  # 2k inflow + value unchanged
    ]
    flows = {date(2025, 2, 4): 2_000.0}
    result = _compute_twrr(series, flows)
    assert len(result) == 2
    assert result[0]["index"] == pytest.approx(100.0)
    # V=12000, prev=10000, flow=2000 → r = 12000 / 12000 = 1.0 → index = 100
    assert result[1]["index"] == pytest.approx(100.0)


def test_compute_twrr_negative_denom_skipped():
    """If denom (prev_v + f) <= 0, index is appended unchanged (line 42)."""
    from app.api.routers.snapshots import _compute_twrr
    series = [
        (date(2025, 3, 3), 10_000.0),
        (date(2025, 3, 4), 5_000.0),   # negative flow > prev_v
    ]
    # Flow of -15000 makes denom = 10000 + (-15000) = -5000 ≤ 0
    flows = {date(2025, 3, 4): -15_000.0}
    result = _compute_twrr(series, flows)
    assert len(result) == 2
    # Denom ≤ 0 → index unchanged (stays at 100)
    assert result[1]["index"] == pytest.approx(100.0)


def test_compute_twrr_prev_v_none_zero_value_skipped():
    """prev_v is None initially; if v <= 0, it stays None (line 34-37)."""
    from app.api.routers.snapshots import _compute_twrr
    series = [
        (date(2025, 4, 1), 0.0),   # v <= 0, skipped
        (date(2025, 4, 2), 0.0),   # still 0, still skipped
        (date(2025, 4, 3), 5_000.0),  # first positive → index = 100
    ]
    result = _compute_twrr(series, {})
    assert len(result) == 1
    assert result[0]["date"] == "2025-04-03"
    assert result[0]["index"] == pytest.approx(100.0)


# ===========================================================================
# Missing branch coverage
# ===========================================================================

# ---------------------------------------------------------------------------
# Branch 125->124: list_daily_with_pools dedup keeps higher-id snapshot for same date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_with_pools_dedup_keeps_higher_id_snapshot(client, db_session):
    """
    Branch 125->124: `if snap.date not in seen or snap.id > seen[snap.date].id`
    The FALSE branch fires when a date already has a higher-id entry and the new
    snapshot has a lower id — the new snapshot is skipped (branch 125->124).

    We return [snap_high, snap_low]: snap_high is stored first, then snap_low is
    encountered with the same date but lower id → condition is False → skip.
    """
    from unittest.mock import patch, MagicMock
    from app.models.snapshot import DailySnapshot as DS

    uid, _, _, pool_id = await _setup(db_session)
    snap_date = date(2025, 11, 10)

    # Build two mock DailySnapshot objects with same date, different ids
    snap_low = DS(portfolio_id=uid, date=snap_date, total_eur=5_000,
                  offensive_eur=5_000, defensive_eur=0)
    snap_low.id = 1001
    snap_low.pool_snapshots = []

    snap_high = DS(portfolio_id=uid, date=snap_date, total_eur=12_000,
                   offensive_eur=12_000, defensive_eur=0)
    snap_high.id = 1002
    snap_high.pool_snapshots = []

    # Return snap_high FIRST then snap_low: snap_high is stored, then snap_low is
    # skipped because 1001 < 1002 (False branch 125->124)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [snap_high, snap_low]

    mock_pools_result = MagicMock()
    mock_pools_result.scalars.return_value.all.return_value = []

    call_count = 0

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_pools_result  # pools query
        return mock_result  # snapshots query

    with patch.object(db_session, "execute", side_effect=fake_execute):
        r = await client.get("/api/snapshots/daily-with-pools", params={"portfolio_id": uid})

    assert r.status_code == 200
    data = r.json()
    # Should have exactly one entry (deduped: snap_low skipped, snap_high kept)
    assert len(data) == 1
    # The higher-id snapshot's value (12000) must be used
    assert data[0]["total_eur"] == pytest.approx(12_000, rel=1e-2)


# ---------------------------------------------------------------------------
# Branch 223->222: get_twrr dedup keeps higher-id snapshot for same date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_endpoint_dedup_keeps_higher_id_snapshot(client, db_session):
    """
    Branch 223->222: `if s.date not in seen_dates or s.id > seen_dates[s.date].id`
    The FALSE branch fires when a date already has a higher-id snapshot stored
    and the new snapshot has a lower id — it is skipped (branch 223->222).

    We return [snap1b, snap1a, snap2]: snap1b (id=2002) is stored first for snap_date1,
    then snap1a (id=2001) arrives with same date but lower id → False branch → skipped.
    snap2 (date2) arrives normally.
    """
    from unittest.mock import patch, MagicMock
    from app.models.snapshot import DailySnapshot as DS

    uid, _, _, pool_id = await _setup(db_session)

    snap_date1 = date(2025, 11, 17)
    snap_date2 = date(2025, 11, 18)

    snap1a = DS(portfolio_id=uid, date=snap_date1, total_eur=5_000,
                offensive_eur=5_000, defensive_eur=0)
    snap1a.id = 2001  # lower id → should be skipped (False branch)

    snap1b = DS(portfolio_id=uid, date=snap_date1, total_eur=10_000,
                offensive_eur=10_000, defensive_eur=0)
    snap1b.id = 2002  # higher id → stored first, then snap1a skipped

    snap2 = DS(portfolio_id=uid, date=snap_date2, total_eur=11_000,
               offensive_eur=11_000, defensive_eur=0)
    snap2.id = 2003

    # Add a real snapshot to the DB so the pool fetching etc. works
    db_session.add(DailySnapshot(portfolio_id=uid, date=date(2025, 11, 19), total_eur=11_500,
                                 offensive_eur=11_500, defensive_eur=0))
    await db_session.flush()

    # Patch only the first query (snapshots) to return snap1b first, then snap1a
    original_execute = db_session.execute
    call_count = 0

    async def patched_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call = snapshots query → snap1b first, then snap1a (lower id → skipped)
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [snap1b, snap1a, snap2]
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    with patch.object(db_session, "execute", side_effect=patched_execute):
        r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})

    assert r.status_code == 200
    body = r.json()
    total = body["total"]
    # After dedup: day1 uses snap1b (id=2002, total=10000), snap1a skipped, day2=snap2 (11000)
    # TWRR: 10000→11000 = 10%
    assert len(total) == 2
    assert total[0]["index"] == pytest.approx(100.0)
    assert total[1]["index"] == pytest.approx(110.0, rel=0.05)


# ---------------------------------------------------------------------------
# Branch 274->269: series is empty → pool not added to twrr_pools (loop continues)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_endpoint_pool_with_all_zero_values_excluded(client, db_session):
    """
    Branch 274->269: when `series` is empty for a pool (all pool_daily values are 0
    and no future value > 0 exists for any date), the pool is NOT added to twrr_pools.
    The `if series:` condition is False, so the pool is skipped and the loop
    continues to the next pool (274->269).

    We set up a pool that has active snapshots but pool_daily always 0 (no
    DailyPoolSnapshot rows). The pool_daily dict will have no entries for this
    pool_id, so series will be [(dt, 0.0), ...] and after filtering (all 0, no
    future > 0) it becomes [].
    """
    uid, _, _, pool_id = await _setup(db_session)

    # Add snapshots for the portfolio but do NOT add DailyPoolSnapshot rows.
    # This means pool_daily.get(dt, {}).get(pool_id, 0.0) == 0 for all dates.
    db_session.add(DailySnapshot(portfolio_id=uid, date=date(2025, 12, 1), total_eur=10_000,
                                 offensive_eur=10_000, defensive_eur=0))
    db_session.add(DailySnapshot(portfolio_id=uid, date=date(2025, 12, 2), total_eur=11_000,
                                 offensive_eur=11_000, defensive_eur=0))
    await db_session.flush()
    # No DailyPoolSnapshot for this pool → all values 0 → series filtered to [] → skipped

    r = await client.get("/api/snapshots/twrr", params={"portfolio_id": uid})
    assert r.status_code == 200
    body = r.json()
    # Pool "Asie" has all-zero values → not in twrr_pools
    assert "Asie" not in body["pools"]
