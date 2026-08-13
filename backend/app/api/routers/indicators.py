"""Global macro indicators — growth (equity/oil) and inflation (government bond/gold) ratio
charts, per user-managed region (see MacroRegion). Not scoped to a portfolio: a single set of
series shared across the whole app."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pgqueuer import Queries
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from app.models.macro_indicator import MacroRegion
from app.tasks import job_runs
from app.services.macro_indicators_service import (
    compute_ratio_indicator,
    create_region,
    delete_region,
    get_macro_settings,
    list_regions,
    update_region,
)

router = APIRouter(tags=["indicators"])


async def _get_region_or_404(db: AsyncSession, code: str) -> MacroRegion:
    region = await db.get(MacroRegion, code)
    if region is None:
        raise HTTPException(status_code=404, detail=f"Unknown region: {code}")
    return region


class RatioIndicatorOut(BaseModel):
    dates: list[str]
    ratio: list[float]
    moving_avg: list[float]
    ma_years: Optional[float] = None
    status: Optional[str] = None
    latest_date: Optional[str] = None
    numerator_ticker: Optional[str] = None
    denominator_ticker: Optional[str] = None
    numerator_label: Optional[str] = None
    denominator_label: Optional[str] = None


class MacroSyncStatusOut(BaseModel):
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    total_tickers: int = 0
    succeeded: int = 0
    failed_tickers: list[str] = []


class MacroRegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str


class MacroRegionCreate(BaseModel):
    code: str
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str


class MacroRegionUpdate(BaseModel):
    label: str
    equity_ticker: str
    bond_ticker: str
    equity_label: str
    bond_label: str


@router.get("/growth", response_model=RatioIndicatorOut)
async def get_growth_indicator(region: str = Query("us"), db: AsyncSession = Depends(get_db)):
    region_row = await _get_region_or_404(db, region)
    macro_settings = await get_macro_settings(db)
    result = await compute_ratio_indicator(
        db, f"{region_row.code}_equity", "oil", macro_settings["ma_years"]
    )
    return {
        **result,
        "numerator_ticker": region_row.equity_ticker, "denominator_ticker": macro_settings["oil"],
        "numerator_label": region_row.equity_label, "denominator_label": macro_settings["oil_label"],
    }


@router.get("/inflation", response_model=RatioIndicatorOut)
async def get_inflation_indicator(region: str = Query("us"), db: AsyncSession = Depends(get_db)):
    region_row = await _get_region_or_404(db, region)
    macro_settings = await get_macro_settings(db)
    result = await compute_ratio_indicator(
        db, f"{region_row.code}_bond", "gold", macro_settings["ma_years"]
    )
    return {
        **result,
        "numerator_ticker": region_row.bond_ticker, "denominator_ticker": macro_settings["gold"],
        "numerator_label": region_row.bond_label, "denominator_label": macro_settings["gold_label"],
    }


# ---------------------------------------------------------------------------
# Region CRUD
# ---------------------------------------------------------------------------

@router.get("/regions", response_model=list[MacroRegionOut])
async def get_regions(db: AsyncSession = Depends(get_db)):
    return await list_regions(db)


@router.post("/regions", response_model=MacroRegionOut, status_code=201)
async def post_region(body: MacroRegionCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_region(
            db, body.code, body.label, body.equity_ticker, body.bond_ticker,
            body.equity_label, body.bond_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/regions/{code}", response_model=MacroRegionOut)
async def put_region(code: str, body: MacroRegionUpdate, db: AsyncSession = Depends(get_db)):
    region = await update_region(
        db, code, body.label, body.equity_ticker, body.bond_ticker,
        body.equity_label, body.bond_label,
    )
    if region is None:
        raise HTTPException(status_code=404, detail=f"Unknown region: {code}")
    return region


@router.delete("/regions/{code}", status_code=204)
async def delete_region_endpoint(code: str, db: AsyncSession = Depends(get_db)):
    try:
        result = await delete_region(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown region: {code}")


@router.post("/refresh", response_model=dict)
async def refresh_macro_indicators_endpoint(queries: Queries = Depends(get_pgq_queries)):
    """Trigger manual macro indicators refresh via PgQueuer (admin use)."""
    job_ids = await queries.enqueue("refresh_macro_indicators", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}


@router.get("/sync-status", response_model=MacroSyncStatusOut)
async def get_macro_sync_status():
    """Return the last macro indicators sync status from job_runs (populated by PgQueuer)."""
    run = await job_runs.get_latest("refresh_macro_indicators")
    return job_runs.to_sync_status_dict(run)
