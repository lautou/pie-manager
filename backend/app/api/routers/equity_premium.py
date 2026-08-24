# SPDX-License-Identifier: AGPL-3.0-or-later
"""Equity risk premium — implied Fed Model/Damodaran premium bar chart shown on the "Premium
action" tab of the Indicateurs page. Mounted at the same /api/indicators prefix as
indicators.py/country_performance.py/sector_performance.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pgqueuer import Queries
from pydantic import BaseModel

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.indicators import MacroSyncStatusOut
from app.tasks import job_runs
from app.services.equity_premium_service import (
    compute_equity_premiums,
    create_premium_config,
    delete_premium_config,
    list_premium_configs,
    update_premium_config,
)

router = APIRouter(tags=["equity-premium"])


class EquityPremiumOut(BaseModel):
    code: str
    label: str
    premium_pct: float
    equity_yield_pct: float
    bond_yield_pct: float
    equity_label: str
    bond_label: str
    asof_date: str


class EquityPremiumConfigOut(BaseModel):
    code: str
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str

    model_config = {"from_attributes": True}


class EquityPremiumConfigCreate(BaseModel):
    code: str
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str


class EquityPremiumConfigUpdate(BaseModel):
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str


@router.get("/equity-premium", response_model=list[EquityPremiumOut])
async def get_equity_premium(db: AsyncSession = Depends(get_db)):
    results = await compute_equity_premiums(db)
    return [
        {
            "code": r.code, "label": r.label, "premium_pct": r.premium_pct,
            "equity_yield_pct": r.equity_yield_pct, "bond_yield_pct": r.bond_yield_pct,
            "equity_label": r.equity_label, "bond_label": r.bond_label,
            "asof_date": r.asof_date.isoformat(),
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------

@router.get("/equity-premium/countries", response_model=list[EquityPremiumConfigOut])
async def get_premium_countries(db: AsyncSession = Depends(get_db)):
    return await list_premium_configs(db)


@router.post("/equity-premium/countries", response_model=EquityPremiumConfigOut, status_code=201)
async def post_premium_country(body: EquityPremiumConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_premium_config(
            db, body.code, body.label, body.equity_ticker, body.bond_ticker,
            body.equity_label, body.bond_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/equity-premium/countries/{code}", response_model=EquityPremiumConfigOut)
async def put_premium_country(code: str, body: EquityPremiumConfigUpdate, db: AsyncSession = Depends(get_db)):
    """Unlike sector-performance's PUT, update_premium_config has no field left to
    revalidate (code is immutable, there's no currency column) — it can only return None for
    an unknown code, never raise ValueError."""
    config = await update_premium_config(
        db, code, body.label, body.equity_ticker, body.bond_ticker,
        body.equity_label, body.bond_label,
    )
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown country: {code}")
    return config


@router.delete("/equity-premium/countries/{code}", status_code=204)
async def delete_premium_country_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    try:
        result = await delete_premium_config(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown country: {code}")


# ---------------------------------------------------------------------------
# Refresh trigger + sync status
# ---------------------------------------------------------------------------

@router.post("/equity-premium/refresh", response_model=dict)
async def refresh_equity_premium_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual equity risk premium refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_equity_premium", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}


@router.get("/equity-premium/sync-status", response_model=MacroSyncStatusOut)
async def get_equity_premium_sync_status():
    """Return the last equity premium sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_equity_premium")
    return job_runs.to_sync_status_dict(run)
