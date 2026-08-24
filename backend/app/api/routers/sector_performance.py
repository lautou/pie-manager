# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sector/commodity performance — trailing-1-year, EUR-adjusted bar chart shown on the
"Performance par secteur" tab of the Indicateurs page. Mounted at the same /api/indicators
prefix as indicators.py/country_performance.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pgqueuer import Queries
from pydantic import BaseModel

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.indicators import MacroSyncStatusOut
from app.tasks import job_runs
from app.services.sector_performance_service import (
    compute_sector_performance,
    create_sector_config,
    delete_sector_config,
    list_sector_configs,
    update_sector_config,
)

router = APIRouter(tags=["sector-performance"])


class SectorPerformanceOut(BaseModel):
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: str
    anchor_date: str
    index_label: str


class SectorPerfConfigOut(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str

    model_config = {"from_attributes": True}


class SectorPerfConfigCreate(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str


class SectorPerfConfigUpdate(BaseModel):
    label: str
    index_ticker: str
    currency: str
    index_label: str


@router.get("/sector-performance", response_model=list[SectorPerformanceOut])
async def get_sector_performance(db: AsyncSession = Depends(get_db)):
    results = await compute_sector_performance(db)
    return [
        {
            "code": r.code, "label": r.label, "currency": r.currency,
            "perf_pct": r.perf_pct,
            "latest_date": r.latest_date.isoformat(), "anchor_date": r.anchor_date.isoformat(),
            "index_label": r.index_label,
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Sector CRUD
# ---------------------------------------------------------------------------

@router.get("/sector-performance/sectors", response_model=list[SectorPerfConfigOut])
async def get_sectors(db: AsyncSession = Depends(get_db)):
    return await list_sector_configs(db)


@router.post("/sector-performance/sectors", response_model=SectorPerfConfigOut, status_code=201)
async def post_sector(body: SectorPerfConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_sector_config(
            db, body.code, body.label, body.index_ticker, body.currency, body.index_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/sector-performance/sectors/{code}", response_model=SectorPerfConfigOut)
async def put_sector(code: str, body: SectorPerfConfigUpdate, db: AsyncSession = Depends(get_db)):
    try:
        sector = await update_sector_config(
            db, code, body.label, body.index_ticker, body.currency, body.index_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if sector is None:
        raise HTTPException(status_code=404, detail=f"Unknown sector: {code}")
    return sector


@router.delete("/sector-performance/sectors/{code}", status_code=204)
async def delete_sector_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    result = await delete_sector_config(db, code)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown sector: {code}")


# ---------------------------------------------------------------------------
# Refresh trigger + sync status
# ---------------------------------------------------------------------------

@router.post("/sector-performance/refresh", response_model=dict)
async def refresh_sector_performance_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual sector performance refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_sector_performance", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}


@router.get("/sector-performance/sync-status", response_model=MacroSyncStatusOut)
async def get_sector_performance_sync_status():
    """Return the last sector performance sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_sector_performance")
    return job_runs.to_sync_status_dict(run)
