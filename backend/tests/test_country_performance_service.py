"""
Non-regression tests for the country performance leaderboard service
(app/services/country_performance_service.py).
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.models.system_setting import SystemSetting
from app.services.country_performance_service import (
    DEFAULT_TOP_N,
    compute_country_performance,
    create_country_config,
    delete_country_config,
    get_top_n,
    list_country_configs,
    update_country_config,
)
from app.services.macro_series_price_service import get_series as real_get_series
from app.services.macro_series_price_service import replace_series_prices

FIXED_TODAY = date(2026, 7, 19)
ANCHOR_TARGET = FIXED_TODAY - timedelta(days=365)


@pytest.fixture(autouse=True)
def _fixed_today():
    """Freezes date.today() as seen by the service module — nothing else in the module
    constructs a date(...) directly, so overriding only .today() is safe."""
    with patch("app.services.country_performance_service.date") as mock_date:
        mock_date.today.return_value = FIXED_TODAY
        yield mock_date


async def _seed(db_session, series: str, points: list[tuple[date, float]]) -> None:
    await replace_series_prices(db_session, series, points)
    await db_session.flush()


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_country_configs_empty(db_session):
    assert await list_country_configs(db_session) == []


@pytest.mark.asyncio
async def test_create_country_config_and_list_sorted_by_code(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")

    countries = await list_country_configs(db_session)
    assert [c.code for c in countries] == ["de", "us"]
    assert countries[0].label == "Allemagne"
    assert countries[0].index_ticker == "^GDAXI"
    assert countries[0].currency == "EUR"
    assert countries[0].index_label == "DAX 40"


@pytest.mark.asyncio
async def test_create_country_config_rejects_invalid_code(db_session):
    with pytest.raises(ValueError, match="Invalid country code"):
        await create_country_config(db_session, "USA", "États-Unis", "^GSPC", "USD", "S&P 500")


@pytest.mark.asyncio
async def test_create_country_config_rejects_invalid_currency(db_session):
    with pytest.raises(ValueError, match="Invalid currency"):
        await create_country_config(db_session, "us", "États-Unis", "^GSPC", "usd", "S&P 500")


@pytest.mark.asyncio
async def test_create_country_config_rejects_duplicate_code(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    with pytest.raises(ValueError, match="already exists"):
        await create_country_config(db_session, "us", "USA (bis)", "^SPXEW", "USD", "S&P 500 EW")


@pytest.mark.asyncio
async def test_update_country_config_changes_fields_but_not_code(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    updated = await update_country_config(db_session, "us", "USA", "^SPXEW", "USD", "S&P 500 EW")
    assert updated is not None
    assert updated.code == "us"
    assert updated.label == "USA"
    assert updated.index_ticker == "^SPXEW"
    assert updated.index_label == "S&P 500 EW"


@pytest.mark.asyncio
async def test_update_country_config_rejects_invalid_currency(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    with pytest.raises(ValueError, match="Invalid currency"):
        await update_country_config(db_session, "us", "USA", "^GSPC", "usd", "S&P 500")


@pytest.mark.asyncio
async def test_update_country_config_unknown_code_returns_none(db_session):
    assert await update_country_config(db_session, "zz", "Nowhere", "X", "EUR", "Index") is None


@pytest.mark.asyncio
async def test_delete_country_config_unknown_code_returns_none(db_session):
    assert await delete_country_config(db_session, "zz") is None


@pytest.mark.asyncio
async def test_delete_country_config_succeeds_even_as_last_row(db_session):
    """Unlike MacroRegion, there is deliberately no 'last remaining row' guard — the
    universe can be emptied out entirely, yielding an empty leaderboard."""
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    assert await delete_country_config(db_session, "us") is True
    assert await list_country_configs(db_session) == []


# ---------------------------------------------------------------------------
# get_top_n
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_top_n_default_when_unset(db_session):
    assert await get_top_n(db_session) == DEFAULT_TOP_N


@pytest.mark.asyncio
async def test_get_top_n_reads_valid_override(db_session):
    db_session.add(SystemSetting(key="country_perf.top_n", value="8"))
    await db_session.flush()
    assert await get_top_n(db_session) == 8


@pytest.mark.asyncio
async def test_get_top_n_falls_back_on_unparsable_value(db_session):
    db_session.add(SystemSetting(key="country_perf.top_n", value="not-a-number"))
    await db_session.flush()
    assert await get_top_n(db_session) == DEFAULT_TOP_N


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", ["0", "-5"])
async def test_get_top_n_falls_back_on_non_positive(db_session, bad_value):
    db_session.add(SystemSetting(key="country_perf.top_n", value=bad_value))
    await db_session.flush()
    assert await get_top_n(db_session) == DEFAULT_TOP_N


# ---------------------------------------------------------------------------
# compute_country_performance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_country_performance_no_countries_returns_empty(db_session):
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_eur_country_skips_fx(db_session):
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await _seed(db_session, "country_de_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 150.0)])

    results = await compute_country_performance(db_session, top_n=15)

    assert len(results) == 1
    assert results[0].code == "de"
    assert results[0].perf_pct == pytest.approx(50.0)
    assert results[0].index_label == "DAX 40"


@pytest.mark.asyncio
async def test_compute_country_performance_non_eur_country_applies_fx(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    await _seed(db_session, "country_us_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    results = await compute_country_performance(db_session, top_n=15)

    assert len(results) == 1
    expected = ((110.0 / 100.0) * (0.95 / 0.9) - 1) * 100
    assert results[0].perf_pct == pytest.approx(expected)


@pytest.mark.asyncio
async def test_compute_country_performance_shares_fx_series_across_same_currency(db_session):
    """Two countries with the same currency must fetch the shared fx_{currency} series only
    once (fx_cache), not once per country."""
    await create_country_config(db_session, "xa", "Test USD A", "TICKA", "USD", "Index A")
    await create_country_config(db_session, "xb", "Test USD B", "TICKB", "USD", "Index B")
    await _seed(db_session, "country_xa_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "country_xb_equity", [(ANCHOR_TARGET, 50.0), (FIXED_TODAY, 55.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9), (FIXED_TODAY, 0.95)])

    call_log: list[str] = []

    async def _counting_get_series(db, series):
        call_log.append(series)
        return await real_get_series(db, series)

    with patch("app.services.country_performance_service.get_series", side_effect=_counting_get_series):
        results = await compute_country_performance(db_session, top_n=15)

    assert call_log.count("fx_usd") == 1
    assert len(results) == 2


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_missing_index_latest(db_session):
    """Index series has an anchor point but nothing recent enough for 'today'."""
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await _seed(db_session, "country_de_equity", [(ANCHOR_TARGET, 100.0)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_missing_index_anchor(db_session):
    """Index series has a recent point but nothing near the 1-year-ago anchor."""
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await _seed(db_session, "country_de_equity", [(FIXED_TODAY, 150.0)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_zero_index_anchor(db_session):
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await _seed(db_session, "country_de_equity", [(ANCHOR_TARGET, 0.0), (FIXED_TODAY, 150.0)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_missing_fx_latest(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    await _seed(db_session, "country_us_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.9)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_missing_fx_anchor(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    await _seed(db_session, "country_us_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "fx_usd", [(FIXED_TODAY, 0.95)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_excludes_zero_fx_anchor(db_session):
    await create_country_config(db_session, "us", "États-Unis", "^GSPC", "USD", "S&P 500")
    await _seed(db_session, "country_us_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "fx_usd", [(ANCHOR_TARGET, 0.0), (FIXED_TODAY, 0.95)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_asof_boundary_within_tolerance_included(db_session):
    """A snapshot exactly ASOF_TOLERANCE_DAYS (10) before the anchor target still counts."""
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    boundary_anchor = ANCHOR_TARGET - timedelta(days=10)
    await _seed(db_session, "country_de_equity", [(boundary_anchor, 100.0), (FIXED_TODAY, 150.0)])
    results = await compute_country_performance(db_session, top_n=15)
    assert len(results) == 1
    assert results[0].anchor_date == boundary_anchor


@pytest.mark.asyncio
async def test_compute_country_performance_asof_boundary_beyond_tolerance_excluded(db_session):
    """A snapshot 11 days before the anchor target (one day past tolerance) is excluded."""
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    beyond_anchor = ANCHOR_TARGET - timedelta(days=11)
    await _seed(db_session, "country_de_equity", [(beyond_anchor, 100.0), (FIXED_TODAY, 150.0)])
    assert await compute_country_performance(db_session, top_n=15) == []


@pytest.mark.asyncio
async def test_compute_country_performance_fewer_than_top_n_returns_all(db_session):
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await create_country_config(db_session, "fr", "France", "^FCHI", "EUR", "CAC 40")
    await _seed(db_session, "country_de_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 110.0)])
    await _seed(db_session, "country_fr_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 105.0)])

    results = await compute_country_performance(db_session, top_n=15)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_compute_country_performance_top_n_selects_best_and_sorts_ascending(db_session):
    seed_data = [
        ("aa", -5.0), ("bb", 50.0), ("cc", 10.0), ("dd", 20.0),
    ]
    for code, pct in seed_data:
        await create_country_config(db_session, code, code.upper(), f"^{code.upper()}", "EUR", f"{code.upper()} Index")
        latest = 100.0 * (1 + pct / 100.0)
        await _seed(db_session, f"country_{code}_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, latest)])

    results = await compute_country_performance(db_session, top_n=2)

    assert [r.code for r in results] == ["dd", "bb"]  # 20% then 50%, ascending
    assert results[0].perf_pct == pytest.approx(20.0)
    assert results[1].perf_pct == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_compute_country_performance_uses_get_top_n_when_not_provided(db_session):
    db_session.add(SystemSetting(key="country_perf.top_n", value="1"))
    await db_session.flush()
    await create_country_config(db_session, "de", "Allemagne", "^GDAXI", "EUR", "DAX 40")
    await create_country_config(db_session, "fr", "France", "^FCHI", "EUR", "CAC 40")
    await _seed(db_session, "country_de_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 120.0)])
    await _seed(db_session, "country_fr_equity", [(ANCHOR_TARGET, 100.0), (FIXED_TODAY, 105.0)])

    results = await compute_country_performance(db_session)  # top_n omitted

    assert len(results) == 1
    assert results[0].code == "de"
