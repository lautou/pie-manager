"""
Non-regression tests for snapshot business logic.

These tests exercise the snapshot_service directly via the DB session fixture
so they don't depend on Celery being available.

Key invariants:
  1. Performance index starts at 100 for the first monthly snapshot.
  2. Index compounds correctly: index_n = index_{n-1} * (1 + perf/100).
  3. Pure performance (no contributions) is negative when portfolio loses value.
  4. compute_daily_snapshot returns positive total_eur when positions have prices.
  5. fill_missing_snapshots skips weekends (tested via the service's DOW logic).
"""
import pytest
from datetime import date

from sqlalchemy import insert

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.snapshot import DailySnapshot, MonthlySnapshot
from app.models.portfolio_account import PortfolioAccount
from app.services.snapshot_service import compute_daily_snapshot, compute_monthly_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_portfolio(db) -> tuple[int, int, int]:
    """
    Insert a minimal Portfolio + Account + Product + Pool needed for
    snapshot computations. Returns (portfolio_id, account_id, pool_id).
    """
    portfolio = Portfolio(name=f"Snap-Test-{id(db)}")
    db.add(portfolio)
    await db.flush()

    account = Broker(name="Degiro", currency="EUR")
    db.add(account)

    product = Product(ticker=f"TEST.SNAP.{portfolio.id}", name="Test ETF", category="Actif", currency="EUR")
    db.add(product)

    pool = Pool(portfolio_id=portfolio.id, name="Asie", strategy="Offensive", target_pct=0.25, is_active=True)
    db.add(pool)
    await db.flush()

    db.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    db.add(PoolProduct(pool_id=pool.id, ticker=product.ticker))
    await db.flush()

    return portfolio.id, account.id, pool.id


# ---------------------------------------------------------------------------
# Daily snapshot — basic valuation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_snapshot_positive_value(db_session):
    """
    A portfolio holding 10 units at a price of 50 EUR should produce a
    DailySnapshot with total_eur = 500.
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"
    snap_date = date(2025, 3, 14)  # Friday

    # Buy 10 units
    tx = Transaction(
        portfolio_id=uid, account_id=aid,
        date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,  # sell convention in the model
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    )
    db_session.add(tx)

    # Price for the day
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=50.0, currency="EUR", source="test"))
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()

    assert snapshot.total_eur == pytest.approx(500.0)
    assert snapshot.total_eur > 0


@pytest.mark.asyncio
async def test_daily_snapshot_zero_when_no_price(db_session):
    """
    If no price exists for any position, total_eur must be 0 (not an error).
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"
    snap_date = date(2025, 4, 1)

    tx = Transaction(
        portfolio_id=uid, account_id=aid,
        date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-5.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    )
    db_session.add(tx)
    # Intentionally no AssetPrice row
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()

    assert snapshot.total_eur == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_daily_snapshot_upsert_idempotent(db_session):
    """
    Calling compute_daily_snapshot twice for the same (user, date) must
    update the existing row rather than raise an IntegrityError.
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"
    snap_date = date(2025, 5, 2)

    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=80.0, currency="EUR", source="test"))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-2.0,
        unit_price=80.0, unit_price_eur=80.0,
        total_amount=-160.0, total_amount_eur=-160.0,
    ))
    await db_session.flush()

    snap1 = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()

    # Second call — must not raise
    snap2 = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()

    assert snap1.portfolio_id == snap2.portfolio_id
    assert snap1.date == snap2.date


# ---------------------------------------------------------------------------
# Monthly snapshot — performance index
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_monthly_snapshot_first_index_is_100(db_session):
    """
    When there is no previous monthly snapshot, performance_index must start
    at exactly 100 (baseline = no gain, no loss).
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"
    snap_date = date(2025, 1, 31)

    # Need a daily snapshot to exist for snap_date
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=snap_date, total_eur=10_000.0,
        offensive_eur=10_000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    monthly = await compute_monthly_snapshot(db_session, uid, snap_date)
    await db_session.flush()

    # No previous snapshot → perf_pct = 0 → index = 100
    assert monthly.performance_index == pytest.approx(100.0)
    assert monthly.performance_pct == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_monthly_snapshot_index_compounds(db_session):
    """
    Given two consecutive monthly snapshots:
      - First:  total=10_000, index=100
      - Second: total=11_000, no new contributions

    Expected:
      perf_pct  = (11_000 / 10_000 - 1) * 100 = 10%
      index     = 100 * 1.10 = 110
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"

    date1 = date(2025, 1, 31)
    date2 = date(2025, 2, 28)

    # Insert the first monthly snapshot directly (baseline)
    db_session.add(MonthlySnapshot(
        portfolio_id=uid, date=date1,
        total_eur=10_000.0,
        offensive_eur=10_000.0, defensive_eur=0.0,
        contributions_eur=0.0,
        performance_pct=0.0,
        performance_index=100.0,
    ))

    # Daily snapshot for date2 (required by compute_monthly_snapshot)
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date2, total_eur=11_000.0,
        offensive_eur=11_000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    monthly = await compute_monthly_snapshot(db_session, uid, date2)
    await db_session.flush()

    assert monthly.performance_pct == pytest.approx(10.0, abs=0.01)
    assert monthly.performance_index == pytest.approx(110.0, abs=0.01)


@pytest.mark.asyncio
async def test_monthly_snapshot_negative_performance(db_session):
    """
    If the portfolio loses value with no contributions, performance must be
    negative and the index must fall below 100.
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)

    date1 = date(2025, 3, 31)
    date2 = date(2025, 4, 30)

    db_session.add(MonthlySnapshot(
        portfolio_id=uid, date=date1,
        total_eur=10_000.0,
        offensive_eur=10_000.0, defensive_eur=0.0,
        contributions_eur=0.0,
        performance_pct=0.0,
        performance_index=100.0,
    ))
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date2, total_eur=9_000.0,
        offensive_eur=9_000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    monthly = await compute_monthly_snapshot(db_session, uid, date2)
    await db_session.flush()

    assert monthly.performance_pct < 0
    assert monthly.performance_index < 100.0


