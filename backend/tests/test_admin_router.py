"""
Tests for /api/admin — backup, restore, and task-status endpoints.

Safety guarantee
----------------
All backup and restore tests mock subprocess.run so that pg_dump and psql
are NEVER called against any real database. The production database (ude_db)
is completely untouched by this test suite.

All 6 background tasks now go through PgQueuer/job_runs (issue #66 steps 3+4) — task-status
tests mock app.tasks.job_runs.get_by_id directly rather than celery.result.AsyncResult; the
exhaustive 5-row state-mapping table itself is unit-tested directly in test_job_runs.py
(to_task_status_dict), so only representative router-integration cases live here.
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
# Task status — job_runs-backed (issue #66 step 4); see test_job_runs.py's
# to_task_status_dict tests for the exhaustive 5-row mapping-table coverage.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_status_unknown_id_returns_pending():
    with patch("app.tasks.job_runs.get_by_id", new_callable=AsyncMock, return_value=None):
        async with _client() as client:
            r = await client.get("/api/admin/task/123")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "PENDING"
    assert body["current"] == 0
    assert body["error"] is None


@pytest.mark.asyncio
async def test_task_status_progress():
    fake_run = MagicMock()
    fake_run.status = "running"
    fake_run.current_step = 3
    fake_run.total_steps = 10
    fake_run.current_label = "2026-05-16"
    with patch("app.tasks.job_runs.get_by_id", new_callable=AsyncMock, return_value=fake_run):
        async with _client() as client:
            r = await client.get("/api/admin/task/456")
    body = r.json()
    assert body["state"] == "PROGRESS"
    assert body["current"] == 3
    assert body["total"] == 10
    assert body["date"] == "2026-05-16"


@pytest.mark.asyncio
async def test_task_status_success():
    fake_run = MagicMock()
    fake_run.status = "success"
    fake_run.total_steps = 8
    fake_run.current_label = "2026-05-20"
    with patch("app.tasks.job_runs.get_by_id", new_callable=AsyncMock, return_value=fake_run):
        async with _client() as client:
            r = await client.get("/api/admin/task/789")
    body = r.json()
    assert body["state"] == "SUCCESS"
    assert body["current"] == 8
    assert body["total"] == 8


@pytest.mark.asyncio
async def test_task_status_failure_with_error():
    fake_run = MagicMock()
    fake_run.status = "failed"
    fake_run.current_step = 2
    fake_run.total_steps = 10
    fake_run.current_label = "2026-05-17"
    fake_run.error = "something went wrong"
    with patch("app.tasks.job_runs.get_by_id", new_callable=AsyncMock, return_value=fake_run):
        async with _client() as client:
            r = await client.get("/api/admin/task/111")
    body = r.json()
    assert body["state"] == "FAILURE"
    assert body["error"] == "something went wrong"


@pytest.mark.asyncio
async def test_task_status_malformed_id_returns_404():
    """task_id must parse as an int (job_runs.id) — a non-numeric id (e.g. a stale Celery
    UUID from before this endpoint's cutover) is a clean 404, not a 500."""
    async with _client() as client:
        r = await client.get("/api/admin/task/not-a-number")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PgQueuer dispatch endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_prices_dispatches_via_pgqueuer():
    from app.core.pgq import get_pgq_queries

    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[42])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/refresh-prices")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json()["job_id"] == 42
    mock_queries.enqueue.assert_called_once_with("refresh_prices_live", payload=b"on_demand")


@pytest.mark.asyncio
async def test_fill_missing_snapshots_dispatches_via_pgqueuer():
    from app.core.pgq import get_pgq_queries

    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[7])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/fill-missing-snapshots")
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    assert r.json()["task_id"] == "7"
    mock_queries.enqueue.assert_called_once_with("fill_missing_snapshots", payload=b"on_demand")


@pytest.mark.asyncio
async def test_recompute_snapshots_valid_range():
    from datetime import date, timedelta
    from app.core.pgq import get_pgq_queries

    start = (date.today() - timedelta(days=10)).isoformat()
    end = (date.today() - timedelta(days=1)).isoformat()

    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[1])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": start, "end_date": end})
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert task_id.isdigit()

    mock_queries.enqueue.assert_called_once()
    call_args = mock_queries.enqueue.call_args
    assert call_args[0][0] == "recompute_snapshots_range"
    payload = json.loads(call_args.kwargs["payload"])
    assert payload == {"start": start, "end": end, "run_id": int(task_id)}


