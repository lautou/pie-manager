# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

# index.html is requested at a stable, unhashed URL, so a client that caches it without
# revalidating never sees a newer app version no matter how many times frontend_dist is
# rebuilt/re-staged on disk - confirmed live (issue #118) as the actual root cause of a native
# WebView2 launcher serving a build from days earlier, well after the on-disk files (both the
# installed package's own copy and the staged writable copy) were already correct. FileResponse
# with no explicit Cache-Control leaves this to the client's own heuristic caching, which can
# pick an arbitrarily long freshness lifetime. "no-cache" (not "no-store") still allows caching
# but forces revalidation against the ETag/Last-Modified FileResponse already sets, so an
# unchanged file is a cheap 304 and a changed one is always fetched fresh.
_INDEX_HTML_HEADERS = {"Cache-Control": "no-cache"}
# Vite fingerprints every built asset filename with a content hash, so a given URL's content
# never changes - safe to let clients cache these indefinitely instead of revalidating on every
# request.
_ASSET_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def mount_frontend(app: FastAPI, dist_dir: str | None) -> None:
    """Serves the built frontend (`vite build`'s `dist/` output) for the native-Windows-port
    MVP (issue #82). A no-op when dist_dir is unset or doesn't exist — the containerized
    deployment never sets FRONTEND_DIST_DIR, since the frontend runs via its own Vite dev
    server / HAProxy there instead.

    Must be called after every app.include_router(...) call and after any standalone route
    definitions (e.g. GET /health): the catch-all GET /{full_path:path} route this registers
    would otherwise shadow every route registered after it, since FastAPI/Starlette matches
    routes in registration order, not by specificity.
    """
    if not dist_dir or not os.path.isdir(dist_dir):
        return

    real_dist_dir = os.path.realpath(dist_dir)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        candidate = os.path.realpath(os.path.join(real_dist_dir, full_path))
        if _is_within(real_dist_dir, candidate) and full_path and os.path.isfile(candidate):
            headers = _INDEX_HTML_HEADERS if os.path.basename(candidate) == "index.html" else _ASSET_HEADERS
            return FileResponse(candidate, headers=headers)
        # React Router (BrowserRouter) uses real client-side paths - any path that isn't a
        # real static file (a fresh page load on a deep link, e.g. /portfolio/1/dashboard)
        # falls back to index.html so the client-side router can take over.
        return FileResponse(os.path.join(real_dist_dir, "index.html"), headers=_INDEX_HTML_HEADERS)


def _is_within(base_dir: str, candidate: str) -> bool:
    """Path-traversal guard: reports whether candidate resolves to a location inside base_dir.
    full_path is attacker-controlled (any URL path segment, including "../" sequences) - without
    this check, a crafted request could escape dist_dir and read arbitrary files the process
    has access to.
    """
    try:
        return os.path.commonpath([base_dir, candidate]) == base_dir
    except ValueError:
        # Raised on Windows when the two paths are on different drives - definitely "outside".
        return False
