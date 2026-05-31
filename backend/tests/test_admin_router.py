"""
Tests for /api/admin — backup, restore, and task-status endpoints.

Safety guarantee
----------------
All backup and restore tests mock subprocess.run so that pg_dump and psql
are NEVER called against any real database. The production database (ude_db)
is completely untouched by this test suite.

Task-status tests mock celery.result.AsyncResult to cover all five state
branches without requiring a live Celery broker.
"""

import io
import json
import subprocess
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app as fastapi_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dump_file(content: str | bytes, filename: str = "backup.dump"):
    if isinstance(content, str):
        content = content.encode()
    return ("file", (filename, io.BytesIO(content), "application/octet-stream"))


def _sql_file(content: str | bytes, filename: str = "backup.sql"):
    """Build an in-memory upload file for the restore endpoint."""
    if isinstance(content, str):
        content = content.encode()
    return ("file", (filename, io.BytesIO(content), "application/sql"))


def _make_proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a mock CompletedProcess returned by subprocess.run."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _client():
    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test")


# ---------------------------------------------------------------------------
# Backup — GET /backup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backup_returns_sql_from_pg_dump():
    """
    GET /backup calls pg_dump subprocess and streams its stdout.
    subprocess.run is mocked → pg_dump never runs, production DB is safe.
    """
    fake_sql = b"-- pg_dump backup\nDROP TABLE IF EXISTS transactions;\nCREATE TABLE transactions ();\n"
    mock_proc = _make_proc(stdout=fake_sql)

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc) as mock_run:
        async with _client() as client:
            r = await client.get("/api/admin/backup")

    assert r.status_code == 200
    assert "application/octet-stream" in r.headers["content-type"]
    assert b"pg_dump backup" in r.content
    # Verify pg_dump was called with expected flags
    call_args = mock_run.call_args[0][0]
    assert "pg_dump" in call_args
    assert "--format=custom" in call_args


@pytest.mark.asyncio
async def test_backup_pg_dump_failure_returns_500():
    """pg_dump returncode != 0 → 500 with stderr detail."""
    mock_proc = _make_proc(returncode=1, stderr=b"pg_dump: connection refused")

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc):
        async with _client() as client:
            r = await client.get("/api/admin/backup")

    assert r.status_code == 500
    assert "pg_dump" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_backup_content_disposition_header():
    """Response carries a Content-Disposition attachment header with .dump filename."""
    mock_proc = _make_proc(stdout=b"-- backup\n")

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc):
        async with _client() as client:
            r = await client.get("/api/admin/backup")

    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".dump" in cd


# ---------------------------------------------------------------------------
# Restore — input validation (subprocess never reached)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_wrong_extension_returns_400():
    """Non-.dump file extension → 400 before subprocess is called."""
    with patch("app.api.routers.admin.subprocess.run") as mock_run:
        async with _client() as client:
            r = await client.post(
                "/api/admin/restore",
                files=[_dump_file(b"SELECT 1;" * 20, filename="backup.csv")],
            )
    assert r.status_code == 400
    assert "dump" in r.json()["detail"].lower()
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_restore_file_too_small_returns_400():
    """File smaller than 100 bytes → 400 before subprocess is called."""
    with patch("app.api.routers.admin.subprocess.run") as mock_run:
        async with _client() as client:
            r = await client.post(
                "/api/admin/restore",
                files=[_dump_file(b"SELECT 1;", filename="backup.dump")],
            )
    assert r.status_code == 400
    assert "petit" in r.json()["detail"].lower() or "vide" in r.json()["detail"].lower()
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Restore — success path (psql mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_valid_sql_calls_psql_and_returns_200():
    """
    Valid .sql file → psql subprocess called with --single-transaction,
    returncode=0 → 200 ok.
    subprocess.run is mocked → psql never runs, production DB is safe.
    """
    sql = b"-- pg_dump backup\n" + b"DROP TABLE IF EXISTS t;\n" * 10  # > 100 bytes
    mock_proc = _make_proc(returncode=0)

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc) as mock_run:
        async with _client() as client:
            r = await client.post("/api/admin/restore", files=[_dump_file(sql)])

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "successfully" in body["message"]

    # Verify pg_restore was called without --single-transaction (incompatible pg_dump v17 / PG16)
    call_args = mock_run.call_args[0][0]
    assert "pg_restore" in call_args
    assert "--single-transaction" not in call_args
    assert "--clean" in call_args


