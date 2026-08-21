"""
Tests for app/frontend.py — the native-Windows-port MVP's (issue #82) conditional frontend
static-file serving.

Always tested against a fresh, isolated FastAPI() instance, never the shared app.main.app
singleton conftest.py's `client` fixture wires up. The real app calls mount_frontend() once at
import time with settings.frontend_dist_dir (unset in the test environment), so the shared app
never has this catch-all route registered — mutating the shared app directly here would leak a
route into every other test in the suite.
"""
import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.frontend import _is_within, mount_frontend


def _make_app(dist_dir):
    app = FastAPI()

    @app.get("/api/health")
    async def api_health():
        return {"status": "from-api"}

    mount_frontend(app, dist_dir)
    return app


@pytest.fixture
def dist_dir(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<html>index</html>")
    assets = d / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('app')")
    return str(d)


async def test_noop_when_dist_dir_none():
    app = _make_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/some/random/path")
    assert resp.status_code == 404  # no catch-all registered at all


async def test_noop_when_dist_dir_missing(tmp_path):
    app = _make_app(str(tmp_path / "does-not-exist"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/some/random/path")
    assert resp.status_code == 404


async def test_serves_index_html_at_root(dist_dir):
    app = _make_app(dist_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/")
    assert resp.status_code == 200
    assert "index" in resp.text
    # index.html must always revalidate - a stale cached copy at this stable, unhashed URL is
    # what let a native WebView2 launcher keep serving a days-old build (issue #118), even after
    # frontend_dist was correctly rebuilt and re-staged on disk.
    assert resp.headers["cache-control"] == "no-cache"


async def test_serves_index_html_for_spa_deep_link(dist_dir):
    """React Router's BrowserRouter uses real client-side paths - a fresh load on a deep link
    (e.g. reloading the page while on /portfolio/1/dashboard) must still get index.html so the
    client-side router can take over, not a 404."""
    app = _make_app(dist_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/portfolio/1/dashboard")
    assert resp.status_code == 200
    assert "index" in resp.text
    assert resp.headers["cache-control"] == "no-cache"


async def test_serves_index_html_when_requested_directly(dist_dir):
    """A direct /index.html request (not the SPA-fallback path) hits the "real file" branch, not
    the fallback FileResponse - must still get the same no-cache treatment, not the long-lived
    asset caching a hashed filename would get."""
    app = _make_app(dist_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/index.html")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


async def test_serves_real_static_asset(dist_dir):
    app = _make_app(dist_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text
    # Vite fingerprints asset filenames with a content hash, so a given URL's content never
    # changes - safe, and desirable for performance, to let clients cache these indefinitely.
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_api_routes_take_priority_over_catchall(dist_dir):
    """The catch-all is registered after mount_frontend() is called - here, and in the real
    app.main, after every API router - so an existing API route must still win, not be
    shadowed by the SPA fallback."""
    app = _make_app(dist_dir)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "from-api"}


async def test_path_traversal_encoded_falls_back_to_index(dist_dir):
    """Defense in depth at the HTTP level: even a percent-encoded traversal attempt (bypassing
    httpx's own client-side dot-segment normalization on a literal "..") must not leak a file
    outside dist_dir. The actual guard logic itself is unit-tested directly below
    (test_is_within_*) - this proves it's wired into the real request path too."""
    app = _make_app(dist_dir)
    outside_dir = os.path.dirname(dist_dir)
    secret_path = os.path.join(outside_dir, "secret.txt")
    with open(secret_path, "w") as f:
        f.write("should never be served")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/%2e%2e/secret.txt")
    assert "should never be served" not in resp.text


def test_is_within_true_for_nested_path(tmp_path):
    base = str(tmp_path)
    nested = os.path.join(base, "assets", "app.js")
    assert _is_within(base, nested) is True


def test_is_within_true_for_base_itself(tmp_path):
    base = str(tmp_path)
    assert _is_within(base, base) is True


def test_is_within_false_for_path_outside_base(tmp_path):
    base = str(tmp_path / "dist")
    outside = str(tmp_path / "secret.txt")
    assert _is_within(base, outside) is False


def test_is_within_false_when_commonpath_raises(tmp_path):
    """os.path.commonpath raises ValueError when mixing an absolute and a relative path (on
    POSIX) or paths on different drives (on Windows, the scenario this branch's own comment
    documents - unreachable on POSIX CI, since candidate is always built via os.path.realpath
    in real usage and thus always absolute; exercised here directly against _is_within to cover
    the exception branch itself)."""
    assert _is_within(str(tmp_path), "relative/path") is False


def test_is_within_false_for_sibling_directory_with_matching_prefix(tmp_path):
    """A naive string-prefix check (base_dir.startswith or "in") would wrongly treat
    "/a/distXXX" as inside "/a/dist" - os.path.commonpath correctly distinguishes them by path
    component, not by character prefix."""
    base = str(tmp_path / "dist")
    sibling = str(tmp_path / "dist-evil" / "secret.txt")
    assert _is_within(base, sibling) is False
