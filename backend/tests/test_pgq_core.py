# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for app/core/pgq.py — the asyncpg pool/Queries wiring for the web process (issue #66
step 3). Resets the module's global state after each test since it holds process-lifetime
singletons (_pool/_queries), unlike router tests which fully replace the get_pgq_queries
dependency via dependency_overrides and never touch this module's globals directly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core import pgq


@pytest.fixture(autouse=True)
def _reset_pgq_module_state():
    yield
    pgq._pool = None
    pgq._queries = None


def test_asyncpg_dsn_strips_the_sqlalchemy_driver_suffix():
    with patch("app.core.pgq.settings") as mock_settings:
        mock_settings.database_url = "postgresql+asyncpg://pie:pw@host:5432/db"
        assert pgq.asyncpg_dsn() == "postgresql://pie:pw@host:5432/db"


@pytest.mark.asyncio
async def test_init_pgq_pool_success_sets_queries():
    mock_pool = MagicMock()
    mock_pool.get_max_size.return_value = 5  # AsyncpgPoolDriver requires >= 2
    with patch("app.core.pgq.asyncpg.create_pool",
               new_callable=AsyncMock, return_value=mock_pool):
        await pgq.init_pgq_pool()

    assert pgq._pool is mock_pool
    assert pgq._queries is not None
    assert pgq.get_pgq_queries() is pgq._queries


@pytest.mark.asyncio
async def test_init_pgq_pool_failure_does_not_raise_and_leaves_queries_none():
    """The one hard requirement: a broken pool must never be able to block app startup."""
    with patch("app.core.pgq.asyncpg.create_pool",
               new_callable=AsyncMock, side_effect=RuntimeError("no db")):
        await pgq.init_pgq_pool()  # must not raise

    assert pgq._pool is None
    assert pgq._queries is None


@pytest.mark.asyncio
async def test_close_pgq_pool_closes_an_existing_pool():
    mock_pool = AsyncMock()
    pgq._pool = mock_pool
    pgq._queries = MagicMock()

    await pgq.close_pgq_pool()

    mock_pool.close.assert_awaited_once()
    assert pgq._pool is None
    assert pgq._queries is None


@pytest.mark.asyncio
async def test_close_pgq_pool_is_a_no_op_when_no_pool_exists():
    await pgq.close_pgq_pool()  # must not raise
    assert pgq._pool is None


@pytest.mark.asyncio
async def test_close_pgq_pool_swallows_close_errors():
    mock_pool = AsyncMock()
    mock_pool.close.side_effect = RuntimeError("already closed")
    pgq._pool = mock_pool

    await pgq.close_pgq_pool()  # must not raise

    assert pgq._pool is None


def test_get_pgq_queries_raises_503_when_pool_never_came_up():
    with pytest.raises(HTTPException) as exc_info:
        pgq.get_pgq_queries()
    assert exc_info.value.status_code == 503
