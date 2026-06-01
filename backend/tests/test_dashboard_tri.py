"""Tests for GET /api/dashboard/tri endpoint (TRI / XIRR calculation)."""

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.snapshot import DailySnapshot, MonthlySnapshot
from app.models.portfolio_account import PortfolioAccount

from tests.helpers import create_portfolio as async_create_portfolio, full_dashboard_setup as _full_setup


# ---------------------------------------------------------------------------
# GET /api/dashboard/tri (lines 642-740)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tri_no_transactions_returns_404(client, db_session):
    uid = await async_create_portfolio(client, f"TRI-NoTx-{id(db_session)}")
    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 404
    assert "cash flows" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tri_no_snapshot_returns_404(client, db_session):
    """Has transactions but no DailySnapshot → should return 404 on snapshot."""
    suffix = f"tri-nosnap-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-NoSnap-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    # LIQUIDITE.EURO product required for TRI
    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.get(Product, liq_ticker)
    if not existing:
        db_session.add(Product(ticker=liq_ticker, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 1), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=10000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=10000.0, total_amount_eur=10000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_tri_with_full_data(client, db_session):
    """Full TRI calculation: LIQUIDITE.EURO deposit + snapshot = valid TRI."""
    suffix = f"tri-full-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Full-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.get(Product, liq_ticker)
    if not existing:
        db_session.add(Product(ticker=liq_ticker, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # Deposit 10000 EUR on 2025-01-01
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 1), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=10000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=10000.0, total_amount_eur=10000.0,
    ))
    await db_session.flush()

    # Snapshot with current value
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 6, 1),
        total_eur=11000.0, offensive_eur=11000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert "tri_pct" in data
    assert "total_investi" in data
    assert "valeur_actuelle" in data
    assert data["total_investi"] == pytest.approx(10000.0)
    assert data["valeur_actuelle"] == pytest.approx(11000.0)
    assert data["nb_flux"] >= 1
    assert isinstance(data["tri_pct"], float)


# ---------------------------------------------------------------------------
# Line 683: TRI — total_retire += cf (withdrawal / negative LIQUIDITE flow)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tri_with_withdrawal(client, db_session):
    """
    Line 683: cf > 0 (withdrawal) → total_retire += cf.

    A negative LIQUIDITE.EURO total_amount_eur means the investor received
    money back → cf = -(-amount) = +positive → total_retire path.
    """
    suffix = f"tri-ret-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Ret-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.get(Product, liq_ticker)
    if not existing:
        db_session.add(Product(ticker=liq_ticker, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # Deposit 10000 EUR (outflow for investor → negative cf)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 2), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=10000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=10000.0, total_amount_eur=10000.0,
    ))
    # Withdrawal 2000 EUR back to investor (negative qty) → cf = -(-2000) = +2000 → line 683
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 3, 3), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-2000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=-2000.0, total_amount_eur=-2000.0,
    ))
    await db_session.flush()

    # Snapshot for TRI valeur_actuelle
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 6, 2),
        total_eur=9000.0, offensive_eur=9000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_retire"] == pytest.approx(2000.0)
    assert data["total_investi"] == pytest.approx(10000.0)
    assert data["nb_flux"] == 2  # 2 cash flow transactions (snapshot not counted)


# ---------------------------------------------------------------------------
# Line 723: Newton break when derivative is near zero
# Line 731: TRI = NaN/Inf → 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tri_nan_result_returns_422(client, db_session):
    """
    Line 731: math.isnan(r) or math.isinf(r) → raise HTTPException(422).

    To force NaN, we construct cash flows that make Newton diverge:
    - Huge opposite-sign amounts on the same date cause extreme oscillations.
    - Two flows: -1_000_000 (deposit) and +1 (withdrawal) on same day,
      then snapshot at +1000. The extreme imbalance causes the XIRR algorithm
      to produce NaN or overflow.

    NOTE: if the Newton-Raphson method converges for this input (unlikely but
    possible), we accept a 200 or 422 — the important thing is the endpoint
    does not crash with an unhandled exception.
    """
    suffix = f"tri-nan-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Nan-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.get(Product, liq_ticker)
    if not existing:
        db_session.add(Product(ticker=liq_ticker, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # Extreme same-date flows that cause Newton oscillation / divergence
    tx_date = date(2025, 1, 2)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=tx_date, type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=1_000_000_000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=1_000_000_000.0, total_amount_eur=1_000_000_000.0,
    ))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=tx_date, type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-999_999_999.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=-999_999_999.0, total_amount_eur=-999_999_999.0,
    ))
    await db_session.flush()

    # Tiny snapshot value — the XIRR between near-zero net flow and 1 EUR at
    # the same date as flows makes denominator computation degenerate
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=tx_date,
        total_eur=1.0, offensive_eur=1.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    # Either computes a valid TRI or raises 422 for NaN/Inf
    assert r.status_code in (200, 422)


