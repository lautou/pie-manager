# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the equity risk premium service
(app/services/equity_premium_service.py). CRUD mirrors test_macro_indicators_service.py's
MacroRegion tests (including the last-remaining-row delete guard); compute_equity_premiums
covers the point-in-time, no-FX, no-anchor-window math this service owns directly (the
exhaustive as-of tolerance matrix itself lives in test_performance_math.py, whose asof() this
delegates to).
"""
from datetime import timedelta

import pytest

from app.services.equity_premium_service import (
    compute_equity_premiums,
    create_premium_config,
    delete_premium_config,
    list_premium_configs,
    update_premium_config,
)
from tests.helpers import FIXED_TODAY, make_fixed_today_fixture, seed_series_points as _seed

_fixed_today = make_fixed_today_fixture("app.services.equity_premium_service")


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_premium_configs_empty(db_session):
    assert await list_premium_configs(db_session) == []


@pytest.mark.asyncio
async def test_create_premium_config_and_list_sorted_by_code(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500 (SPY)", "Trésor US (IEF)")
    await create_premium_config(db_session, "de", "Allemagne", "EWG", "EXX6.DE", "Actions allemandes (EWG)", "Bund (EXX6.DE)")

    configs = await list_premium_configs(db_session)
    assert [c.code for c in configs] == ["de", "us"]
    assert configs[0].label == "Allemagne"
    assert configs[0].equity_ticker == "EWG"
    assert configs[0].bond_ticker == "EXX6.DE"
    assert configs[0].equity_label == "Actions allemandes (EWG)"
    assert configs[0].bond_label == "Bund (EXX6.DE)"


@pytest.mark.asyncio
async def test_create_premium_config_rejects_invalid_code(db_session):
    with pytest.raises(ValueError, match="Invalid country code"):
        await create_premium_config(db_session, "USA", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")


@pytest.mark.asyncio
async def test_create_premium_config_rejects_duplicate_code(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    with pytest.raises(ValueError, match="already exists"):
        await create_premium_config(db_session, "us", "USA (bis)", "SPY", "IEF", "S&P 500", "Trésor US")


@pytest.mark.asyncio
async def test_update_premium_config_changes_fields_but_not_code(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    updated = await update_premium_config(db_session, "us", "USA", "SPY", "IEF", "S&P 500 Index", "US Treasury 7-10y")
    assert updated is not None
    assert updated.code == "us"
    assert updated.label == "USA"
    assert updated.equity_label == "S&P 500 Index"
    assert updated.bond_label == "US Treasury 7-10y"


@pytest.mark.asyncio
async def test_update_premium_config_unknown_code_returns_none(db_session):
    assert await update_premium_config(db_session, "zz", "Nowhere", "X", "Y", "X Index", "Y Index") is None


@pytest.mark.asyncio
async def test_delete_premium_config_unknown_code_returns_none(db_session):
    assert await delete_premium_config(db_session, "zz") is None


@pytest.mark.asyncio
async def test_delete_premium_config_succeeds_when_others_remain(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await create_premium_config(db_session, "fr", "France", "EWQ", "IFRB.L", "CAC (EWQ)", "OAT (IFRB.L)")

    assert await delete_premium_config(db_session, "fr") is True
    remaining = await list_premium_configs(db_session)
    assert [c.code for c in remaining] == ["us"]


@pytest.mark.asyncio
async def test_delete_premium_config_rejects_last_remaining_country(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    with pytest.raises(ValueError, match="last remaining equity premium country"):
        await delete_premium_config(db_session, "us")
    assert [c.code for c in await list_premium_configs(db_session)] == ["us"]


# ---------------------------------------------------------------------------
# compute_equity_premiums
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_equity_premiums_no_countries_returns_empty(db_session):
    assert await compute_equity_premiums(db_session) == []


@pytest.mark.asyncio
async def test_compute_equity_premiums_both_legs_present(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed(db_session, "premium_us_equity_yield", [(FIXED_TODAY, 0.04)])
    await _seed(db_session, "premium_us_bond_yield", [(FIXED_TODAY, 0.015)])

    results = await compute_equity_premiums(db_session)

    assert len(results) == 1
    r = results[0]
    assert r.code == "us"
    assert r.premium_pct == pytest.approx((0.04 - 0.015) * 100)
    assert r.equity_yield_pct == pytest.approx(4.0)
    assert r.bond_yield_pct == pytest.approx(1.5)
    assert r.equity_label == "S&P 500"
    assert r.bond_label == "Trésor US"
    assert r.asof_date == FIXED_TODAY


@pytest.mark.asyncio
async def test_compute_equity_premiums_excludes_equity_only(db_session):
    """Bond leg missing entirely (a known-gap country, or a failed fetch) — excluded."""
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed(db_session, "premium_us_equity_yield", [(FIXED_TODAY, 0.04)])

    assert await compute_equity_premiums(db_session) == []


@pytest.mark.asyncio
async def test_compute_equity_premiums_excludes_bond_only(db_session):
    """Equity leg missing entirely (e.g. a crumb failure that day) — excluded."""
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed(db_session, "premium_us_bond_yield", [(FIXED_TODAY, 0.015)])

    assert await compute_equity_premiums(db_session) == []


@pytest.mark.asyncio
async def test_compute_equity_premiums_excludes_stale_leg_beyond_tolerance(db_session):
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    stale = FIXED_TODAY - timedelta(days=30)
    await _seed(db_session, "premium_us_equity_yield", [(stale, 0.04)])
    await _seed(db_session, "premium_us_bond_yield", [(FIXED_TODAY, 0.015)])

    assert await compute_equity_premiums(db_session) == []


@pytest.mark.asyncio
async def test_compute_equity_premiums_sorts_ascending_with_mixed_signs(db_session):
    """Ascending sort, no Top-N — and a positive/negative mix, since the sign is the whole
    point of this feature downstream (green/red bar coloring)."""
    # us: premium negative (equity yield below bond yield); fr: premium positive.
    await create_premium_config(db_session, "us", "États-Unis", "SPY", "IEF", "S&P 500", "Trésor US")
    await _seed(db_session, "premium_us_equity_yield", [(FIXED_TODAY, 0.02)])
    await _seed(db_session, "premium_us_bond_yield", [(FIXED_TODAY, 0.04)])

    await create_premium_config(db_session, "fr", "France", "EWQ", "IFRB.L", "CAC (EWQ)", "OAT (IFRB.L)")
    await _seed(db_session, "premium_fr_equity_yield", [(FIXED_TODAY, 0.06)])
    await _seed(db_session, "premium_fr_bond_yield", [(FIXED_TODAY, 0.03)])

    results = await compute_equity_premiums(db_session)

    assert [r.code for r in results] == ["us", "fr"]
    assert results[0].premium_pct < 0
    assert results[1].premium_pct > 0
