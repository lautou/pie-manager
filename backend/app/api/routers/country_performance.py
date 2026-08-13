"""Country stock-market performance leaderboard — Top-N ranking (trailing 1 year,
EUR-adjusted) shown on the "Performance des marchés" tab of the Indicateurs page. Mounted
at the same /api/indicators prefix as indicators.py (same page, same global/portfolio-
independent data), kept in its own router file since it's a distinct feature (a ranking,
not a region-scoped ratio) with its own CRUD/task/schemas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pgqueuer import Queries
from pydantic import BaseModel

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.indicators import MacroSyncStatusOut
from app.tasks import job_runs
from app.services.country_performance_service import (
    compute_country_performance,
    create_country_config,
    delete_country_config,
    list_country_configs,
    update_country_config,
)

router = APIRouter(tags=["country-performance"])


class CountryPerformanceOut(BaseModel):
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: str
    anchor_date: str
    index_label: str


class CountryPerfConfigOut(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str

    model_config = {"from_attributes": True}


class CountryPerfConfigCreate(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str


class CountryPerfConfigUpdate(BaseModel):
    label: str
    index_ticker: str
    currency: str
    index_label: str


@router.get("/country-performance", response_model=list[CountryPerformanceOut])
async def get_country_performance(db: AsyncSession = Depends(get_db)):
    results = await compute_country_performance(db)
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
# Country CRUD
# ---------------------------------------------------------------------------

@router.get("/country-performance/countries", response_model=list[CountryPerfConfigOut])
async def get_countries(db: AsyncSession = Depends(get_db)):
    return await list_country_configs(db)


@router.post("/country-performance/countries", response_model=CountryPerfConfigOut, status_code=201)
async def post_country(body: CountryPerfConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_country_config(
            db, body.code, body.label, body.index_ticker, body.currency, body.index_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/country-performance/countries/{code}", response_model=CountryPerfConfigOut)
async def put_country(code: str, body: CountryPerfConfigUpdate, db: AsyncSession = Depends(get_db)):
    try:
        country = await update_country_config(
            db, code, body.label, body.index_ticker, body.currency, body.index_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if country is None:
        raise HTTPException(status_code=404, detail=f"Unknown country: {code}")
    return country


@router.delete("/country-performance/countries/{code}", status_code=204)
async def delete_country_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    result = await delete_country_config(db, code)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown country: {code}")


# ---------------------------------------------------------------------------
# Refresh trigger + sync status
# ---------------------------------------------------------------------------

@router.post("/country-performance/refresh", response_model=dict)
async def refresh_country_performance_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual country performance refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_country_performance", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}


@router.get("/country-performance/sync-status", response_model=MacroSyncStatusOut)
async def get_country_performance_sync_status():
    """Return the last country performance sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_country_performance")
    return job_runs.to_sync_status_dict(run)
