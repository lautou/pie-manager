# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the sector/commodity performance service
(app/services/sector_performance_service.py). Mirrors
test_country_performance_service.py — the exhaustive as-of/FX-edge-case matrix lives in
test_performance_math.py (the shared math this service delegates to); these tests cover CRUD
and the orchestration this module owns itself (FX caching/dedup, no Top-N truncation).
"""
from unittest.mock import patch

import pytest

from app.services.sector_performance_service import (
    compute_sector_performance,
    create_sector_config,
    delete_sector_config,
    list_sector_configs,
    update_sector_config,
)
from app.services.macro_series_price_service import get_series as real_get_series
from tests.helpers import FIXED_TODAY, ANCHOR_TARGET, make_fixed_today_fixture, seed_series_points as _seed

_fixed_today = make_fixed_today_fixture("app.services.sector_performance_service")


# ---------------------------------------------------------------------------
# Sector CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sector_configs_empty(db_session):
    assert await list_sector_configs(db_session) == []


@pytest.mark.asyncio
async def test_create_sector_config_and_list_sorted_by_code(db_session):
    await create_sector_config(db_session, "petrole", "Pétrole", "CL=F", "USD", "Pétrole (WTI)")
    await create_sector_config(db_session, "agriculture", "Agriculture", "DBA", "USD", "Invesco DB Agriculture Fund")

    sectors = await list_sector_configs(db_session)
    assert [s.code for s in sectors] == ["agriculture", "petrole"]
    assert sectors[0].label == "Agriculture"
    assert sectors[0].index_ticker == "DBA"
    assert sectors[0].currency == "USD"
    assert sectors[0].index_label == "Invesco DB Agriculture Fund"


@pytest.mark.asyncio
async def test_create_sector_config_rejects_invalid_code(db_session):
    with pytest.raises(ValueError, match="Invalid sector code"):
        await create_sector_config(db_session, "OR", "Or", "GC=F", "USD", "Or (COMEX)")


@pytest.mark.asyncio
async def test_create_sector_config_rejects_invalid_currency(db_session):
    with pytest.raises(ValueError, match="Invalid currency"):
        await create_sector_config(db_session, "or", "Or", "GC=F", "usd", "Or (COMEX)")


@pytest.mark.asyncio
async def test_create_sector_config_rejects_duplicate_code(db_session):
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    with pytest.raises(ValueError, match="already exists"):
        await create_sector_config(db_session, "or", "Or (bis)", "GC=F", "USD", "Or (COMEX)")


@pytest.mark.asyncio
async def test_update_sector_config_changes_fields_but_not_code(db_session):
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    updated = await update_sector_config(db_session, "or", "Or physique", "GC=F", "USD", "Gold Futures")
    assert updated is not None
    assert updated.code == "or"
    assert updated.label == "Or physique"
    assert updated.index_label == "Gold Futures"


@pytest.mark.asyncio
async def test_update_sector_config_rejects_invalid_currency(db_session):
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    with pytest.raises(ValueError, match="Invalid currency"):
        await update_sector_config(db_session, "or", "Or", "GC=F", "usd", "Or (COMEX)")


@pytest.mark.asyncio
async def test_update_sector_config_unknown_code_returns_none(db_session):
    assert await update_sector_config(db_session, "zz", "Nowhere", "X", "USD", "Index") is None


@pytest.mark.asyncio
async def test_delete_sector_config_unknown_code_returns_none(db_session):
    assert await delete_sector_config(db_session, "zz") is None


@pytest.mark.asyncio
async def test_delete_sector_config_succeeds_even_as_last_row(db_session):
    """No 'last remaining row' guard — the universe can be emptied out entirely, yielding an
    empty chart."""
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    assert await delete_sector_config(db_session, "or") is True
    assert await list_sector_configs(db_session) == []


# ---------------------------------------------------------------------------
# compute_sector_performance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_sector_performance_no_sectors_returns_empty(db_session):
    assert await compute_sector_performance(db_session) == []


@pytest.mark.asyncio
async def test_compute_sector_performance_eur_sector_skips_fx(db_session):
    await create_sector_config(db_session, "testeur", "Test EUR", "TICK", "EUR", "Index")
    await _seed(db_session, "sector_testeur_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 150.0)])

    results = await compute_sector_performance(db_session)

    assert len(results) == 1
    assert results[0].code == "testeur"
    assert results[0].perf_pct == pytest.approx(50.0)
    assert results[0].index_label == "Index"


@pytest.mark.asyncio
async def test_compute_sector_performance_non_eur_sector_applies_fx(db_session):
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    await _seed(db_session, "sector_or_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    results = await compute_sector_performance(db_session)

    assert len(results) == 1
    expected = ((110.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert results[0].perf_pct == pytest.approx(expected)


@pytest.mark.asyncio
async def test_compute_sector_performance_shares_fx_series_across_same_currency(db_session):
    """Two sectors sharing a currency must fetch the shared fx_{currency} series only once
    (fx_cache), not once per sector."""
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    await create_sector_config(db_session, "petrole", "Pétrole", "CL=F", "USD", "Pétrole (WTI)")
    await _seed(db_session, "sector_or_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "sector_petrole_equity", [(ANCHOR_TARGET, 50.0), (FIXED_TODAY, 55.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    call_log: list[str] = []

    async def _counting_get_series(db, series):
        call_log.append(series)
        return await real_get_series(db, series)

    with patch("app.services.sector_performance_service.get_series", side_effect=_counting_get_series):
        results = await compute_sector_performance(db_session)

    assert call_log.count("fx_usd") == 1
    assert len(results) == 2


@pytest.mark.asyncio
async def test_compute_sector_performance_excludes_missing_index_latest(db_session):
    """Index series has an anchor point but nothing recent enough for 'today'."""
    await create_sector_config(db_session, "or", "Or", "GC=F", "USD", "Or (COMEX)")
    await _seed(db_session, "sector_or_equity", [(ANCHOR_TARGET, 100.0)])
    assert await compute_sector_performance(db_session) == []


@pytest.mark.asyncio
async def test_compute_sector_performance_sorts_ascending_no_truncation(db_session):
    """Unlike country performance, there is no Top-N — every valid row is returned, sorted
    ascending by perf_pct for left-to-right chart display."""
    seed_data = [
        ("aa", -5.0), ("bb", 50.0), ("cc", 10.0), ("dd", 20.0),
    ]
    for code, pct in seed_data:
        await create_sector_config(db_session, code, code.upper(), f"TICK-{code}", "EUR", f"{code.upper()} Index")
        latest = 100.0 * (1 + pct / 100.0)
        await _seed(db_session, f"sector_{code}_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, latest)])

    results = await compute_sector_performance(db_session)

    assert [r.code for r in results] == ["aa", "cc", "dd", "bb"]
    assert results[0].perf_pct == pytest.approx(-5.0)
    assert results[-1].perf_pct == pytest.approx(50.0)
