"""
Tests for POST /api/transactions/import/commit — atomic, all-or-nothing insertion,
force-including flagged duplicates, fee auto-linking (proving reuse of
create_transaction_core rather than a parallel reimplementation), unsorted-file handling,
and the single snapshot-recompute trigger per commit.
"""
import io
import json
from datetime import date
from unittest.mock import patch

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import Broker, Portfolio, PortfolioAccount, Product, Transaction
from app.services.import_service import TRANSACTION_COLUMNS


def _make_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(TRANSACTION_COLUMNS)
    for row in rows:
        ws.append([row.get(col) for col in TRANSACTION_COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(content: bytes, include_rows: list[int]):
    return (
        {"file": ("import.xlsx", io.BytesIO(content),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        {"include_rows": json.dumps(include_rows)},
    )


async def _seed_basic(db_session, suffix):
    portfolio = Portfolio(name=f"CommitPortfolio-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    broker = Broker(name=f"CommitBroker-{suffix}", currency="EUR")
    db_session.add(broker)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=broker.id, cash_balance_eur=1000.0))
    product = Product(ticker=f"ETF.{suffix}", name="ETF Monde", category="Actif", instrument_type="ETF", currency="EUR")
    db_session.add(product)
    await db_session.flush()
    return portfolio, broker, product


def _row(portfolio, broker, product, **overrides):
    base = {
        "Portefeuille": portfolio.name, "Compte": broker.name, "Sens": "Achat",
        "Ticker": product.ticker, "Date": date(2026, 1, 5), "Quantité": 10,
        "Prix unitaire": 45.2, "Devise": "EUR", "Taux de change": 1.0,
        "Courtage (EUR)": 0, "TTF (EUR)": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_commit_creates_transaction_and_triggers_snapshot_once(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [2])

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay") as mock_delay:
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported_count"] == 1
    mock_delay.assert_called_once()

    tx = (await db_session.execute(
        select(Transaction).where(Transaction.id == body["created_transaction_ids"][0])
    )).scalar_one()
    assert tx.quantity == -10.0
    assert tx.operation == "Achat"


@pytest.mark.asyncio
async def test_commit_multiple_rows_triggers_snapshot_exactly_once_with_min_date(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([
        _row(portfolio, broker, product, Date=date(2026, 3, 1)),
        _row(portfolio, broker, product, Date=date(2026, 1, 5)),
    ])
    files, data = _upload(content, [2, 3])

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay") as mock_delay:
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200, r.text
    assert r.json()["imported_count"] == 2
    mock_delay.assert_called_once_with("2026-01-05")


@pytest.mark.asyncio
async def test_commit_default_excludes_duplicate_unless_forced(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    existing = Transaction(
        portfolio_id=portfolio.id, account_id=broker.id, date=date(2026, 1, 5),
        type="Actif", operation="Achat", ticker=product.ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0, unit_price=45.2,
        unit_price_eur=45.2, total_amount=-452.0, total_amount_eur=-452.0,
    )
    db_session.add(existing)
    await db_session.flush()

    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [])  # nothing included -> duplicate stays excluded

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay"):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200
    assert r.json()["imported_count"] == 0


@pytest.mark.asyncio
async def test_commit_forces_include_of_flagged_duplicate(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    existing = Transaction(
        portfolio_id=portfolio.id, account_id=broker.id, date=date(2026, 1, 5),
        type="Actif", operation="Achat", ticker=product.ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0, unit_price=45.2,
        unit_price_eur=45.2, total_amount=-452.0, total_amount_eur=-452.0,
    )
    db_session.add(existing)
    await db_session.flush()

    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [2])  # explicitly force the duplicate row

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay"):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200, r.text
    assert r.json()["imported_count"] == 1

    count = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id, Transaction.ticker == product.ticker)
    )).scalars().all()
    assert len(count) == 2  # the pre-existing one + the forced import


@pytest.mark.asyncio
async def test_commit_rejects_when_included_row_has_error(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([_row(portfolio, broker, product, Portefeuille="Ghost")])
    files, data = _upload(content, [2])

    r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 422
    assert "Ligne 2" in r.json()["detail"]

    count = (await db_session.execute(select(Transaction))).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_commit_rejects_unknown_row_number(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [99])

    r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_commit_rejects_malformed_include_rows(client, db_session):
    content = _make_xlsx([])
    files = {"file": ("import.xlsx", io.BytesIO(content),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/api/transactions/import/commit", files=files, data={"include_rows": "not-json"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_commit_rejects_missing_transactions_sheet(client, db_session):
    wb = Workbook()
    wb.active.title = "Autre"
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("import.xlsx", io.BytesIO(buf.getvalue()),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/api/transactions/import/commit", files=files, data={"include_rows": "[2]"})
    assert r.status_code == 400
    assert "Transactions" in r.json()["detail"]


@pytest.mark.asyncio
async def test_commit_corrupt_non_xlsx_file_returns_400_not_500(client, db_session):
    files = {"file": ("import.xlsx", io.BytesIO(b"not an excel file at all"),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/api/transactions/import/commit", files=files, data={"include_rows": "[2]"})
    assert r.status_code == 400
    assert "illisible" in r.json()["detail"]


@pytest.mark.asyncio
async def test_commit_rolls_back_on_http_exception_from_create_transaction_core(client, db_session):
    """create_transaction_core can itself raise HTTPException (its own broker/portfolio_account
    check) even after our own pre-validation passed — an inherent, if rare, race between
    /validate-time and /commit-time DB state. Must roll back exactly like the generic
    exception path, not leak a stray HTTPException with uncommitted partial state."""
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [2])

    from fastapi import HTTPException as FastAPIHTTPException

    async def failing_create(body, db):
        raise FastAPIHTTPException(status_code=400, detail="simulated broker check failure")

    with patch("app.api.routers.transaction_import.create_transaction_core", side_effect=failing_create):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 400
    assert "simulated broker check failure" in r.json()["detail"]

    count = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id)
    )).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_commit_rejects_upfront_when_revalidation_finds_new_error(client, db_session):
    """Simulate DB state changing between /validate and /commit: the broker is deleted after
    the file is prepared. Row 2 (valid broker) should commit fine on its own, but when combined
    with a row referencing the now-deleted broker in the same batch, nothing must be inserted."""
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    other_broker = Broker(name=f"GhostBroker-{suffix}", currency="EUR")
    db_session.add(other_broker)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=other_broker.id))
    await db_session.flush()

    content = _make_xlsx([
        _row(portfolio, broker, product),
        _row(portfolio, other_broker, product, Date=date(2026, 1, 6)),
    ])

    # Delete the second row's broker's PortfolioAccount link after the file was built,
    # simulating a race between validate and commit.
    await db_session.delete((await db_session.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.portfolio_id == portfolio.id, PortfolioAccount.broker_id == other_broker.id
        )
    )).scalar_one())
    await db_session.flush()

    files, data = _upload(content, [2, 3])
    r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 422

    count = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id)
    )).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_commit_rolls_back_on_mid_loop_failure(client, db_session):
    """Both rows pass re-validation (unlike the upfront-rejection test above), but the second
    call to create_transaction_core raises mid-loop — the whole batch, including the first
    row that would have succeeded on its own, must be rolled back rather than partially
    imported. Exercises the try/except rollback branch directly, which the upfront-rejection
    test above can never reach (it always fails before entering the loop)."""
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([
        _row(portfolio, broker, product, Date=date(2026, 1, 5)),
        _row(portfolio, broker, product, Date=date(2026, 1, 6)),
    ])
    files, data = _upload(content, [2, 3])

    real_create = None
    call_count = 0

    async def flaky_create(body, db):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated failure on second row")
        return await real_create(body, db)

    from app.api.routers import transactions as transactions_router
    real_create = transactions_router.create_transaction_core

    with patch("app.api.routers.transaction_import.create_transaction_core", side_effect=flaky_create):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 500
    assert "simulated failure" in r.json()["detail"]

    count = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id)
    )).scalars().all()
    assert count == [], "the first row must have been rolled back along with the second"