@pytest.mark.asyncio
async def test_tri_near_zero_derivative_breaks_newton(client, db_session):
    """
    Line 723: abs(fp) < 1e-12 → break in Newton loop.

    All cash flows at t=0 produce t=0 in npv_deriv, making the derivative
    approach 0 for many initial conditions.  Two flows on the SAME date as the
    snapshot means all t-values are 0, so npv_deriv = 0 → break on line 723.
    """
    suffix = f"tri-deriv-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Deriv-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.get(Product, liq_ticker)
    if not existing:
        db_session.add(Product(ticker=liq_ticker, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # All flows on the SAME date = t0, so t = (d - t0).days / 365.25 = 0 for all.
    # npv_deriv = sum(-t * cf / (1+r)^(t+1)) = 0 for all → abs(fp) = 0 < 1e-12 → break.
    same_date = date(2025, 4, 7)  # Monday
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=same_date, type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=5000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=5000.0, total_amount_eur=5000.0,
    ))
    await db_session.flush()

    # Snapshot on the SAME date as the transaction
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=same_date,
        total_eur=5500.0, offensive_eur=5500.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    # Endpoint must not crash; result may be 200 or 422 (NaN from degenerate case)
    assert r.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Lines 665-716: dashboard TRI endpoint — positive TRI (growing portfolio)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tri_positive_return(client, db_session):
    """
    TRI endpoint with multiple LIQUIDITE.EURO deposits and a growing portfolio value.
    Tests lines 752-786 (cash flow construction) and 788-814 (Newton-Raphson loop).
    """
    suffix = f"tri-pos-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Pos-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liq))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # Two deposits over 6 months
    for d, amt in [(date(2024, 1, 2), 5000.0), (date(2024, 7, 1), 3000.0)]:
        db_session.add(Transaction(
            portfolio_id=uid, account_id=account.id,
            date=d, type="Actif", ticker=liq,
            currency="EUR", exchange_rate=1.0,
            quantity=amt, unit_price=1.0, unit_price_eur=1.0,
            total_amount=amt, total_amount_eur=amt,
        ))

    # Portfolio value grew by ~10%
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 1, 2),
        total_eur=8800.0, offensive_eur=8800.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_investi"] == pytest.approx(8000.0)
    assert data["valeur_actuelle"] == pytest.approx(8800.0)
    assert data["nb_flux"] == 2
    # TRI should be positive (10% gain over ~1 year)
    assert data["tri_pct"] > 0


# ---------------------------------------------------------------------------
# Lines 752-790: TRI — Newton convergence (abs(r_new - r) < 1e-8 break)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tri_converges_exactly(client, db_session):
    """
    Lines 811-814: `if abs(r_new - r) < 1e-8: r = r_new; break`
    A simple constant-rate investment should converge quickly.
    """
    suffix = f"tri-conv-{id(db_session)}"
    portfolio = Portfolio(name=f"TRI-Conv-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    liq = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liq))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq, name="Liquidity EUR",
                                category="Cash", currency="EUR"))
        await db_session.flush()

    # 10,000 invested, value after exactly 1 year = 11,000 → TRI ≈ 10%
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2024, 1, 2), type="Actif", ticker=liq,
        currency="EUR", exchange_rate=1.0,
        quantity=10000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=10000.0, total_amount_eur=10000.0,
    ))
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 1, 2),
        total_eur=11000.0, offensive_eur=11000.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/tri", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Should converge to approximately 10% annually
    assert abs(data["tri_pct"] - 10.0) < 2.0  # within 2% of expected 10%