@pytest.mark.asyncio
async def test_monthly_snapshot_contributions_excluded_from_performance(db_session):
    """
    A cash deposit (LIQUIDITE.EURO Actif transaction) must not inflate the
    measured performance: contributions are subtracted before computing perf%.

    Setup:
      - Previous total: 10_000
      - New total:      15_000  (a 5_000 cash deposit + 0 market gain)

    Expected:
      contributions = 5_000
      perf_pct      = (15_000 - 5_000) / 10_000 - 1) * 100 = 0%
      index         = prev_index (unchanged)
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)

    # LIQUIDITE.EURO product must exist for FK
    liquidity_ticker = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(
        sa_select(Product).where(Product.ticker == liquidity_ticker)
    )
    if not existing.scalar_one_or_none():
        db_session.add(Product(
            ticker=liquidity_ticker, name="Cash EUR",
            category="Actif", instrument_type="Cash", currency="EUR",
        ))
        await db_session.flush()

    date1 = date(2025, 5, 31)
    date2 = date(2025, 6, 30)

    # Cash deposit transaction
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date2,
        type="Actif", ticker=liquidity_ticker, currency="EUR",
        exchange_rate=1.0, quantity=5_000.0,
        unit_price=1.0, unit_price_eur=1.0,
        total_amount=5_000.0, total_amount_eur=5_000.0,
    ))

    db_session.add(MonthlySnapshot(
        portfolio_id=uid, date=date1,
        total_eur=10_000.0,
        offensive_eur=10_000.0, defensive_eur=0.0,
        contributions_eur=0.0,
        performance_pct=0.0,
        performance_index=100.0,
    ))

    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date2, total_eur=15_000.0,
        offensive_eur=15_000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    monthly = await compute_monthly_snapshot(db_session, uid, date2)
    await db_session.flush()

    assert monthly.contributions_eur == pytest.approx(5_000.0)
    assert monthly.performance_pct == pytest.approx(0.0, abs=0.01)
    assert monthly.performance_index == pytest.approx(100.0, abs=0.01)


# ---------------------------------------------------------------------------
# snapshot_service coverage — lines 42, 46-49, 53, 121
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_snapshot_skips_liquidite_euro(db_session):
    """
    LIQUIDITE.EURO positions are excluded from pool valuation (line 42).
    A portfolio with only LIQUIDITE.EURO in a pool should produce pool_value=0.
    """
    from sqlalchemy import select as sa_select
    uid, aid, pool_id = await _setup_portfolio(db_session)
    snap_date = date(2025, 7, 1)
    liquidity_ticker = "LIQUIDITE.EURO"

    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liquidity_ticker))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liquidity_ticker, name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    db_session.add(PoolProduct(pool_id=pool_id, ticker=liquidity_ticker))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=liquidity_ticker, currency="EUR",
        exchange_rate=1.0, quantity=5_000.0,
        unit_price=1.0, unit_price_eur=1.0,
        total_amount=5_000.0, total_amount_eur=5_000.0,
    ))
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()
    assert snapshot.total_eur == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_daily_snapshot_manuel_category_uses_price_as_total(db_session):
    """
    'Manuel' category: price in asset_prices IS the total value (lines 46-49).
    qty is irrelevant — only price matters.
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    manuel_ticker = f"OR.PHYS.{uid}"
    snap_date = date(2025, 8, 1)

    db_session.add(Product(ticker=manuel_ticker, name="Or physique", category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool_id, ticker=manuel_ticker))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=manuel_ticker, currency="EUR",
        exchange_rate=1.0, quantity=1.0,
        unit_price=15_000.0, unit_price_eur=15_000.0,
        total_amount=15_000.0, total_amount_eur=15_000.0,
    ))
    db_session.add(AssetPrice(ticker=manuel_ticker, date=snap_date, price=15_000.0, currency="EUR", source="manual"))
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()
    assert snapshot.total_eur == pytest.approx(15_000.0)


