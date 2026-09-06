# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the sovereign bond performance service
(app/services/bond_performance_service.py). Mirrors test_sector_performance_service.py — the
exhaustive as-of/FX-edge-case matrix lives in test_performance_math.py (the shared math this
service delegates to); these tests cover CRUD and the orchestration this module owns itself
(FX caching/dedup, no Top-N truncation).
"""
from unittest.mock import patch

import pytest

from app.services.bond_performance_service import (
    compute_bond_performance,
    create_bond_config,
    delete_bond_config,
    list_bond_configs,
    update_bond_config,
)
from app.services.macro_series_price_service import get_series as real_get_series
from tests.helpers import FIXED_TODAY, ANCHOR_TARGET, make_fixed_today_fixture, seed_series_points as _seed

_fixed_today = make_fixed_today_fixture("app.services.bond_performance_service")


# ---------------------------------------------------------------------------
# Bond-market CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_bond_configs_empty(db_session):
    assert await list_bond_configs(db_session) == []


@pytest.mark.asyncio
async def test_create_bond_config_and_list_sorted_by_code(db_session):
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain 7-10 ans (IEF)")
    await create_bond_config(db_session, "fr", "France", "IFRB.AS", "EUR", "Obligations françaises")

    countries = await list_bond_configs(db_session)
    assert [c.code for c in countries] == ["fr", "us"]
    assert countries[0].label == "France"
    assert countries[0].index_ticker == "IFRB.AS"
    assert countries[0].currency == "EUR"
    assert countries[0].index_label == "Obligations françaises"


@pytest.mark.asyncio
async def test_create_bond_config_rejects_invalid_code(db_session):
    with pytest.raises(ValueError, match="Invalid country code"):
        await create_bond_config(db_session, "US", "États-Unis", "IEF", "USD", "Trésor américain")


@pytest.mark.asyncio
async def test_create_bond_config_rejects_invalid_currency(db_session):
    with pytest.raises(ValueError, match="Invalid currency"):
        await create_bond_config(db_session, "us", "États-Unis", "IEF", "usd", "Trésor américain")


@pytest.mark.asyncio
async def test_create_bond_config_rejects_duplicate_code(db_session):
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    with pytest.raises(ValueError, match="already exists"):
        await create_bond_config(db_session, "us", "USA (bis)", "IEF", "USD", "Trésor américain")


@pytest.mark.asyncio
async def test_update_bond_config_changes_fields_but_not_code(db_session):
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    updated = await update_bond_config(db_session, "us", "USA", "IEF", "USD", "US Treasury 7-10y")
    assert updated is not None
    assert updated.code == "us"
    assert updated.label == "USA"
    assert updated.index_label == "US Treasury 7-10y"


@pytest.mark.asyncio
async def test_update_bond_config_rejects_invalid_currency(db_session):
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    with pytest.raises(ValueError, match="Invalid currency"):
        await update_bond_config(db_session, "us", "États-Unis", "IEF", "usd", "Trésor américain")


@pytest.mark.asyncio
async def test_update_bond_config_unknown_code_returns_none(db_session):
    assert await update_bond_config(db_session, "zz", "Nowhere", "X", "USD", "Bond") is None


@pytest.mark.asyncio
async def test_delete_bond_config_unknown_code_returns_none(db_session):
    assert await delete_bond_config(db_session, "zz") is None


@pytest.mark.asyncio
async def test_delete_bond_config_succeeds_even_as_last_row(db_session):
    """No 'last remaining row' guard — the universe can be emptied out entirely, yielding an
    empty chart."""
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    assert await delete_bond_config(db_session, "us") is True
    assert await list_bond_configs(db_session) == []


# ---------------------------------------------------------------------------
# compute_bond_performance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_bond_performance_no_countries_returns_empty(db_session):
    assert await compute_bond_performance(db_session) == []


@pytest.mark.asyncio
async def test_compute_bond_performance_eur_country_skips_fx(db_session):
    await create_bond_config(db_session, "fr", "France", "IFRB.AS", "EUR", "Obligations françaises")
    await _seed(db_session, "bond_fr_govt", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 105.0)])

    results = await compute_bond_performance(db_session)

    assert len(results) == 1
    assert results[0].code == "fr"
    assert results[0].perf_pct == pytest.approx(5.0)
    assert results[0].index_label == "Obligations françaises"


@pytest.mark.asyncio
async def test_compute_bond_performance_non_eur_country_applies_fx(db_session):
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    await _seed(db_session, "bond_us_govt", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 95.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    results = await compute_bond_performance(db_session)

    assert len(results) == 1
    expected = ((95.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert results[0].perf_pct == pytest.approx(expected)


@pytest.mark.asyncio
async def test_compute_bond_performance_shares_fx_series_across_same_currency(db_session):
    """Two bond-market rows sharing a currency must fetch the shared fx_{currency} series
    only once (fx_cache), not once per row."""
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    await create_bond_config(db_session, "in", "Inde", "INGB.AS", "USD", "Obligations indiennes")
    await _seed(db_session, "bond_us_govt", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 95.0)])
    await _seed(db_session, "bond_in_govt", [(ANCHOR_TARGET, 50.0), (FIXED_TODAY, 55.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    call_log: list[str] = []

    async def _counting_get_series(db, series):
        call_log.append(series)
        return await real_get_series(db, series)

    with patch("app.services.bond_performance_service.get_series", side_effect=_counting_get_series):
        results = await compute_bond_performance(db_session)

    assert call_log.count("fx_usd") == 1
    assert len(results) == 2


@pytest.mark.asyncio
async def test_compute_bond_performance_excludes_missing_price_latest(db_session):
    """Price series has an anchor point but nothing recent enough for 'today'."""
    await create_bond_config(db_session, "us", "États-Unis", "IEF", "USD", "Trésor américain")
    await _seed(db_session, "bond_us_govt", [(ANCHOR_TARGET, 100.0)])
    assert await compute_bond_performance(db_session) == []


@pytest.mark.asyncio
async def test_compute_bond_performance_sorts_ascending_no_truncation(db_session):
    """No Top-N — every valid row is returned, sorted ascending by perf_pct for left-to-right
    chart display."""
    seed_data = [
        ("aa", -5.0), ("bb", 12.0), ("cc", 0.5), ("dd", 8.0),
    ]
    for code, pct in seed_data:
        await create_bond_config(db_session, code, code.upper(), f"TICK-{code}", "EUR", f"{code.upper()} bond")
        latest = 100.0 * (1 + pct / 100.0)
        await _seed(db_session, f"bond_{code}_govt", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, latest)])

    results = await compute_bond_performance(db_session)

    assert [r.code for r in results] == ["aa", "cc", "dd", "bb"]
    assert results[0].perf_pct == pytest.approx(-5.0)
    assert results[-1].perf_pct == pytest.approx(12.0)
