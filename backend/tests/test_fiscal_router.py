"""
Integration tests for the fiscal carry-forward router.

Covers CRUD operations and the unique constraint (portfolio + year).
"""
import pytest
from unittest.mock import patch
from tests.helpers import create_portfolio

_MOCK_DELAY = "app.tasks.snapshots.compute_daily_snapshots_all_users.delay"


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

    with patch(_MOCK_DELAY):
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

    await create_product(client, "JPYEUR=X", name="JPY / EUR", category="Cash")

    from datetime import date
    current_year = date.today().year

    # Buy and sell JPYEUR (forex — excluded from fiscal)
    with patch(_MOCK_DELAY):
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