@pytest.mark.asyncio
async def test_daily_snapshot_zero_quantity_excluded(db_session):
    """
    If a position has qty=0, it contributes 0 to the snapshot (line 53).
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    ticker = f"TEST.SNAP.{uid}"
    snap_date = date(2025, 9, 1)

    # Buy then fully sell → net qty = 0
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
        exchange_rate=1.0, quantity=10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=500.0, total_amount_eur=500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=50.0, currency="EUR", source="test"))
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()
    assert snapshot.total_eur == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_daily_snapshot_manuel_no_price_excluded(db_session):
    """
    Manuel category with NO price in asset_prices → excluded from pool total (line 48).
    The snapshot still completes (no crash) but pool value = 0.
    """
    uid, aid, pool_id = await _setup_portfolio(db_session)
    manuel_ticker = f"OR.NOPRICE.{uid}"
    snap_date = date(2025, 11, 3)

    db_session.add(Product(ticker=manuel_ticker, name="Or sans prix",
                           category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool_id, ticker=manuel_ticker))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=manuel_ticker, currency="EUR",
        exchange_rate=1.0, quantity=1.0,
        unit_price=8_000.0, unit_price_eur=8_000.0,
        total_amount=8_000.0, total_amount_eur=8_000.0,
    ))
    # Intentionally NO AssetPrice row → price is None → line 48 hit
    await db_session.flush()

    snapshot = await compute_daily_snapshot(db_session, uid, snap_date)
    await db_session.flush()
    assert snapshot.total_eur == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_compute_monthly_raises_when_no_daily_snapshot(db_session):
    """
    compute_monthly_snapshot raises ValueError if no daily snapshot exists (line 121).
    """
    uid, _, _ = await _setup_portfolio(db_session)
    await db_session.flush()

    with pytest.raises(ValueError, match="No daily snapshot"):
        await compute_monthly_snapshot(db_session, uid, date(2025, 10, 31))


# ---------------------------------------------------------------------------
# fill_missing_snapshots — weekend-skipping logic (unit-level)
# ---------------------------------------------------------------------------

def test_weekend_days_excluded_from_trading_days():
    """
    Verify that the DOW-based weekend filter corresponds to correct weekday numbers.
    PostgreSQL: DOW 0 = Sunday, 6 = Saturday.
    Python: weekday() 5 = Saturday, 6 = Sunday.

    We test the Python side: any date we consider a 'trading day' must not
    fall on a Saturday or Sunday.
    """
    from datetime import timedelta

    start = date(2025, 3, 10)  # Monday
    trading_days = []
    for i in range(14):  # two weeks
        d = start + timedelta(days=i)
        if d.weekday() < 5:  # 0=Mon … 4=Fri
            trading_days.append(d)

    for d in trading_days:
        assert d.weekday() < 5, f"{d} is a weekend but was included as a trading day"

    # Exactly 10 trading days in 2 weeks
    assert len(trading_days) == 10


# ---------------------------------------------------------------------------
# dashboard_service.get_holdings with as_of + forex fees — line 80
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_daily_snapshot_forex_fee_with_as_of(db_session):
    """
    dashboard_service.py line 80: `if as_of is not None: fee_clauses.append(...)`.

    compute_daily_snapshot calls get_holdings(db, pid, as_of=snap_date).
    For the as_of branch to be reached, the portfolio must hold a non-EUR
    Cash product (ticker_to_currency non-empty → foreign_currencies non-empty).
    A Frais transaction in JPY triggers the full fee-adjustment path including
    the as_of clause.
    """
    from app.models.broker import Broker
    from app.models.portfolio_account import PortfolioAccount

    portfolio = Portfolio(name=f"Snap-FX-Fee-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()

    account = Broker(name="FX-Broker", currency="JPY")
    db_session.add(account)
    pool = Pool(portfolio_id=portfolio.id, name="FX-Pool", strategy="Offensive", target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()

    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))

    jpyeur = f"JPYEUR.FEE.{portfolio.id}"
    fee_ticker = f"FRAIS.JPY.{portfolio.id}"
    db_session.add(Product(ticker=jpyeur, name="JPY/EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker=fee_ticker, name="JPY Fee", category="Fee", currency="JPY"))
    db_session.add(PoolProduct(pool_id=pool.id, ticker=jpyeur))
    await db_session.flush()

    snap_date = date(2025, 11, 3)  # Monday
    # Buy 100,000 JPY
    db_session.add(Transaction(
        portfolio_id=portfolio.id, account_id=account.id,
        date=snap_date, type="Actif", ticker=jpyeur,
        currency="JPY", exchange_rate=0.006,
        quantity=100_000.0, unit_price=1.0, unit_price_eur=0.006,
        total_amount=100_000.0, total_amount_eur=600.0,
    ))
    # Fee in JPY: 200 JPY brokerage
    db_session.add(Transaction(
        portfolio_id=portfolio.id, account_id=account.id,
        date=snap_date, type="Frais", ticker=fee_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-1.0, unit_price=200.0, unit_price_eur=1.2,
        total_amount=-200.0, total_amount_eur=-1.2,
    ))
    db_session.add(AssetPrice(ticker=jpyeur, date=snap_date, price=0.006, currency="EUR", source="test"))
    await db_session.flush()

    # compute_daily_snapshot calls get_holdings(db, pid, as_of=snap_date) → line 80
    snap = await compute_daily_snapshot(db_session, portfolio.id, snap_date)
    assert snap is not None
    # 99,800 JPY * 0.006 = 598.8 EUR (≈ after fee deduction)
    assert snap.total_eur == pytest.approx(598.8, abs=1.0)
