"""
Shared test fixtures for the PIE Manager backend test suite.

All tests use an isolated `pie_test` database — never touches production.
"""
import asyncio
import os
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app as fastapi_app
from app.core.database import get_db, Base  # Base imported from database so all models are registered
from app.core.pgq import get_pgq_queries
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

    Also overrides get_pgq_queries with a harmless default (queries.enqueue always
    "succeeds", no assertions made on it) — necessary, not cosmetic: AsyncClient's
    ASGITransport never runs FastAPI's lifespan, so app/core/pgq.py's module-level pool stays
    None for the whole test session, and several routes (create/update/delete_transaction, the
    bulk-import commit endpoint, and every already-PgQueuer-backed router) now hard-depend on
    get_pgq_queries() resolving. Without this default they'd all 503. A test that wants to
    inspect enqueue calls sets its own override afterward, inside the test body — that
    reassignment takes precedence and is still cleared by the same .clear() below.
    """
    async def override_get_db():
        yield db_session

    default_queries = MagicMock()
    default_queries.enqueue = AsyncMock(return_value=[0])

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: default_queries
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()


async def fetch_latest_job_run(task_name: str):
    """Test helper: read back the most recent job_runs row for a task — thin wrapper around
    app/tasks/job_runs.py's own get_latest(), kept here so existing call sites don't need to
    import job_runs directly."""
    from app.tasks import job_runs

    return await job_runs.get_latest(task_name)
