# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sovereign bond market performance leaderboard — trailing 1 year, EUR-adjusted, shown on
the "Performance obligataire" tab of the Indicateurs page. Mounted at the same
/api/indicators prefix as indicators.py/country_performance.py/sector_performance.py (same
page, same global/portfolio-independent data), kept in its own router file since it's a
distinct feature with its own CRUD/task/schemas."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pgqueuer import Queries
from pydantic import BaseModel

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.indicators import MacroSyncStatusOut
from app.tasks import job_runs
from app.services.bond_performance_service import (
    compute_bond_performance,
    create_bond_config,
    delete_bond_config,
    list_bond_configs,
    update_bond_config,
)
from app.services.code_keyed_crud import crud_or_http

router = APIRouter(tags=["bond-performance"])


class BondPerformanceOut(BaseModel):
    code: str
    label: str
    currency: str
    perf_pct: float
    latest_date: str
    anchor_date: str
    index_label: str


class BondPerfConfigOut(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str

    model_config = {"from_attributes": True}


class BondPerfConfigCreate(BaseModel):
    code: str
    label: str
    index_ticker: str
    currency: str
    index_label: str


class BondPerfConfigUpdate(BaseModel):
    label: str
    index_ticker: str
    currency: str
    index_label: str


@router.get("/bond-performance", response_model=list[BondPerformanceOut])
async def get_bond_performance(db: AsyncSession = Depends(get_db)):
    results = await compute_bond_performance(db)
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
# Bond-market CRUD
# ---------------------------------------------------------------------------

@router.get("/bond-performance/countries", response_model=list[BondPerfConfigOut])
async def get_bond_countries(db: AsyncSession = Depends(get_db)):
    return await list_bond_configs(db)


@router.post("/bond-performance/countries", response_model=BondPerfConfigOut, status_code=201)
async def post_bond_country(body: BondPerfConfigCreate, db: AsyncSession = Depends(get_db)):
    return await crud_or_http(create_bond_config(
        db, body.code, body.label, body.index_ticker, body.currency, body.index_label,
    ))


@router.put("/bond-performance/countries/{code}", response_model=BondPerfConfigOut)
async def put_bond_country(code: str, body: BondPerfConfigUpdate, db: AsyncSession = Depends(get_db)):
    return await crud_or_http(update_bond_config(
        db, code, body.label, body.index_ticker, body.currency, body.index_label,
    ), f"Unknown country: {code}")


@router.delete("/bond-performance/countries/{code}", status_code=204)
async def delete_bond_country_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    await crud_or_http(delete_bond_config(db, code), f"Unknown country: {code}")


# ---------------------------------------------------------------------------
# Refresh trigger + sync status
# ---------------------------------------------------------------------------

@router.post("/bond-performance/refresh", response_model=dict)
async def refresh_bond_performance_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual bond performance refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_bond_performance", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}


@router.get("/bond-performance/sync-status", response_model=MacroSyncStatusOut)
async def get_bond_performance_sync_status():
    """Return the last bond performance sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_bond_performance")
    return job_runs.to_sync_status_dict(run)
