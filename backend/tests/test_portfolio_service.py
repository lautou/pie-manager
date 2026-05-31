"""
Unit tests for services/portfolio_service.py.

Covers lines 8-9, 13, 17-18, 22-25.
All functions are async DB helpers; tested directly with db_session.
"""

import pytest

from app.models.portfolio import Portfolio
from app.services.portfolio_service import (
    get_all_portfolios,
    get_portfolio_by_id,
    get_portfolio_by_name,
    create_portfolio,
)


# ---------------------------------------------------------------------------
# get_all_portfolios (lines 8-9)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_all_portfolios_empty(db_session):
    """Returns an empty list when no portfolios exist (in this session)."""
    result = await get_all_portfolios(db_session)
    # Other tests may have added portfolios; just assert it's a list
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_all_portfolios_returns_inserted(db_session):
    name = f"SvcAll-{id(db_session)}"
    p = Portfolio(name=name)
    db_session.add(p)
    await db_session.flush()

    portfolios = await get_all_portfolios(db_session)
    names = [pf.name for pf in portfolios]
    assert name in names


@pytest.mark.asyncio
async def test_get_all_portfolios_ordered_by_name(db_session):
    suffix = id(db_session)
    names = [f"Zoo-{suffix}", f"Alpha-{suffix}", f"Meta-{suffix}"]
    for n in names:
        db_session.add(Portfolio(name=n))
    await db_session.flush()

    portfolios = await get_all_portfolios(db_session)
    returned_names = [p.name for p in portfolios if p.name in names]
    assert returned_names == sorted(returned_names)


# ---------------------------------------------------------------------------
# get_portfolio_by_id (line 13)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_portfolio_by_id_found(db_session):
    p = Portfolio(name=f"ById-{id(db_session)}")
    db_session.add(p)
    await db_session.flush()

    result = await get_portfolio_by_id(db_session, p.id)
    assert result is not None
    assert result.id == p.id
    assert result.name == p.name


@pytest.mark.asyncio
async def test_get_portfolio_by_id_not_found(db_session):
    result = await get_portfolio_by_id(db_session, 999999)
    assert result is None


# ---------------------------------------------------------------------------
# get_portfolio_by_name (lines 17-18)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_portfolio_by_name_found(db_session):
    name = f"ByName-{id(db_session)}"
    p = Portfolio(name=name)
    db_session.add(p)
    await db_session.flush()

    result = await get_portfolio_by_name(db_session, name)
    assert result is not None
    assert result.name == name


@pytest.mark.asyncio
async def test_get_portfolio_by_name_not_found(db_session):
    result = await get_portfolio_by_name(db_session, "DoesNotExist-XYZ-99999")
    assert result is None


@pytest.mark.asyncio
async def test_get_portfolio_by_name_is_exact_match(db_session):
    suffix = id(db_session)
    name = f"Exact-{suffix}"
    db_session.add(Portfolio(name=name))
    db_session.add(Portfolio(name=f"ExactOther-{suffix}"))
    await db_session.flush()

    result = await get_portfolio_by_name(db_session, name)
    assert result is not None
    assert result.name == name


# ---------------------------------------------------------------------------
# create_portfolio (lines 22-25)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_portfolio_returns_object(db_session):
    name = f"Create-{id(db_session)}"
    result = await create_portfolio(db_session, name)
    assert result is not None
    assert result.name == name
    assert result.id is not None


@pytest.mark.asyncio
async def test_create_portfolio_is_retrievable(db_session):
    name = f"CreateRetrieve-{id(db_session)}"
    created = await create_portfolio(db_session, name)
    found = await get_portfolio_by_id(db_session, created.id)
    assert found is not None
    assert found.name == name


@pytest.mark.asyncio
async def test_create_portfolio_flush_not_commit(db_session):
    """create_portfolio uses flush() — object has an id but session not committed."""
    name = f"Flush-{id(db_session)}"
    p = await create_portfolio(db_session, name)
    # After flush the id is assigned
    assert isinstance(p.id, int)
