"""
Non-regression tests for the macro indicators service (app/services/macro_indicators_service.py).
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.macro_indicator import MacroSeriesPrice
from app.models.system_setting import SystemSetting
from app.services.macro_indicators_service import (
    DEFAULT_MA_YEARS,
    DEFAULT_TICKER_LABELS,
    DEFAULT_TICKERS,
    _rolling_average,
    compute_ratio_indicator,
    create_region,
    delete_region,
    get_macro_settings,
    list_regions,
    replace_series_prices,
    update_region,
)


# ---------------------------------------------------------------------------
# get_macro_settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_macro_settings_all_defaults_when_unset(db_session):
    settings = await get_macro_settings(db_session)
    for series, ticker in DEFAULT_TICKERS.items():
        assert settings[series] == ticker
    for series, label in DEFAULT_TICKER_LABELS.items():
        assert settings[f"{series}_label"] == label
    assert settings["ma_years"] == DEFAULT_MA_YEARS


@pytest.mark.asyncio
async def test_get_macro_settings_overrides_and_parses_ma_years(db_session):
    db_session.add(SystemSetting(key="macro.ticker.oil", value="BZ=F"))
    db_session.add(SystemSetting(key="macro.ticker.oil.label", value="Brent"))
    db_session.add(SystemSetting(key="macro.ma_years", value="5"))
    await db_session.flush()

    settings = await get_macro_settings(db_session)
    assert settings["oil"] == "BZ=F"
    assert settings["oil_label"] == "Brent"
    assert settings["gold"] == DEFAULT_TICKERS["gold"]  # untouched key still defaults
    assert settings["gold_label"] == DEFAULT_TICKER_LABELS["gold"]  # untouched key still defaults
    assert settings["ma_years"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Region CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_regions_empty(db_session):
    assert await list_regions(db_session) == []


@pytest.mark.asyncio
async def test_create_region_and_list_sorted_by_code(db_session):
    await create_region(db_session, "world", "Monde", "MWEQ.L", "BNDW", "Actions Monde", "Obligations Monde")
    await create_region(db_session, "fr", "France", "^FCHI", "MTE.PA", "CAC 40", "Obligations zone euro")

    regions = await list_regions(db_session)
    assert [r.code for r in regions] == ["fr", "world"]
    assert regions[0].label == "France"
    assert regions[0].equity_ticker == "^FCHI"
    assert regions[0].equity_label == "CAC 40"
    assert regions[0].bond_label == "Obligations zone euro"


@pytest.mark.asyncio
async def test_create_region_rejects_invalid_code(db_session):
    with pytest.raises(ValueError, match="Invalid region code"):
        await create_region(db_session, "US!", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")


@pytest.mark.asyncio
async def test_create_region_rejects_duplicate_code(db_session):
    await create_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    with pytest.raises(ValueError, match="already exists"):
        await create_region(db_session, "us", "USA (bis)", "^GSPC", "TLT", "S&P 500", "Treasury")


@pytest.mark.asyncio
async def test_update_region_changes_label_and_tickers_but_not_code(db_session):
    await create_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    updated = await update_region(db_session, "us", "USA", "^GSPC", "TLT", "S&P 500", "Treasury")
    assert updated is not None
    assert updated.code == "us"
    assert updated.label == "USA"
    assert updated.equity_ticker == "^GSPC"
    assert updated.bond_ticker == "TLT"
    assert updated.equity_label == "S&P 500"
    assert updated.bond_label == "Treasury"


@pytest.mark.asyncio
async def test_update_region_unknown_code_returns_none(db_session):
    assert await update_region(db_session, "zz", "Nowhere", "X", "Y", "X label", "Y label") is None


@pytest.mark.asyncio
async def test_delete_region_unknown_code_returns_none(db_session):
    assert await delete_region(db_session, "zz") is None


@pytest.mark.asyncio
async def test_delete_region_succeeds_when_others_remain(db_session):
    await create_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    await create_region(db_session, "fr", "France", "^FCHI", "MTE.PA", "CAC 40", "Obligations zone euro")

    assert await delete_region(db_session, "fr") is True
    remaining = await list_regions(db_session)
    assert [r.code for r in remaining] == ["us"]


@pytest.mark.asyncio
async def test_delete_region_rejects_last_remaining_region(db_session):
    await create_region(db_session, "us", "États-Unis", "^SPXEW", "GOVT", "S&P 500 Equal Weight", "Obligations Trésor")
    with pytest.raises(ValueError, match="last remaining region"):
        await delete_region(db_session, "us")
    # Still there — the failed delete must not have removed it.
    assert [r.code for r in await list_regions(db_session)] == ["us"]


# ---------------------------------------------------------------------------
# replace_series_prices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replace_series_prices_empty_points_is_noop(db_session):
    await replace_series_prices(db_session, "us_equity", [])
    result = await db_session.execute(select(MacroSeriesPrice))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_replace_series_prices_upserts_on_conflict(db_session):
    await replace_series_prices(db_session, "us_equity", [(date(2020, 1, 1), 100.0), (date(2020, 1, 2), 200.0)])
    await db_session.flush()

    # Re-fetch with an updated value for one date and a new date for the other series call —
    # must update the existing row in place, not duplicate it.
    await replace_series_prices(db_session, "us_equity", [(date(2020, 1, 1), 111.0)])
    await db_session.flush()

    result = await db_session.execute(
        select(MacroSeriesPrice).where(MacroSeriesPrice.series == "us_equity").order_by(MacroSeriesPrice.date)
    )
    rows = result.scalars().all()
    assert [(r.date, r.value) for r in rows] == [(date(2020, 1, 1), 111.0), (date(2020, 1, 2), 200.0)]


# ---------------------------------------------------------------------------
# _rolling_average — hand-verified two-pointer sliding window
# ---------------------------------------------------------------------------

def test_rolling_average_drops_points_outside_window():
    dates = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 10), date(2020, 1, 11)]
    values = [10.0, 20.0, 30.0, 40.0]
    # window_years chosen so window == exactly 8 days (8 / 365.25 years)
    averages = _rolling_average(dates, values, window_years=8 / 365.25)
    assert averages == pytest.approx([10.0, 15.0, 25.0, 35.0])


# ---------------------------------------------------------------------------
# compute_ratio_indicator
# ---------------------------------------------------------------------------

async def _seed_series(db_session, series: str, points: list[tuple[date, float]]) -> None:
    await replace_series_prices(db_session, series, points)
    await db_session.flush()


@pytest.mark.asyncio
async def test_compute_ratio_indicator_no_common_dates_returns_empty(db_session):
    await _seed_series(db_session, "num", [(date(2020, 1, 1), 10.0)])
    result = await compute_ratio_indicator(db_session, "num", "den", ma_years=7.0)
    assert result == {
        "dates": [], "ratio": [], "moving_avg": [], "ma_years": None, "status": None, "latest_date": None,
    }


@pytest.mark.asyncio
async def test_compute_ratio_indicator_rebase_to_100_and_status_above(db_session):
    dates = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    await _seed_series(db_session, "num", [(d, v) for d, v in zip(dates, [10.0, 20.0, 30.0])])
    await _seed_series(db_session, "den", [(d, 1.0) for d in dates])

    result = await compute_ratio_indicator(db_session, "num", "den", ma_years=100.0)

    assert result["dates"] == [d.isoformat() for d in dates]
    assert result["ratio"] == pytest.approx([100.0, 200.0, 300.0])
    # ma_years=100 keeps every point in the average window → cumulative mean
    assert result["moving_avg"] == pytest.approx([100.0, 150.0, 200.0])
    assert result["status"] == "above"  # latest ratio 300 > latest moving_avg 200
    assert result["latest_date"] == dates[-1].isoformat()
    assert result["ma_years"] == 100.0


@pytest.mark.asyncio
async def test_compute_ratio_indicator_status_below_on_declining_series(db_session):
    dates = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    await _seed_series(db_session, "num", [(d, v) for d, v in zip(dates, [30.0, 20.0, 10.0])])
    await _seed_series(db_session, "den", [(d, 1.0) for d in dates])

    result = await compute_ratio_indicator(db_session, "num", "den", ma_years=100.0)

    assert result["status"] == "below"  # latest ratio 33.3 < cumulative average


@pytest.mark.asyncio
async def test_compute_ratio_indicator_inner_join_clips_to_common_range(db_session):
    # 'num' has an extra earlier date the 'den' series doesn't have — must be excluded,
    # mirroring the real SP500 (1984+) vs oil (2000+) history-depth mismatch.
    await _seed_series(db_session, "num", [
        (date(2019, 12, 31), 999.0), (date(2020, 1, 1), 10.0), (date(2020, 1, 2), 20.0),
    ])
    await _seed_series(db_session, "den", [(date(2020, 1, 1), 1.0), (date(2020, 1, 2), 1.0)])

    result = await compute_ratio_indicator(db_session, "num", "den", ma_years=7.0)

    assert result["dates"] == ["2020-01-01", "2020-01-02"]
    assert result["ratio"] == pytest.approx([100.0, 200.0])
