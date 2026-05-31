"""
Health-check endpoint — the one test that can run without a database.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_health_no_db():
    """GET /health must return 200 {"status": "ok"} without any database connection."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_via_fixture(client):
    """Same check through the shared fixture (confirms fixture wiring works)."""
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
