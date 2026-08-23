# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for app/tasks/github_update.py (issue #113).

_read_cache/_write_cache/compute_github_update_status take an explicit `db` and are tested
with a lightweight AsyncMock session — the same pattern already used for the generic settings
CRUD endpoints in test_admin_router.py (system_settings is a plain key/value table either way).
run_github_update_check opens its own engine/session per call (mirrors app/tasks/prices.py's
_run_price_refresh) and is tested with the engine/session-factory mock pattern from
test_macro_indicators_task.py, plus a mocked httpx.AsyncClient for the GitHub API call itself
— no real network access, no real database.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.system_setting import SystemSetting
from app.tasks.github_update import (
    CACHE_KEY,
    _fetch_latest_release,
    _parse_semver,
    _read_cache,
    _write_cache,
    compute_github_update_status,
    get_current_version,
    run_github_update_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=MagicMock(), response=self)

    def json(self):
        return self._body


def _make_async_db(scalar_return=None):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_return
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()
    return mock_db


def _make_httpx_mock(response):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_httpx


def _make_engine_mocks(db):
    session_instance = AsyncMock()
    session_instance.__aenter__ = AsyncMock(return_value=db)
    session_instance.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session_instance)

    mock_eng = MagicMock()
    mock_eng.dispose = AsyncMock()
    return mock_eng, session_factory


# ---------------------------------------------------------------------------
# get_current_version / _parse_semver
# ---------------------------------------------------------------------------

def test_get_current_version_prefers_installer_version(monkeypatch):
    monkeypatch.setenv("INSTALLER_VERSION", "1.4.6")
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    assert get_current_version() == "1.4.6"


def test_get_current_version_falls_back_to_app_version(monkeypatch):
    monkeypatch.delenv("INSTALLER_VERSION", raising=False)
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    assert get_current_version() == "1.2.3"


def test_get_current_version_falls_back_to_unknown(monkeypatch):
    monkeypatch.delenv("INSTALLER_VERSION", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert get_current_version() == "UNKNOWN"


@pytest.mark.parametrize("value, expected", [
    ("1.4.6", (1, 4, 6)),
    ("v1.4.6", (1, 4, 6)),
    ("v1.4.6-rc1", (1, 4, 6)),
    ("0.1.0", (0, 1, 0)),
])
def test_parse_semver_valid(value, expected):
    assert _parse_semver(value) == expected


@pytest.mark.parametrize("value", ["UNKNOWN", "dev", "", "v1.4", "not-a-version"])
def test_parse_semver_invalid_returns_none(value):
    assert _parse_semver(value) is None


# ---------------------------------------------------------------------------
# _read_cache / _write_cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_cache_returns_none_when_no_row():
    db = _make_async_db(scalar_return=None)
    assert await _read_cache(db) is None


@pytest.mark.asyncio
async def test_read_cache_parses_json_value():
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps({"latest_version": "1.4.6"}))
    db = _make_async_db(scalar_return=setting)
    assert await _read_cache(db) == {"latest_version": "1.4.6"}


