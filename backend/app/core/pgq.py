"""
PgQueuer asyncpg pool + Queries for the web process (issue #66 step 3).

Mirrors app/core/database.py's own get_db/AsyncSessionLocal idiom (module-level state + a
plain dependency function) rather than PgQueuer's own app.extra example pattern — this keeps
the dependency overridable in tests via app.dependency_overrides[get_pgq_queries], exactly
like get_db already works.

An asyncpg pool can't be built at import time (needs a running event loop), unlike
database.py's engine — so this module exposes explicit init/close hooks for app.main's
lifespan instead of module-level construction.
"""

import logging

import asyncpg
from fastapi import HTTPException
from pgqueuer import AsyncpgPoolDriver, Queries

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_queries: Queries | None = None


def asyncpg_dsn() -> str:
    """asyncpg wants a plain postgresql:// DSN, not SQLAlchemy's +asyncpg driver suffix — same
    conversion already used by admin.py's _pg_conn_args() for pg_dump/pg_restore."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def init_pgq_pool() -> None:
    """Never raises — mirrors main.py's existing per-block try/except startup style. A failed
    pool construction leaves get_pgq_queries() raising a clean 503 rather than blocking the
    rest of app startup."""
    global _pool, _queries
    try:
        # AsyncpgPoolDriver requires pool.get_max_size() >= 2 (raises RuntimeError otherwise,
        # confirmed from pgqueuer's own source) — max_size=5 comfortably clears that floor.
        _pool = await asyncpg.create_pool(dsn=asyncpg_dsn(), min_size=1, max_size=5)
        _queries = Queries(AsyncpgPoolDriver(_pool))
    except Exception:
        logger.exception("Failed to initialize PgQueuer pool; on-demand job enqueueing unavailable")
        _pool = None
        _queries = None


async def close_pgq_pool() -> None:
    """Also never raises — defensive shutdown."""
    global _pool, _queries
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            logger.exception("Error closing PgQueuer pool")
    _pool = None
    _queries = None


def get_pgq_queries() -> Queries:
    """FastAPI dependency. Raises a clean 503 (not an unhandled exception) if the pool never
    came up — parity with how a down broker surfaces as a request-time failure today, just a
    controlled one instead of an unhandled 500."""
    if _queries is None:
        raise HTTPException(status_code=503, detail="Job queue unavailable")
    return _queries
