# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Integration tests for the fiscal carry-forward router.

Covers CRUD operations and the unique constraint (portfolio + year).
"""
import pytest
from tests.helpers import create_portfolio, create_product


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_entry(client, portfolio_id: int, tax_year: int, amount_eur: float) -> dict:
    r = await client.post("/api/fiscal/carry-forward/", json={
        "portfolio_id": portfolio_id,
        "tax_year": tax_year,
        "amount_eur": amount_eur,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_create_carry_forward(client):
    """POST creates a new carry-forward entry and returns it."""
    pid = await create_portfolio(client, "Fiscal-Create")
    data = await _create_entry(client, pid, 2022, -5000.0)

    assert data["portfolio_id"] == pid
    assert data["tax_year"] == 2022
    assert data["amount_eur"] == -5000.0
    assert "id" in data


async def test_list_carry_forwards(client):
    """GET returns all entries for a portfolio, ordered by tax_year DESC."""
    pid = await create_portfolio(client, "Fiscal-List")
    await _create_entry(client, pid, 2020, -1000.0)
    await _create_entry(client, pid, 2022, -3000.0)
    await _create_entry(client, pid, 2021, -2000.0)

    r = await client.get("/api/fiscal/carry-forward/", params={"portfolio_id": pid})
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 3
    # Ordered by tax_year DESC
    assert items[0]["tax_year"] == 2022
    assert items[1]["tax_year"] == 2021
    assert items[2]["tax_year"] == 2020


async def test_update_carry_forward(client):
    """PUT updates the amount_eur of an existing entry."""
    pid = await create_portfolio(client, "Fiscal-Update")
    entry = await _create_entry(client, pid, 2023, -8000.0)
    entry_id = entry["id"]

    r = await client.put(f"/api/fiscal/carry-forward/{entry_id}", json={"amount_eur": -9500.0})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["id"] == entry_id
    assert updated["amount_eur"] == -9500.0
    assert updated["tax_year"] == 2023


async def test_delete_carry_forward(client):
    """DELETE removes the entry and subsequent GET returns empty list."""
    pid = await create_portfolio(client, "Fiscal-Delete")
    entry = await _create_entry(client, pid, 2019, -4500.0)
    entry_id = entry["id"]

    r = await client.delete(f"/api/fiscal/carry-forward/{entry_id}")
    assert r.status_code == 204, r.text

    r = await client.get("/api/fiscal/carry-forward/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json() == []


async def test_unique_constraint_same_year(client):
    """POST with the same portfolio_id + tax_year twice returns 400."""
    pid = await create_portfolio(client, "Fiscal-Unique")
    await _create_entry(client, pid, 2021, -2000.0)

    r = await client.post("/api/fiscal/carry-forward/", json={
        "portfolio_id": pid,
        "tax_year": 2021,
        "amount_eur": -3000.0,
    })
    assert r.status_code == 400, r.text
    assert "2021" in r.json()["detail"]


async def test_update_nonexistent_returns_404(client):
    """PUT on a non-existent id returns 404."""
    r = await client.put("/api/fiscal/carry-forward/999999", json={"amount_eur": -100.0})
    assert r.status_code == 404


async def test_delete_nonexistent_returns_404(client):
    """DELETE on a non-existent id returns 404."""
    r = await client.delete("/api/fiscal/carry-forward/999999")
    assert r.status_code == 404


async def test_list_empty_for_new_portfolio(client):
    """GET for a portfolio with no entries returns empty list."""
    pid = await create_portfolio(client, "Fiscal-Empty")
    r = await client.get("/api/fiscal/carry-forward/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json() == []


async def test_entries_isolated_per_portfolio(client):
    """Entries from portfolio A are not visible when querying portfolio B."""
    pid_a = await create_portfolio(client, "Fiscal-IsoA")
    pid_b = await create_portfolio(client, "Fiscal-IsoB")

    await _create_entry(client, pid_a, 2020, -5000.0)
    await _create_entry(client, pid_a, 2021, -3000.0)

    r = await client.get("/api/fiscal/carry-forward/", params={"portfolio_id": pid_b})
    assert r.status_code == 200
    assert r.json() == []


async def test_same_year_different_portfolios_allowed(client):
    """Two portfolios can both have an entry for the same tax_year (no conflict)."""
    pid_a = await create_portfolio(client, "Fiscal-SameYearA")
    pid_b = await create_portfolio(client, "Fiscal-SameYearB")

    await _create_entry(client, pid_a, 2022, -1000.0)
    data_b = await _create_entry(client, pid_b, 2022, -2000.0)

    assert data_b["portfolio_id"] == pid_b
    assert data_b["tax_year"] == 2022


# ── current-year PV endpoint ──────────────────────────────────────────────────

async def test_current_year_pv_no_cto_accounts(client):
    """Portfolio with no CTO accounts returns net_realized_pv=0."""
    pid = await create_portfolio(client, "Fiscal-PV-NoCTO")
    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["net_realized_pv"] == 0.0
    assert body["details"] == []
    assert body["loss_harvesting_candidates"] == []


async def test_current_year_pv_default_year(client):
    """Endpoint returns current year when no year param is supplied."""
    from datetime import date
    pid = await create_portfolio(client, "Fiscal-PV-YearDefault")
    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["year"] == date.today().year


async def test_current_year_pv_explicit_year(client):
    """Explicit year param is reflected in the response."""
    pid = await create_portfolio(client, "Fiscal-PV-Year2024")
    r = await client.get("/api/fiscal/current-year-pv/",
                         params={"portfolio_id": pid, "year": 2024})
    assert r.status_code == 200
    assert r.json()["year"] == 2024


async def test_current_year_pv_with_cto_account_and_transactions(client, db_session):
    """Full path: CTO account + sell transaction → realized PV returned."""
    from sqlalchemy import text
    from tests.helpers import create_broker, create_product

    pid = await create_portfolio(client, "Fiscal-PV-Full")

    # Create account then explicitly set is_cto=True (migration only sets existing accounts)
    acc = await create_broker(client, pid, name="Degiro")
    acc_id = acc["id"]
    await db_session.execute(
        text("UPDATE brokers SET is_cto = TRUE WHERE id = :id"), {"id": acc_id}
    )

    # Create a product
    await create_product(client, "TST.DE", name="Test ETF", category="Actif")

    from datetime import date
    current_year = date.today().year

    # Create a buy transaction (negative quantity = buy)
    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid,
        "account_id": acc_id,
        "date": "2024-01-15",
        "type": "Actif",
        "ticker": "TST.DE",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -10,
        "unit_price": 100.0,
        "unit_price_eur": 100.0,
        "total_amount": -1000.0,
        "total_amount_eur": -1000.0,
    })
    assert r.status_code == 201, r.text

    # Create a sell transaction (positive quantity = sell) in current year
    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid,
        "account_id": acc_id,
        "date": f"{current_year}-03-01",
        "type": "Actif",
        "ticker": "TST.DE",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": 5,
        "unit_price": 120.0,
        "unit_price_eur": 120.0,
        "total_amount": 600.0,
        "total_amount_eur": 600.0,
    })
    assert r.status_code == 201, r.text

    # Check current-year PV
    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == current_year
    # TST.DE: buy 10@100, sell 5@120 → CUMP=100, realized PV = 5*(120-100) = 100
    assert body["net_realized_pv"] == pytest.approx(100.0, abs=1.0)
    assert len(body["details"]) >= 1

    # Calling with a different year (e.g. 2030) covers the FALSE branch of the
    # year filter (ev_year != year_str → 174->172) — no sell events for 2030
    r2 = await client.get("/api/fiscal/current-year-pv/",
                          params={"portfolio_id": pid, "year": 2030})
    assert r2.status_code == 200
    assert r2.json()["net_realized_pv"] == 0.0
    assert r2.json()["details"] == []


async def test_current_year_pv_excludes_jpyeur(client, db_session):
    """JPYEUR=X events are excluded from fiscal PV computation."""
    from sqlalchemy import text
    from tests.helpers import create_broker, create_product

    pid = await create_portfolio(client, "Fiscal-PV-Yen")
    acc = await create_broker(client, pid, name="Degiro")
    acc_id = acc["id"]
    await db_session.execute(
        text("UPDATE brokers SET is_cto = TRUE WHERE id = :id"), {"id": acc_id}
    )

    await create_product(client, "JPYEUR=X", name="JPY / EUR", category="Actif", instrument_type="Cash")

    from datetime import date
    current_year = date.today().year

    # Buy and sell JPYEUR (forex — excluded from fiscal)
    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid, "account_id": acc_id,
        "date": "2024-01-01", "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 100000, "unit_price": 0.006, "unit_price_eur": 0.006,
        "total_amount": 600.0, "total_amount_eur": 600.0,
    })
    assert r.status_code == 201

    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid, "account_id": acc_id,
        "date": f"{current_year}-04-01", "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -50000, "unit_price": 0.0055, "unit_price_eur": 0.0055,
        "total_amount": -275.0, "total_amount_eur": -275.0,
    })
    assert r.status_code == 201

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    # JPYEUR excluded → no details
    assert r.json()["details"] == []
    assert r.json()["net_realized_pv"] == 0.0


# ── loss-harvesting candidates ───────────────────────────────────────────────

async def _make_cto_account(client, db_session, portfolio_id: int, name: str) -> int:
    from sqlalchemy import text
    from tests.helpers import create_broker

    acc = await create_broker(client, portfolio_id, name=name)
    acc_id = acc["id"]
    await db_session.execute(
        text("UPDATE brokers SET is_cto = TRUE WHERE id = :id"), {"id": acc_id}
    )
    return acc_id


async def _buy(client, portfolio_id: int, account_id: int, ticker: str,
                qty: float, unit_price: float) -> None:
    r = await client.post("/api/transactions/", json={
        "portfolio_id": portfolio_id, "account_id": account_id,
        "date": "2024-01-15", "type": "Actif", "ticker": ticker,
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -abs(qty), "unit_price": unit_price, "unit_price_eur": unit_price,
        "total_amount": -abs(qty) * unit_price, "total_amount_eur": -abs(qty) * unit_price,
    })
    assert r.status_code == 201, r.text


async def _seed_price(db_session, ticker: str, price: float, currency: str = "EUR") -> None:
    from datetime import date as date_cls
    from app.models.price import AssetPrice

    db_session.add(AssetPrice(
        ticker=ticker, date=date_cls(2024, 6, 1), price=price, currency=currency, source="manual",
    ))
    await db_session.flush()


async def test_loss_harvesting_candidate_appears_for_unrealized_loss(client, db_session):
    """A currently-held CTO position priced below its CUMP appears as a candidate."""
    pid = await create_portfolio(client, "Fiscal-Loss-Basic")
    acc_id = await _make_cto_account(client, db_session, pid, "Degiro")
    await create_product(client, "LOSS.DE", name="Losing ETF", category="Actif")

    await _buy(client, pid, acc_id, "LOSS.DE", qty=10, unit_price=100.0)
    await _seed_price(db_session, "LOSS.DE", price=80.0)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    candidates = r.json()["loss_harvesting_candidates"]
    assert len(candidates) == 1
    c = candidates[0]
    assert c["ticker"] == "LOSS.DE"
    assert c["qty_held"] == pytest.approx(10.0, abs=1e-6)
    assert c["cump"] == pytest.approx(100.0, rel=1e-4)
    assert c["current_value_eur"] == pytest.approx(800.0, abs=0.01)
    assert c["unrealized_pv"] == pytest.approx(-200.0, abs=0.01)


async def test_loss_harvesting_excludes_unrealized_gain(client, db_session):
    """A currently-held CTO position priced above its CUMP is not a candidate."""
    pid = await create_portfolio(client, "Fiscal-Loss-Gain")
    acc_id = await _make_cto_account(client, db_session, pid, "Degiro")
    await create_product(client, "GAIN.DE", name="Winning ETF", category="Actif")

    await _buy(client, pid, acc_id, "GAIN.DE", qty=10, unit_price=100.0)
    await _seed_price(db_session, "GAIN.DE", price=120.0)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []


async def test_loss_harvesting_excludes_non_cto_account(client, db_session):
    """A losing position held in a non-CTO account is never a candidate."""
    from tests.helpers import create_broker

    pid = await create_portfolio(client, "Fiscal-Loss-NonCTO")
    # CTO account exists (required for the endpoint to compute anything at all)
    await _make_cto_account(client, db_session, pid, "Degiro-CTO")
    non_cto_acc = await create_broker(client, pid, name="PEA-NonCTO")
    await create_product(client, "PEALOSS.PA", name="PEA Losing ETF", category="Actif")

    await _buy(client, pid, non_cto_acc["id"], "PEALOSS.PA", qty=10, unit_price=100.0)
    await _seed_price(db_session, "PEALOSS.PA", price=50.0)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []


async def test_loss_harvesting_excludes_forex_ticker(client, db_session):
    """A losing JPYEUR=X forex position is excluded (biens meubles regime)."""
    pid = await create_portfolio(client, "Fiscal-Loss-Forex")
    acc_id = await _make_cto_account(client, db_session, pid, "Degiro")
    await create_product(client, "JPYEUR=X", name="JPY / EUR", category="Actif", instrument_type="Cash")

    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid, "account_id": acc_id,
        "date": "2024-01-01", "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 100000, "unit_price": 0.006, "unit_price_eur": 0.006,
        "total_amount": 600.0, "total_amount_eur": 600.0,
    })
    assert r.status_code == 201
    await _seed_price(db_session, "JPYEUR=X", price=0.004)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []


async def test_loss_harvesting_excludes_fully_sold_position(client, db_session):
    """A fully-closed position (qty_held == 0) is never a candidate."""
    pid = await create_portfolio(client, "Fiscal-Loss-Closed")
    acc_id = await _make_cto_account(client, db_session, pid, "Degiro")
    await create_product(client, "CLOSED.DE", name="Closed ETF", category="Actif")

    await _buy(client, pid, acc_id, "CLOSED.DE", qty=10, unit_price=100.0)
    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid, "account_id": acc_id,
        "date": "2024-06-01", "type": "Actif", "ticker": "CLOSED.DE",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 10, "unit_price": 50.0, "unit_price_eur": 50.0,
        "total_amount": 500.0, "total_amount_eur": 500.0,
    })
    assert r.status_code == 201, r.text
    await _seed_price(db_session, "CLOSED.DE", price=50.0)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []


async def test_loss_harvesting_no_transactions_returns_empty(client, db_session):
    """CTO account exists but has no transactions at all → empty candidates list."""
    pid = await create_portfolio(client, "Fiscal-Loss-Empty")
    await _make_cto_account(client, db_session, pid, "Degiro")

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []


async def test_loss_harvesting_skips_ticker_with_no_price(client, db_session):
    """A held CTO position with no AssetPrice row at all is silently skipped, not crashed on."""
    pid = await create_portfolio(client, "Fiscal-Loss-NoPrice")
    acc_id = await _make_cto_account(client, db_session, pid, "Degiro")
    await create_product(client, "NOPRICE.DE", name="No Price ETF", category="Actif")

    await _buy(client, pid, acc_id, "NOPRICE.DE", qty=10, unit_price=100.0)

    r = await client.get("/api/fiscal/current-year-pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    assert r.json()["loss_harvesting_candidates"] == []
