"""
Shared test fixtures for the PIE Manager backend test suite.

All tests use an isolated `pie_test` database — never touches production.
"""
import asyncio
import os
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app as fastapi_app
from app.core.database import get_db, Base  # Base imported from database so all models are registered
import app.models  # noqa: F401 — side-effect import to ensure all ORM classes are in Base.metadata

TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://pie:pie_password@localhost:5432/pie_test",
)


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop (required for session-scoped async fixtures)."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def engine():
    """
    Create a fresh test database schema at the start of the session and
    drop it afterwards.  NullPool prevents any connection sharing between tests.
    """
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    """
    Provide a fully isolated per-test session via SAVEPOINTs.

    Commits issued inside FastAPI routers (await db.commit()) create a SAVEPOINT
    instead of committing the outer transaction. After each test the connection is
    rolled back — everything is undone, including what was "committed".
    """
    conn = await engine.connect()
    await conn.begin()  # outer transaction (never committed)

    session = AsyncSession(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",  # commit → SAVEPOINT, not a real commit
    )
    try:
        yield session
    finally:
        await session.close()
        await conn.rollback()   # undo EVERYTHING, including test "commits"
        await conn.close()


@pytest.fixture
async def client(db_session):
    """
    Async HTTP client wired to the FastAPI app with the test DB session injected.
    Dependency override is cleared after every test.
    """
    async def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()