@pytest.mark.asyncio
async def test_commit_reorders_unsorted_rows_chronologically(client, db_session):
    """The file lists a later-dated row first; the commit must still produce a correct
    running-balance chain as if rows were inserted in chronological order. Seeds an initial
    transaction with a known balance_eur first — a brand new account's first-ever transaction
    never gets an auto-computed balance_eur (no prior row to chain from), so the reorder
    itself can only be observed once there's a seeded baseline to chain onto."""
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    seed_tx = Transaction(
        portfolio_id=portfolio.id, account_id=broker.id, date=date(2025, 12, 1),
        type="Actif", operation=None, ticker=product.ticker, currency="EUR",
        exchange_rate=1.0, quantity=1000.0, unit_price=1.0,
        unit_price_eur=1.0, total_amount=1000.0, total_amount_eur=1000.0,
        balance_eur=1000.0, balance_currency=1000.0,
    )
    db_session.add(seed_tx)
    await db_session.flush()

    content = _make_xlsx([
        _row(portfolio, broker, product, Sens="Vente", Date=date(2026, 3, 1), Quantité=5, **{"Prix unitaire": 50.0}),
        _row(portfolio, broker, product, Sens="Achat", Date=date(2026, 1, 5), Quantité=10, **{"Prix unitaire": 45.2}),
    ])
    files, data = _upload(content, [2, 3])

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay"):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200, r.text

    txs = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id, Transaction.id != seed_tx.id)
        .order_by(Transaction.date)
    )).scalars().all()
    assert len(txs) == 2
    assert txs[0].date == date(2026, 1, 5)
    assert txs[0].balance_eur == pytest.approx(1000.0 - 452.0, abs=0.01)
    assert txs[1].date == date(2026, 3, 1)
    assert txs[1].balance_eur == pytest.approx(1000.0 - 452.0 + 250.0, abs=0.01)