@pytest.mark.asyncio
async def test_restore_psql_failure_returns_500():
    """psql returncode != 0 → 500, stderr included in detail."""
    sql = b"-- backup\n" + b"x" * 120
    mock_proc = _make_proc(returncode=1, stderr=b"ERROR: relation does not exist")

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc):
        async with _client() as client:
            r = await client.post("/api/admin/restore", files=[_dump_file(sql)])

    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "restore failed" in detail.lower() or "rollback" in detail.lower()


@pytest.mark.asyncio
async def test_restore_stderr_truncated_to_400_chars():
    """Long psql stderr is truncated to ≤500 chars in the response detail."""
    sql = b"-- backup\n" + b"x" * 120
    mock_proc = _make_proc(returncode=1, stderr=b"E" * 600)

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc):
        async with _client() as client:
            r = await client.post("/api/admin/restore", files=[_dump_file(sql)])

    assert r.status_code == 500
    assert len(r.json()["detail"]) <= 500


@pytest.mark.asyncio
async def test_restore_transaction_timeout_only_returns_200():
    """returncode!=0 but only error is transaction_timeout → success (PG16 compat)."""
    sql = b"-- backup\n" + b"x" * 120
    stderr = (
        b"pg_restore: error: could not execute query: ERROR: "
        b"unrecognized configuration parameter \"transaction_timeout\"\n"
        b"Command was: SET transaction_timeout = 0;\n"
    )
    mock_proc = _make_proc(returncode=1, stderr=stderr)

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc):
        async with _client() as client:
            r = await client.post("/api/admin/restore", files=[_dump_file(sql)])

    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_restore_temp_file_cleaned_up_on_success():
    """Temp file is deleted after psql runs (success path)."""
    sql = b"-- backup\n" + b"x" * 120
    mock_proc = _make_proc(returncode=0)
    deleted_files: list[str] = []

    real_unlink = __import__("os").unlink

    def capture_unlink(path: str):
        deleted_files.append(path)
        real_unlink(path)

    with patch("app.api.routers.admin.subprocess.run", return_value=mock_proc), \
         patch("app.api.routers.admin.os.unlink", side_effect=capture_unlink):
        async with _client() as client:
            await client.post("/api/admin/restore", files=[_dump_file(sql)])

    assert len(deleted_files) == 1
    assert deleted_files[0].endswith(".dump")


# ---------------------------------------------------------------------------
# Task status — all 5 Celery state branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_status_pending():
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/abc-123")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "PENDING"
    assert body["current"] == 0
    assert body["error"] is None


@pytest.mark.asyncio
async def test_task_status_progress_with_meta():
    mock_result = MagicMock()
    mock_result.state = "PROGRESS"
    mock_result.info = {"current": 3, "total": 10, "date": "2026-05-16"}
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/xyz-456")
    body = r.json()
    assert body["state"] == "PROGRESS"
    assert body["current"] == 3
    assert body["total"] == 10
    assert body["date"] == "2026-05-16"


@pytest.mark.asyncio
async def test_task_status_progress_no_meta():
    mock_result = MagicMock()
    mock_result.state = "PROGRESS"
    mock_result.info = None
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/xyz-000")
    body = r.json()
    assert body["state"] == "PROGRESS"
    assert body["current"] == 0
    assert body["date"] is None