@pytest.mark.asyncio
async def test_recompute_snapshots_end_exceeds_yesterday_returns_400():
    from datetime import date, timedelta
    from app.core.pgq import get_pgq_queries

    future = (date.today() + timedelta(days=1)).isoformat()
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[1])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": "2025-01-01", "end_date": future})
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)
    assert r.status_code == 400
    mock_queries.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_recompute_snapshots_start_after_end_returns_400():
    from datetime import date, timedelta
    from app.core.pgq import get_pgq_queries

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[1])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": yesterday, "end_date": "2020-01-01"})
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)
    assert r.status_code == 400
    mock_queries.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_recompute_snapshots_no_end_date_defaults_to_yesterday():
    from datetime import date, timedelta
    from app.core.pgq import get_pgq_queries

    start = (date.today() - timedelta(days=7)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(return_value=[2])

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": start})
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 200
    payload = json.loads(mock_queries.enqueue.call_args.kwargs["payload"])
    assert payload["start"] == start
    assert payload["end"] == yesterday


@pytest.mark.asyncio
async def test_recompute_snapshots_enqueue_failure_marks_run_failed_and_503():
    from datetime import date, timedelta
    from app.core.pgq import get_pgq_queries
    from app.tasks import job_runs

    start = (date.today() - timedelta(days=3)).isoformat()
    end = (date.today() - timedelta(days=1)).isoformat()

    mock_queries = MagicMock()
    mock_queries.enqueue = AsyncMock(side_effect=RuntimeError("queue unavailable"))

    fastapi_app.dependency_overrides[get_pgq_queries] = lambda: mock_queries
    try:
        async with _client() as client:
            r = await client.post("/api/admin/recompute-snapshots",
                                  json={"start_date": start, "end_date": end})
    finally:
        fastapi_app.dependency_overrides.pop(get_pgq_queries, None)

    assert r.status_code == 503
    # The run_id created before the failed enqueue must be marked failed, not left
    # orphaned "running" forever for a job that was never actually queued.
    run = await job_runs.get_latest("recompute_snapshots_range")
    assert run is not None
    assert run.status == "failed"


# ---------------------------------------------------------------------------
# Sync status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_status_never_synced():
    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=None):
        async with _client() as client:
            r = await client.get("/api/admin/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "never"
    assert body["failed_tickers"] == []


@pytest.mark.asyncio
async def test_sync_status_returns_last_sync():
    from datetime import datetime

    fake_run = MagicMock()
    fake_run.status = "partial"
    fake_run.started_at = datetime(2026, 5, 16, 10, 0, 0)
    fake_run.finished_at = datetime(2026, 5, 16, 10, 0, 5)
    fake_run.total_steps = 5
    fake_run.succeeded_steps = 3
    fake_run.failed_items = ["X.PA", "Y.DE"]

    with patch("app.tasks.job_runs.get_latest", new_callable=AsyncMock, return_value=fake_run):
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
async def test_version_endpoint_fallback_unknown():
    """GET /api/admin/version returns UNKNOWN when no version env var is set."""
    with patch.dict("os.environ", {}, clear=False):
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("INSTALLER_VERSION", "APP_VERSION")}
        with patch.dict("os.environ", env, clear=True):
            async with _client() as client:
                r = await client.get("/api/admin/version")
    assert r.status_code == 200
    assert r.json()["version"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_version_endpoint_installer_version_takes_priority():
    """INSTALLER_VERSION takes priority over APP_VERSION."""
    with patch.dict("os.environ", {"INSTALLER_VERSION": "1.0.6", "APP_VERSION": "1.0.0"}):
        async with _client() as client:
            r = await client.get("/api/admin/version")
    assert r.status_code == 200
    assert r.json()["version"] == "1.0.6"


@pytest.mark.asyncio
async def test_version_endpoint_from_app_version_fallback():
    """Falls back to APP_VERSION when INSTALLER_VERSION is not set."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "INSTALLER_VERSION"}
    with patch.dict("os.environ", {**env, "APP_VERSION": "1.2.3"}, clear=True):
        async with _client() as client:
            r = await client.get("/api/admin/version")
    assert r.status_code == 200
    assert r.json()["version"] == "1.2.3"


# ---------------------------------------------------------------------------
# Health — GET /api/admin/health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_ok():
    """GET /api/admin/health returns 200 when DB executes successfully."""
    from app.core.database import get_db

    async def working_db():
        mock = AsyncMock()
        mock.execute.return_value = MagicMock()
        yield mock

    fastapi_app.dependency_overrides[get_db] = working_db
    try:
        async with _client() as c:
            r = await c.get("/api/admin/health")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_health_db_unavailable():
    """GET /api/admin/health returns 503 when DB raises."""
    from app.core.database import get_db

    async def broken_db():
        mock = AsyncMock()
        mock.execute.side_effect = Exception("DB unavailable")
        yield mock

    fastapi_app.dependency_overrides[get_db] = broken_db
    try:
        async with _client() as c:
            r = await c.get("/api/admin/health")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 503
    assert r.json()["detail"] == "Database unavailable"


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