@pytest.mark.asyncio
async def test_commit_achat_with_courtage_and_ttf_creates_linked_frais(client, db_session):
    """Proves the import path reuses create_transaction_core's existing fee-auto-linking
    logic rather than a parallel reimplementation."""
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", fee_type="Courtage", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.TTF.EUR", name="TTF", category="Frais", fee_type="TTF", currency="EUR"))
    await db_session.flush()
    content = _make_xlsx([_row(portfolio, broker, product, **{"Courtage (EUR)": 2.5, "TTF (EUR)": 1.8})])
    files, data = _upload(content, [2])

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay"):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200, r.text
    parent_id = r.json()["created_transaction_ids"][0]

    linked = (await db_session.execute(
        select(Transaction).where(Transaction.linked_transaction_id == parent_id)
    )).scalars().all()
    tickers = {tx.ticker for tx in linked}
    assert tickers == {"FRAIS.COURTAGE.EUR", "FRAIS.TTF.EUR"}


@pytest.mark.asyncio
async def test_commit_updates_cash_balance(client, db_session):
    suffix = id(db_session)
    portfolio, broker, product = await _seed_basic(db_session, suffix)
    content = _make_xlsx([_row(portfolio, broker, product)])
    files, data = _upload(content, [2])

    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay"):
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200

    pa = (await db_session.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.portfolio_id == portfolio.id, PortfolioAccount.broker_id == broker.id
        )
    )).scalar_one()
    assert pa.cash_balance_eur == pytest.approx(1000.0 - 452.0, abs=0.01)


@pytest.mark.asyncio
async def test_commit_zero_rows_does_not_trigger_snapshot(client, db_session):
    content = _make_xlsx([])
    files, data = _upload(content, [])
    with patch("app.tasks.snapshots.compute_daily_snapshots_all_users.delay") as mock_delay:
        r = await client.post("/api/transactions/import/commit", files=files, data=data)
    assert r.status_code == 200
    assert r.json()["imported_count"] == 0
    mock_delay.assert_not_called()