@pytest.mark.asyncio
async def test_task_status_success():
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/done-789")
    body = r.json()
    assert body["state"] == "SUCCESS"
    assert body["current"] == 1
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_task_status_failure_with_error():
    mock_result = MagicMock()
    mock_result.state = "FAILURE"
    mock_result.info = ValueError("something went wrong")
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/fail-111")
    body = r.json()
    assert body["state"] == "FAILURE"
    assert "something went wrong" in body["error"]


@pytest.mark.asyncio
async def test_task_status_unknown_state_passthrough():
    mock_result = MagicMock()
    mock_result.state = "REVOKED"
    with patch("app.api.routers.admin.AsyncResult", return_value=mock_result):
        async with _client() as client:
            r = await client.get("/api/admin/task/rev-222")
    body = r.json()
    assert body["state"] == "REVOKED"
    assert body["current"] == 0
    assert body["error"] is None


# ---------------------------------------------------------------------------
# Celery dispatch endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_prices_dispatches_celery_task():
    mock_task = MagicMock()
    mock_task.id = "price-task-abc"
    with patch("app.tasks.prices.refresh_prices_live") as mock_live:
        mock_live.delay.return_value = mock_task
        async with _client() as client:
            r = await client.post("/api/admin/refresh-prices")
    assert r.status_code == 200
    assert r.json()["task_id"] == "price-task-abc"
    mock_live.delay.assert_called_once()


@pytest.mark.asyncio
async def test_fill_missing_snapshots_dispatches_celery_task():
    mock_task = MagicMock()
    mock_task.id = "fill-task-xyz"
    with patch("app.tasks.snapshots.fill_missing_snapshots") as mock_fill:
        mock_fill.delay.return_value = mock_task
        async with _client() as client:
            r = await client.post("/api/admin/fill-missing-snapshots")
    assert r.status_code == 200
    assert r.json()["task_id"] == "fill-task-xyz"
    mock_fill.delay.assert_called_once()


@pytest.mark.asyncio
async def test_recompute_snapshots_valid_range():
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=10)).isoformat()
    end = (date.today() - timedelta(days=1)).isoformat()
    mock_task = MagicMock()
    mock_task.id = "recompute-task-1"
    with patch("app.api.routers.admin.recompute_snapshots_range") as mock_rc:
        mock_rc.delay.return_value = mock_task
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": start, "end_date": end})
    assert r.status_code == 200
    assert r.json()["task_id"] == "recompute-task-1"
    mock_rc.delay.assert_called_once_with(start, end)


