# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for GET /api/dashboard/twrr-summary endpoint."""

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.snapshot import DailySnapshot

from tests.helpers import create_portfolio as async_create_portfolio


# ---------------------------------------------------------------------------
# Helper: insert DailySnapshot rows directly into the test session
# ---------------------------------------------------------------------------

async def _add_snapshots(db_session, portfolio_id: int, rows: list[tuple[date, float]]) -> None:
    for snap_date, total_eur in rows:
        db_session.add(DailySnapshot(
            portfolio_id=portfolio_id,
            date=snap_date,
            total_eur=total_eur,
            offensive_eur=total_eur / 2,
            defensive_eur=total_eur / 2,
        ))
    await db_session.flush()


# ---------------------------------------------------------------------------
# 404 cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_summary_no_snapshots_returns_404(client, db_session):
    """Portfolio with no snapshots → 404."""
    uid = await async_create_portfolio(client, f"TWRR-NoSnap-{id(db_session)}")
    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 404
    assert "snapshots" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_twrr_summary_one_snapshot_returns_404(client, db_session):
    """Only one snapshot → cannot compute TWRR (need at least 2)."""
    suffix = f"twrr-one-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-One-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [(date(2025, 1, 1), 10000.0)])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_summary_basic(client, db_session):
    """Two snapshots: portfolio went from 10000 to 11000 (no external flows)."""
    suffix = f"twrr-basic-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Basic-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [
        (date(2024, 1, 2), 10000.0),
        (date(2025, 1, 2), 11000.0),  # +10% over ~1 year
    ])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()

    # Required fields
    assert "twrr_total_pct" in data
    assert "twrr_annualized_pct" in data
    assert "period_days" in data
    assert "start_date" in data
    assert "end_date" in data
    assert "start_index" in data
    assert "end_index" in data

    # start_index is always 100
    assert data["start_index"] == pytest.approx(100.0)

    # With no external flows, TWRR ≈ simple return = (11000/10000 - 1) * 100 = 10%
    assert data["twrr_total_pct"] == pytest.approx(10.0, abs=0.5)

    # end_index ≈ 110
    assert data["end_index"] == pytest.approx(110.0, abs=0.5)

    # Period ≈ 365 days
    assert data["period_days"] == pytest.approx(365, abs=2)

    # Annualised should be close to total over 1 year
    assert abs(data["twrr_annualized_pct"] - data["twrr_total_pct"]) < 1.0

    # Dates match snapshot dates
    assert data["start_date"] == "2024-01-02"
    assert data["end_date"] == "2025-01-02"


@pytest.mark.asyncio
async def test_twrr_summary_multiple_snapshots(client, db_session):
    """More than two snapshots → uses first and last."""
    suffix = f"twrr-multi-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Multi-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [
        (date(2024, 1, 1), 10000.0),
        (date(2024, 6, 1), 10500.0),
        (date(2024, 12, 1), 11000.0),
    ])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["start_date"] == "2024-01-01"
    assert data["end_date"] == "2024-12-01"
    assert data["twrr_total_pct"] > 0


@pytest.mark.asyncio
async def test_twrr_summary_negative_return(client, db_session):
    """Portfolio lost value → TWRR total pct is negative."""
    suffix = f"twrr-neg-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Neg-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [
        (date(2024, 1, 1), 10000.0),
        (date(2025, 1, 1), 8000.0),   # -20%
    ])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["twrr_total_pct"] < 0
    assert data["end_index"] < 100.0


@pytest.mark.asyncio
async def test_twrr_summary_response_types(client, db_session):
    """All returned fields have the correct types."""
    suffix = f"twrr-types-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Types-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [
        (date(2024, 3, 15), 50000.0),
        (date(2024, 9, 15), 55000.0),
    ])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()

    assert isinstance(data["twrr_total_pct"], float)
    assert isinstance(data["twrr_annualized_pct"], float)
    assert isinstance(data["period_days"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["start_index"], float)
    assert isinstance(data["end_index"], float)


@pytest.mark.asyncio
async def test_twrr_summary_exact_one_year_annualized(client, db_session):
    """Over exactly one year with +20% growth, annualized ≈ total."""
    suffix = f"twrr-ann-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Ann-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    await _add_snapshots(db_session, uid, [
        (date(2024, 1, 1), 10000.0),
        (date(2025, 1, 1), 12000.0),  # +20%
    ])

    r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()

    # Total TWRR ≈ 20%
    assert data["twrr_total_pct"] == pytest.approx(20.0, abs=0.5)
    # Annualized over ~1 year ≈ total (with slight difference due to 365 vs 365.25)
    assert abs(data["twrr_annualized_pct"] - data["twrr_total_pct"]) < 1.0
    # Period ≈ 366 days (2024 is a leap year)
    assert 364 <= data["period_days"] <= 366


