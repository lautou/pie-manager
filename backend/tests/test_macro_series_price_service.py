# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the shared (series, date, value) time-series storage
(app/services/macro_series_price_service.py).

replace_series_prices tests moved here from test_macro_indicators_service.py when the
function was extracted; get_series (formerly private _get_series) now gets a direct test
of its own instead of only being exercised indirectly via compute_ratio_indicator.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.macro_indicator import MacroSeriesPrice
from app.services.macro_series_price_service import get_series, replace_series_prices


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
# get_series
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_series_empty_returns_empty_dict(db_session):
    assert await get_series(db_session, "unknown_series") == {}


@pytest.mark.asyncio
async def test_get_series_returns_date_value_dict_ordered_by_date(db_session):
    await replace_series_prices(db_session, "oil", [(date(2020, 1, 2), 50.0), (date(2020, 1, 1), 48.0)])
    await db_session.flush()
    result = await get_series(db_session, "oil")
    assert result == {date(2020, 1, 1): 48.0, date(2020, 1, 2): 50.0}