@pytest.mark.asyncio
async def test_write_cache_creates_new_row_when_absent():
    db = _make_async_db(scalar_return=None)
    await _write_cache(db, {"latest_version": "1.4.6"})
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.key == CACHE_KEY
    assert json.loads(added.value) == {"latest_version": "1.4.6"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_cache_updates_existing_row():
    existing = SystemSetting(key=CACHE_KEY, value=json.dumps({"latest_version": "1.0.0"}))
    db = _make_async_db(scalar_return=existing)
    await _write_cache(db, {"latest_version": "1.4.6"})
    db.add.assert_not_called()
    assert json.loads(existing.value) == {"latest_version": "1.4.6"}
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# compute_github_update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_status_never_checked(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.4.6")
    db = _make_async_db(scalar_return=None)
    result = await compute_github_update_status(db)
    assert result == {
        "status": "never", "current_version": "1.4.6", "latest_version": None,
        "release_url": None, "checked_at": None, "error": None,
    }


@pytest.mark.asyncio
async def test_compute_status_error_when_only_failed_checks_ever_happened(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.4.6")
    cached = {"latest_version": None, "release_url": None, "checked_at": "2026-08-18T00:00:00+00:00",
              "error": "network down"}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "error"
    assert result["error"] == "network down"
    assert result["checked_at"] == "2026-08-18T00:00:00+00:00"


@pytest.mark.asyncio
async def test_compute_status_up_to_date(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.4.6")
    cached = {"latest_version": "1.4.6", "release_url": "https://github.com/x/releases/tag/v1.4.6",
              "checked_at": "2026-08-18T00:00:00+00:00", "error": None}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "up_to_date"
    assert result["current_version"] == "1.4.6"
    assert result["latest_version"] == "1.4.6"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_compute_status_update_available(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.4.2")
    cached = {"latest_version": "1.4.6", "release_url": "https://github.com/x/releases/tag/v1.4.6",
              "checked_at": "2026-08-18T00:00:00+00:00", "error": None}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "update_available"


@pytest.mark.asyncio
async def test_compute_status_current_ahead_of_latest_is_up_to_date(monkeypatch):
    """A dev/pre-release build ahead of the last tagged release has nothing to update to."""
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    cached = {"latest_version": "1.4.6", "release_url": "https://github.com/x/releases/tag/v1.4.6",
              "checked_at": "2026-08-18T00:00:00+00:00", "error": None}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "up_to_date"


@pytest.mark.asyncio
async def test_compute_status_unparseable_current_version_is_error(monkeypatch):
    monkeypatch.delenv("INSTALLER_VERSION", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)  # → "UNKNOWN", unparseable
    cached = {"latest_version": "1.4.6", "release_url": "https://github.com/x/releases/tag/v1.4.6",
              "checked_at": "2026-08-18T00:00:00+00:00", "error": None}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "error"
    assert "UNKNOWN" in result["error"]


@pytest.mark.asyncio
async def test_compute_status_ignores_stale_error_once_a_latest_version_is_cached(monkeypatch):
    """A transient failure after an earlier success must not regress the reported status —
    see run_github_update_check's own docstring for why the error field is layered on top of,
    not instead of, the last successful latest_version/release_url."""
    monkeypatch.setenv("APP_VERSION", "1.4.6")
    cached = {"latest_version": "1.4.6", "release_url": "https://github.com/x/releases/tag/v1.4.6",
              "checked_at": "2026-08-18T00:00:00+00:00", "error": "timeout on a later, unrelated tick"}
    setting = SystemSetting(key=CACHE_KEY, value=json.dumps(cached))
    db = _make_async_db(scalar_return=setting)
    result = await compute_github_update_status(db)
    assert result["status"] == "up_to_date"
    assert result["error"] is None


# ---------------------------------------------------------------------------
# _fetch_latest_release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_latest_release_strips_v_prefix_and_returns_html_url():
    response = _FakeResponse(200, {"tag_name": "v1.4.6", "html_url": "https://github.com/x/releases/tag/v1.4.6"})
    with patch("app.tasks.github_update.httpx", _make_httpx_mock(response)):
        version, url = await _fetch_latest_release()
    assert version == "1.4.6"
    assert url == "https://github.com/x/releases/tag/v1.4.6"


@pytest.mark.asyncio
async def test_fetch_latest_release_raises_on_http_error():
    response = _FakeResponse(404)
    with patch("app.tasks.github_update.httpx", _make_httpx_mock(response)):
        with pytest.raises(Exception):
            await _fetch_latest_release()


# ---------------------------------------------------------------------------
# run_github_update_check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_check_success_writes_cache(monkeypatch):
    db = _make_async_db(scalar_return=None)
    mock_eng, session_factory = _make_engine_mocks(db)
    response = _FakeResponse(200, {"tag_name": "v1.4.6", "html_url": "https://github.com/x/releases/tag/v1.4.6"})

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.github_update.httpx", _make_httpx_mock(response)):
        await run_github_update_check()

    db.add.assert_called_once()
    written = json.loads(db.add.call_args[0][0].value)
    assert written["latest_version"] == "1.4.6"
    assert written["error"] is None
    mock_eng.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_check_failure_with_no_prior_cache_records_error_only():
    db = _make_async_db(scalar_return=None)
    mock_eng, session_factory = _make_engine_mocks(db)
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("network down"))
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.github_update.httpx", mock_httpx):
        await run_github_update_check()

    written = json.loads(db.add.call_args[0][0].value)
    assert written["latest_version"] is None
    assert "network down" in written["error"]
    mock_eng.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_check_failure_after_prior_success_preserves_last_good_result():
    prior = {"latest_version": "1.4.2", "release_url": "https://github.com/x/releases/tag/v1.4.2",
             "checked_at": "2026-08-01T00:00:00+00:00", "error": None}
    existing = SystemSetting(key=CACHE_KEY, value=json.dumps(prior))
    db = _make_async_db(scalar_return=existing)
    mock_eng, session_factory = _make_engine_mocks(db)
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("timeout"))
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.github_update.httpx", mock_httpx):
        await run_github_update_check()

    written = json.loads(existing.value)
    assert written["latest_version"] == "1.4.2"  # preserved, not clobbered
    assert written["release_url"] == "https://github.com/x/releases/tag/v1.4.2"
    assert "timeout" in written["error"]
    mock_eng.dispose.assert_awaited_once()
