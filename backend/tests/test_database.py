"""
Tests for app/core/database.py.

Target: 100% coverage (lines 15-16 — the get_db async generator body).

The get_db() function is an async generator:

    async def get_db() -> AsyncSession:
        async with AsyncSessionLocal() as session:   # line 15
            yield session                             # line 16

Lines 15-16 are the body of get_db().  They are not exercised by the
conftest override (which short-circuits the dependency), so we call the
generator directly here.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, Base  # noqa: F401 — registers models


@pytest.mark.asyncio
async def test_get_db_yields_async_session():
    """
    Calling get_db() directly exercises lines 15-16:
      - async with AsyncSessionLocal() as session:   → line 15
      - yield session                                → line 16

    We iterate the generator, verify we get an AsyncSession, then close it.
    """
    gen = get_db()
    session = await gen.__anext__()
    try:
        assert isinstance(session, AsyncSession), (
            f"Expected AsyncSession, got {type(session)}"
        )
    finally:
        # Close the generator (triggers the finally / context-manager cleanup).
        try:
            await gen.aclose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_get_db_session_is_usable():
    """
    The yielded session should be usable (not already closed).
    We run a trivial no-op execute to confirm it is alive.
    """
    from sqlalchemy import text

    gen = get_db()
    session = await gen.__anext__()
    try:
        result = await session.execute(text("SELECT 1"))
        assert result is not None
    finally:
        await gen.aclose()