# ---------------------------------------------------------------------------
# Branch 45->44: dedup keeps the snapshot with the higher id for the same date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_summary_deduplicates_same_date_keeps_latest_id(client, db_session):
    """
    Branch 45->44 in analytics.py: the FALSE branch of
    `if s.date not in seen_dates or s.id > seen_dates[s.date].id`.

    When a date already has a higher-id snapshot in seen_dates, a subsequent snapshot
    with a lower id for the same date is skipped (False branch → 45->44).

    We return [snap_high, snap_low, snap_day2]: snap_high is stored first, then
    snap_low (lower id, same date) is encountered → condition is False → skipped.
    """
    from unittest.mock import patch, MagicMock

    suffix = f"twrr-dedup-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Dedup-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    snap_date1 = date(2025, 3, 3)
    snap_date2 = date(2025, 3, 4)

    # Build mock snapshot objects (same date, different ids and values)
    snap_low = DailySnapshot(portfolio_id=uid, date=snap_date1,
                              total_eur=5_000.0, offensive_eur=2_500.0, defensive_eur=2_500.0)
    snap_low.id = 3001  # lower id → should be skipped (False branch)

    snap_high = DailySnapshot(portfolio_id=uid, date=snap_date1,
                               total_eur=10_000.0, offensive_eur=5_000.0, defensive_eur=5_000.0)
    snap_high.id = 3002  # higher id → stored first

    snap_day2 = DailySnapshot(portfolio_id=uid, date=snap_date2,
                               total_eur=11_000.0, offensive_eur=5_500.0, defensive_eur=5_500.0)
    snap_day2.id = 3003

    original_execute = db_session.execute
    call_count = 0

    async def patched_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            mock_result = MagicMock()
            # snap_high first, then snap_low: snap_low has lower id → False branch → skipped
            mock_result.scalars.return_value.all.return_value = [snap_high, snap_low, snap_day2]
            return mock_result
        return await original_execute(stmt, *args, **kwargs)

    with patch.object(db_session, "execute", side_effect=patched_execute):
        r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})

    assert r.status_code == 200
    data = r.json()
    # With dedup keeping the latest id (10000 on day1), TWRR = (11000/10000 - 1)*100 = 10%
    # Without dedup (using 5000), TWRR would be 120%
    assert data["twrr_total_pct"] == pytest.approx(10.0, abs=1.0), (
        f"Dedup should keep the 10000-value snapshot, got TWRR={data['twrr_total_pct']}"
    )


# ---------------------------------------------------------------------------
# Line 59: twrr_series is empty → 404 (impossible to calculate TWRR)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_summary_empty_twrr_series_returns_404(client, db_session):
    """
    Line 59: if not twrr_series → 404 'Unable to compute TWRR'.

    _compute_twrr is imported inside the analytics endpoint from snapshots.
    We patch app.api.routers.snapshots._compute_twrr to return [] so the
    `if not twrr_series` branch triggers.
    """
    from unittest.mock import patch

    suffix = f"twrr-zero-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Zero-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    # We need at least 2 snapshots so the len(daily_list) < 2 check passes
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 5, 1),
        total_eur=1.0, offensive_eur=0.0, defensive_eur=0.0,
    ))
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 5, 2),
        total_eur=2.0, offensive_eur=0.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    # The function imports _compute_twrr from snapshots at call time
    with patch("app.api.routers.snapshots._compute_twrr", return_value=[]):
        r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})

    assert r.status_code == 404
    assert "TWRR" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Line 77: period_days == 0 → annualized = 0.0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twrr_summary_same_day_snapshots_zero_annualized(client, db_session):
    """
    Line 77: when start_date == end_date (period_days == 0),
    twrr_annualized_pct must be 0.0.

    We mock _compute_twrr to return two entries with the same date so that
    first["date"] == last["date"] → period_days = 0 → else branch at line 77.
    """
    from unittest.mock import patch

    suffix = f"twrr-sameday-{id(db_session)}"
    portfolio = Portfolio(name=f"TWRR-Sameday-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    same_date = date(2025, 6, 2)
    fake_series = [
        {"date": same_date.isoformat(), "index": 100.0},
        {"date": same_date.isoformat(), "index": 105.0},  # same date → period_days=0
    ]

    db_session.add(DailySnapshot(
        portfolio_id=uid, date=same_date,
        total_eur=10_000.0, offensive_eur=0.0, defensive_eur=0.0,
    ))
    db_session.add(DailySnapshot(
        portfolio_id=uid, date=date(2025, 6, 3),  # needed to pass len(daily_list) >= 2
        total_eur=10_500.0, offensive_eur=0.0, defensive_eur=0.0,
    ))
    await db_session.flush()

    with patch("app.api.routers.snapshots._compute_twrr", return_value=fake_series):
        r = await client.get("/api/dashboard/twrr-summary", params={"portfolio_id": uid})

    assert r.status_code == 200
    data = r.json()
    assert data["period_days"] == 0
    # Line 77: period_days == 0 → twrr_annualized_pct = 0.0
    assert data["twrr_annualized_pct"] == pytest.approx(0.0)
