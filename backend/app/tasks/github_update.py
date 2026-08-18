"""
GitHub-release update check (issue #113) — scheduled via app/tasks/pgq_app.py, every 6h.

The frontend (frontend/src/api/queries.ts's useGitHubUpdateStatus) has always called
GET /api/admin/github-update-status, fully tested end to end on that side, but the backend
never implemented the route — confirmed via grep, zero matches anywhere in this app before
this file existed.

Design: only the "what's the latest GitHub release" half is cached (via SystemSetting,
refreshed periodically by run_github_update_check below) — the comparison against the
currently-running version is always computed live in compute_github_update_status, so the
reported status is correct immediately after an app upgrade rather than stale until the next
6h tick. A failed check (network error, GitHub API down) never overwrites a previously
successful latest_version/release_url — it only records the error, so a transient hiccup
can't regress a working badge back into an 'error' state.

lautou/pie-manager is a public repository, so the unauthenticated GitHub API is used
directly — no token, no rate-limit concern at a once-per-6h check frequency (well under the
60 requests/hour unauthenticated cap). The frontend's GitHubUpdateStatus.status type also
allows 'no_token', anticipating an optional PAT for a higher rate limit; not needed here and
deliberately not implemented, since no version of the check this app performs can ever
require it.
"""

import json
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_setting import SystemSetting

GITHUB_RELEASES_URL = "https://api.github.com/repos/lautou/pie-manager/releases/latest"
CACHE_KEY = "github_update.cache"


def get_current_version() -> str:
    """Same priority order as GET /api/admin/version (app/api/routers/admin.py) — both call
    this so the two can never drift apart."""
    import os
    return os.getenv("INSTALLER_VERSION") or os.getenv("APP_VERSION") or "UNKNOWN"


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    a, b, c = match.groups()
    return (int(a), int(b), int(c))


async def _read_cache(db: AsyncSession) -> dict | None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == CACHE_KEY))
    setting = result.scalar_one_or_none()
    return json.loads(setting.value) if setting else None


async def _write_cache(db: AsyncSession, data: dict) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == CACHE_KEY))
    setting = result.scalar_one_or_none()
    value = json.dumps(data)
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=CACHE_KEY, value=value))
    await db.commit()


async def _fetch_latest_release() -> tuple[str, str]:
    """Returns (version_without_v_prefix, release_url). Raises on any failure — callers
    decide how to degrade (see run_github_update_check)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GITHUB_RELEASES_URL, timeout=10.0, headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()
    return data["tag_name"].lstrip("v"), data["html_url"]


async def compute_github_update_status(db: AsyncSession) -> dict:
    """Backs GET /api/admin/github-update-status. current_version is always read live (never
    cached) so an upgrade is reflected immediately, not just after the next scheduled check."""
    cached = await _read_cache(db)
    current_version = get_current_version()

    if not cached or not cached.get("latest_version"):
        error = cached.get("error") if cached else None
        return {
            "status": "error" if error else "never",
            "current_version": current_version,
            "latest_version": None,
            "release_url": None,
            "checked_at": cached.get("checked_at") if cached else None,
            "error": error,
        }

    current_tuple = _parse_semver(current_version)
    latest_tuple = _parse_semver(cached["latest_version"])
    if current_tuple is None or latest_tuple is None:
        status = "error"
        error = f"Cannot compare versions: current={current_version!r}, latest={cached['latest_version']!r}"
    else:
        status = "update_available" if latest_tuple > current_tuple else "up_to_date"
        error = None

    return {
        "status": status,
        "current_version": current_version,
        "latest_version": cached["latest_version"],
        "release_url": cached["release_url"],
        "checked_at": cached["checked_at"],
        "error": error,
    }


async def run_github_update_check() -> None:
    """Scheduled every 6h by app/tasks/pgq_app.py. Opens its own engine/session per call —
    same pattern as app/tasks/prices.py's _run_price_refresh, needed because a PgQueuer
    schedule handler runs inside the worker's own persistent event loop."""
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            cached = await _read_cache(db) or {}
            checked_at = datetime.now(timezone.utc).isoformat()
            try:
                latest_version, release_url = await _fetch_latest_release()
            except Exception as exc:
                cached.setdefault("latest_version", None)
                cached.setdefault("release_url", None)
                cached["error"] = str(exc)[:200]
                cached["checked_at"] = checked_at
                await _write_cache(db, cached)
                return
            cached.update({
                "latest_version": latest_version,
                "release_url": release_url,
                "checked_at": checked_at,
                "error": None,
            })
            await _write_cache(db, cached)
    finally:
        await eng.dispose()