@pytest.mark.asyncio
async def test_recompute_snapshots_end_exceeds_yesterday_returns_400():
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=1)).isoformat()
    async with _client() as client:
        r = await client.post("/api/admin/recompute-snapshots",
                              json={"start_date": "2025-01-01", "end_date": future})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_recompute_snapshots_start_after_end_returns_400():
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    async with _client() as client:
        r = await client.post("/api/admin/recompute-snapshots",
                              json={"start_date": yesterday, "end_date": "2020-01-01"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_recompute_snapshots_no_end_date_defaults_to_yesterday():
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=7)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    mock_task = MagicMock()
    mock_task.id = "recompute-default"
    with patch("app.api.routers.admin.recompute_snapshots_range") as mock_rc:
        mock_rc.delay.return_value = mock_task
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": start})
    assert r.status_code == 200
    mock_rc.delay.assert_called_once_with(start, yesterday)


# ---------------------------------------------------------------------------
# Sync status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_status_never_synced():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with patch("redis.Redis.from_url", return_value=mock_redis):
        async with _client() as client:
            r = await client.get("/api/admin/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync():
    payload = {
        "status": "partial",
        "started_at": "2026-05-16T10:00:00Z",
        "finished_at": "2026-05-16T10:00:05Z",
        "total_tickers": 5,
        "succeeded": 3,
        "failed_tickers": ["X.PA", "Y.DE"],
    }
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(payload)
    with patch("redis.Redis.from_url", return_value=mock_redis):
        async with _client() as client:
            r = await client.get("/api/admin/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "partial"
    assert body["failed_tickers"] == ["X.PA", "Y.DE"]


# ---------------------------------------------------------------------------
# Version — GET /api/admin/version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_version_endpoint():
    """GET /api/admin/version retourne un objet avec version (fallback dev)."""
    async with _client() as client:
        r = await client.get("/api/admin/version")
    assert r.status_code == 200
    assert "version" in r.json()


@pytest.mark.asyncio
async def test_version_endpoint_from_env():
    """GET /api/admin/version returns the version from APP_VERSION env var if set."""
    with patch.dict("os.environ", {"APP_VERSION": "1.2.3"}):
        async with _client() as client:
            r = await client.get("/api/admin/version")
    assert r.status_code == 200
    assert r.json()["version"] == "1.2.3"


# ---------------------------------------------------------------------------
# System settings — GET /PUT /DELETE /api/admin/settings/{key}
# ---------------------------------------------------------------------------

def _make_async_db(scalar_return=None):
    """Build an AsyncMock DB session for settings endpoint tests."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_return
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()  # add is synchronous
    return mock_db


@pytest.mark.asyncio
async def test_get_setting_not_found_returns_404():
    """GET /settings/{key} → 404 when key does not exist in DB."""
    from app.core.database import get_db
    from app.main import app as fastapi_app

    mock_db = _make_async_db(scalar_return=None)

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.get("/api/admin/settings/nonexistent_key")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_setting_found_returns_key_value():
    """GET /settings/{key} → returns key and value when setting exists."""
    from app.models.system_setting import SystemSetting
    from app.core.database import get_db
    from app.main import app as fastapi_app

    setting = SystemSetting(key="github_api_token", value="ghp_test123")
    mock_db = _make_async_db(scalar_return=setting)

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.get("/api/admin/settings/github_api_token")
        assert r.status_code == 200
        body = r.json()
        assert body["key"] == "github_api_token"
        assert body["value"] == "ghp_test123"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_put_setting_creates_new_setting():
    """PUT /settings/{key} → creates setting when it doesn't exist yet."""
    from app.core.database import get_db
    from app.main import app as fastapi_app

    mock_db = _make_async_db(scalar_return=None)  # not found → create

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.put("/api/admin/settings/github_api_token",
                                 json={"value": "ghp_new_token"})
        assert r.status_code == 200
        body = r.json()
        assert body["key"] == "github_api_token"
        assert body["value"] == "ghp_new_token"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_put_setting_updates_existing_setting():
    """PUT /settings/{key} → updates value when setting already exists."""
    from app.models.system_setting import SystemSetting
    from app.core.database import get_db
    from app.main import app as fastapi_app

    existing = SystemSetting(key="github_api_token", value="ghp_old_token")
    mock_db = _make_async_db(scalar_return=existing)

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.put("/api/admin/settings/github_api_token",
                                 json={"value": "ghp_updated_token"})
        assert r.status_code == 200
        body = r.json()
        assert body["value"] == "ghp_updated_token"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_delete_setting_removes_existing_setting():
    """DELETE /settings/{key} → 204 when setting exists and is deleted."""
    from app.models.system_setting import SystemSetting
    from app.core.database import get_db
    from app.main import app as fastapi_app

    existing = SystemSetting(key="github_api_token", value="ghp_token")
    mock_db = _make_async_db(scalar_return=existing)

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.delete("/api/admin/settings/github_api_token")
        assert r.status_code == 204
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_delete_setting_nonexistent_returns_204():
    """DELETE /settings/{key} → 204 (no-op) when setting does not exist."""
    from app.core.database import get_db
    from app.main import app as fastapi_app

    mock_db = _make_async_db(scalar_return=None)

    async def override_get_db():
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with _client() as client:
            r = await client.delete("/api/admin/settings/nonexistent_key")
        assert r.status_code == 204
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
