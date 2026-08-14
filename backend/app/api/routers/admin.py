from __future__ import annotations
import json
import os
import subprocess
import tempfile
from datetime import date, timedelta, datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pgqueuer import Queries
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks import job_runs
from app.core.config import settings
from app.core.database import get_db
from app.core.pgq import get_pgq_queries

router = APIRouter(tags=["admin"])


def yesterday() -> date:
    return date.today() - timedelta(days=1)


def _pg_conn_args() -> tuple[list[str], dict[str, str]]:
    """Parse DATABASE_URL → (psql/pg_dump connection args, env with PGPASSWORD)."""
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    p = urlparse(url)
    args = [
        "-h", p.hostname or "localhost",
        "-p", str(p.port or 5432),
        "-U", p.username or "pie",
        "-d", (p.path or "/pie_db").lstrip("/"),
    ]
    env = os.environ.copy()
    env["PGPASSWORD"] = p.password or ""
    return args, env


# ── Backup — pg_dump custom format (binary, compressed) ───────────────────

@router.get("/backup")
async def download_backup():
    """Full pg_dump backup in custom binary format (.dump) — compressed, fast restore."""
    conn_args, env = _pg_conn_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"pie_backup_{timestamp}.dump"

    result = subprocess.run(
        ["pg_dump", *conn_args,
         "--format=custom",
         "--no-owner", "--no-privileges"],
        capture_output=True, env=env,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"pg_dump failed: {result.stderr.decode()[:400]}",
        )
    return StreamingResponse(
        iter([result.stdout]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Restore — pg_restore --single-transaction ──────────────────────────────

@router.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    """
    Restore a pg_dump custom-format backup via pg_restore.
    Uses --clean --if-exists to wipe and recreate all objects, then
    --single-transaction to roll back everything if any error occurs.
    """
    if not file.filename or not file.filename.endswith(".dump"):
        raise HTTPException(status_code=400, detail="Fichier .dump requis")

    sql_bytes = await file.read()
    if len(sql_bytes) < 100:
        raise HTTPException(status_code=400, detail="Fichier trop petit ou vide")

    conn_args, env = _pg_conn_args()

    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
        tmp.write(sql_bytes)
        tmpfile = tmp.name

    try:
        result = subprocess.run(
            ["pg_restore", *conn_args,
             "--clean", "--if-exists", "--no-owner", "--no-privileges",
             # No --single-transaction: pg_dump v17 injects SET transaction_timeout
             # which PostgreSQL 16 does not recognise. Without --single-transaction,
             # pg_restore continues despite this non-critical error.
             tmpfile],
            capture_output=True, env=env,
        )
    finally:
        os.unlink(tmpfile)

    if result.returncode != 0:
        stderr_text = result.stderr.decode()
        error_lines = [line for line in stderr_text.splitlines() if "error:" in line.lower()]
        critical = [line for line in error_lines if "transaction_timeout" not in line]
        # Fatal if: critical errors OR non-empty stderr with no known "error:" lines
        if critical or (not error_lines and stderr_text.strip()):
            raise HTTPException(
                status_code=500,
                detail=f"Restore failed: {chr(10).join((critical or [stderr_text[:400]])[:5])}",
            )
        # Otherwise: only transaction_timeout (non-critical on PG16) → success
    return {"status": "ok", "message": "Restore completed successfully."}


# ── Snapshot recomputation ─────────────────────────────────────────────────

class RecomputeRequest(BaseModel):
    start_date: date
    end_date: Optional[date] = None


class TaskStatus(BaseModel):
    task_id: str
    state: str
    current: int = 0
    total: int = 0
    date: Optional[str] = None
    error: Optional[str] = None


@router.post("/refresh-prices", response_model=dict)
async def refresh_prices(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual price refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_prices_live", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued", "date": date.today().isoformat()}


@router.get("/sync-status")
async def get_sync_status():
    """Return the last price sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_prices_live")
    return job_runs.to_sync_status_dict(run)


@router.post("/fill-missing-snapshots", response_model=dict)
async def fill_missing_snapshots_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger fill of all missing daily snapshots up to yesterday.
    Called automatically on startup and at midnight by the frontend — fire-and-forget, never
    polled (see useAutoRefresh.ts), so the returned task_id only needs to exist as a string."""
    job_ids = await queries.enqueue("fill_missing_snapshots", payload=b"on_demand")
    return {"task_id": str(job_ids[0])}


@router.post("/recompute-snapshots", response_model=dict)
async def trigger_recompute(body: RecomputeRequest, queries: Queries = Depends(get_pgq_queries)):
    end = body.end_date or yesterday()
    if end > yesterday():
        raise HTTPException(status_code=400, detail=f"end_date cannot exceed yesterday ({yesterday()})")
    if body.start_date > end:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    # Created here (not inside the PgQueuer entrypoint) so the client gets a pollable task_id
    # back immediately, even before the job is picked up — see snapshots.py's
    # _run_recompute_snapshots and pgq_app.py's entrypoint for the rest of this task's
    # deliberately different run_id lifecycle.
    run_id = await job_runs.start_run("recompute_snapshots_range", trigger="on_demand")
    payload = json.dumps(
        {"start": body.start_date.isoformat(), "end": end.isoformat(), "run_id": run_id}
    ).encode()
    try:
        await queries.enqueue("recompute_snapshots_range", payload=payload)
    except Exception as exc:
        await job_runs.finish_run(run_id, status="failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    return {"task_id": str(run_id)}


@router.get("/task/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    try:
        run_id = int(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")
    run = await job_runs.get_by_id(run_id)
    return TaskStatus(task_id=task_id, **job_runs.to_task_status_dict(run))


# ── System settings ────────────────────────────────────────────────────────

@router.get("/settings/{key}")
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    from app.models.system_setting import SystemSetting
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found.")
    return {"key": setting.key, "value": setting.value}


@router.put("/settings/{key}")
async def set_setting(key: str, body: dict, db: AsyncSession = Depends(get_db)):
    from app.models.system_setting import SystemSetting
    value = body.get("value", "")
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = SystemSetting(key=key, value=value)
        db.add(setting)
    await db.commit()
    return {"key": key, "value": value}


@router.delete("/settings/{key}", status_code=204)
async def delete_setting(key: str, db: AsyncSession = Depends(get_db)):
    from app.models.system_setting import SystemSetting
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        await db.delete(setting)
        await db.commit()


# ── Health ────────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Returns 200 when DB is reachable, 503 otherwise.
    Probed by HAProxy active health checks every 2 s."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── Version ───────────────────────────────────────────────────────────────

@router.get("/version")
async def get_version():
    """Retourne la version de l'application.

    Priority: INSTALLER_VERSION env var (set by installer via .env)
              → APP_VERSION env var (fallback)
              → "UNKNOWN" (installer did not run or env not injected)
    """
    import os
    version = os.getenv("INSTALLER_VERSION") or os.getenv("APP_VERSION") or "UNKNOWN"
    return {"version": version}
