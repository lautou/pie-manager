# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for portfolio CRUD endpoints.

Covers:
  - Create / List / Get / Rename / Delete
  - Duplicate-name rejection (409)
  - 404 on unknown ID
"""
import pytest


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_portfolio(client):
    r = await client.post("/api/portfolios/", json={"name": "Test Portfolio"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test Portfolio"
    assert "id" in data
    assert "created_at" in data
    # issue #72: must carry an explicit UTC offset, not a naive/ambiguous string —
    # otherwise the frontend parses it as local time instead of UTC.
    assert data["created_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_create_portfolio_strips_whitespace(client):
    """Leading/trailing spaces in the name must be stripped."""
    r = await client.post("/api/portfolios/", json={"name": "  Padded  "})
    assert r.status_code == 201
    assert r.json()["name"] == "Padded"


@pytest.mark.asyncio
async def test_duplicate_name_rejected(client):
    """Creating two portfolios with the same name must return 409."""
    await client.post("/api/portfolios/", json={"name": "UniquePortfolio"})
    r = await client.post("/api/portfolios/", json={"name": "UniquePortfolio"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_portfolios(client):
    await client.post("/api/portfolios/", json={"name": "Portfolio A"})
    await client.post("/api/portfolios/", json={"name": "Portfolio B"})
    r = await client.get("/api/portfolios/")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Portfolio A" in names
    assert "Portfolio B" in names


@pytest.mark.asyncio
async def test_list_portfolios_empty(client):
    """An empty portfolio table must return an empty list, not an error."""
    r = await client.get("/api/portfolios/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_portfolio(client):
    created = (await client.post("/api/portfolios/", json={"name": "SingleGet"})).json()
    r = await client.get(f"/api/portfolios/{created['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "SingleGet"


@pytest.mark.asyncio
async def test_get_portfolio_not_found(client):
    r = await client.get("/api/portfolios/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Rename (PUT)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rename_portfolio(client):
    pid = (await client.post("/api/portfolios/", json={"name": "Old Name"})).json()["id"]
    r = await client.put(f"/api/portfolios/{pid}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_rename_portfolio_same_name_ok(client):
    """Renaming a portfolio to its own current name must succeed (no 409)."""
    pid = (await client.post("/api/portfolios/", json={"name": "SameName"})).json()["id"]
    r = await client.put(f"/api/portfolios/{pid}", json={"name": "SameName"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rename_portfolio_conflict(client):
    """Renaming to an already-taken name must return 409."""
    await client.post("/api/portfolios/", json={"name": "TakenName"})
    pid = (await client.post("/api/portfolios/", json={"name": "OriginalName"})).json()["id"]
    r = await client.put(f"/api/portfolios/{pid}", json={"name": "TakenName"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_rename_portfolio_not_found(client):
    r = await client.put("/api/portfolios/999999", json={"name": "Ghost"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_portfolio(client):
    pid = (await client.post("/api/portfolios/", json={"name": "To Delete"})).json()["id"]
    r = await client.delete(f"/api/portfolios/{pid}")
    assert r.status_code == 204
    # Confirm it's gone
    assert (await client.get(f"/api/portfolios/{pid}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_portfolio_not_found(client):
    r = await client.delete("/api/portfolios/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Additional coverage: DELETE with cascading data (lines 82-95)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_portfolio_cascades_all_relations(client, db_session):
    """
    DELETE /{portfolio_id} runs cascade-delete text() statements for:
      daily_snapshots, monthly_snapshots, transactions, pool_products, pools, accounts.
    Lines 82-95.
    """
    from datetime import date as date_cls
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.pool import Pool, PoolProduct
    from app.models.transaction import Transaction
    from app.models.snapshot import DailySnapshot, MonthlySnapshot
    from app.models.portfolio_account import PortfolioAccount

    suffix = f"cascade-{id(db_session)}"
    portfolio = Portfolio(name=f"CascadeDel-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    acc = Broker(name="Acc", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    liq = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liq))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq, name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    pool = Pool(portfolio_id=uid, name="Pool", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=liq))

    db_session.add(Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date_cls(2025, 1, 2), type="Actif", ticker=liq,
        currency="EUR", exchange_rate=1.0,
        quantity=1000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=1000.0, total_amount_eur=1000.0,
    ))
    db_session.add(DailySnapshot(portfolio_id=uid, date=date_cls(2025, 1, 2),
                                  total_eur=1000.0, offensive_eur=0.0, defensive_eur=0.0))
    db_session.add(MonthlySnapshot(
        portfolio_id=uid, date=date_cls(2025, 1, 31),
        total_eur=1000.0, offensive_eur=1000.0, defensive_eur=0.0,
        contributions_eur=1000.0, performance_pct=0.0, performance_index=100.0,
    ))
    await db_session.flush()

    # Commit so the delete endpoint can see the rows (rollback will undo at end)
    await db_session.commit()

    r = await client.delete(f"/api/portfolios/{uid}")

    assert r.status_code == 204
    # Portfolio is gone
    r2 = await client.get(f"/api/portfolios/{uid}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_rename_portfolio_strips_whitespace(client):
    """PUT name with spaces → stripped (line 69)."""
    pid = (await client.post("/api/portfolios/", json={"name": "OldWithSpaces"})).json()["id"]
    r = await client.put(f"/api/portfolios/{pid}", json={"name": "  NewName  "})
    assert r.status_code == 200
    assert r.json()["name"] == "NewName"
