# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.models import DailySnapshot, Transaction

router = APIRouter(tags=["dashboard"])


class TWRRSummaryOut(BaseModel):
    twrr_total_pct: float        # (index_final/100 - 1) * 100
    twrr_annualized_pct: float   # ((index_final/100)^(365.25/nb_jours) - 1) * 100
    period_days: int
    start_date: str              # ISO format
    end_date: str
    start_index: float           # = 100 always
    end_index: float             # last TWRR index value


@router.get("/twrr-summary", response_model=TWRRSummaryOut)
async def get_twrr_summary(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a concise TWRR summary by reading the first and last daily snapshot.

    The TWRR index is computed using the same _compute_twrr logic used by the
    full TWRR endpoint (neutralises external cash flows). This endpoint extracts
    just the final scalar values for display in a summary widget.
    """
    from app.api.routers.snapshots import _compute_twrr

    # ── 1. Load all daily snapshots (total_eur > 0), deduplicated per date ──
    snaps_raw = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.total_eur > 0)
        .order_by(DailySnapshot.date.asc())
    )
    seen_dates: dict = {}
    for s in snaps_raw.scalars().all():
        if s.date not in seen_dates or s.id > seen_dates[s.date].id:
            seen_dates[s.date] = s
    daily_list = sorted(seen_dates.values(), key=lambda s: s.date)

    if len(daily_list) < 2:
        raise HTTPException(status_code=404, detail="Pas assez de snapshots pour calculer le TWRR")

    # ── 2. Build value series ──────────────────────────────────────────────
    value_series = [(s.date, s.total_eur) for s in daily_list]

    # ── 3. Compute TWRR index (no external flows for total — same as full endpoint) ──
    twrr_series = _compute_twrr(value_series, {})

    if not twrr_series:
        raise HTTPException(status_code=404, detail="Unable to compute TWRR")

    first = twrr_series[0]
    last = twrr_series[-1]

    from datetime import date as date_cls
    start_date = date_cls.fromisoformat(first["date"])
    end_date = date_cls.fromisoformat(last["date"])
    period_days = (end_date - start_date).days

    end_index = last["index"]
    twrr_total_pct = round((end_index / 100.0 - 1.0) * 100.0, 2)

    if period_days > 0:
        twrr_annualized_pct = round(
            ((end_index / 100.0) ** (365.25 / period_days) - 1.0) * 100.0, 2
        )
    else:
        twrr_annualized_pct = 0.0

    return TWRRSummaryOut(
        twrr_total_pct=twrr_total_pct,
        twrr_annualized_pct=twrr_annualized_pct,
        period_days=period_days,
        start_date=first["date"],
        end_date=last["date"],
        start_index=100.0,
        end_index=round(end_index, 2),
    )


class TRIOut(BaseModel):
    tri_pct: float
    tri_label: str
    total_investi: float
    total_retire: float
    valeur_actuelle: float
    nb_flux: int


@router.get("/tri", response_model=TRIOut)
async def get_tri(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Compute the IRR (XIRR) for the full portfolio:
    - Negative cash flows = LIQUIDITE.EURO deposits (money taken out of pocket)
    - Positive cash flows = negative LIQUIDITE.EURO withdrawals (money received)
    - Terminal value      = total portfolio value today
    """
    from datetime import date as date_cls
    import math

    # 1. Fetch all LIQUIDITE.EURO cash flows (all accounts)
    result = await db.execute(
        select(Transaction.date, Transaction.quantity, Transaction.total_amount_eur)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.ticker == "LIQUIDITE.EURO",
            Transaction.type == "Actif",
        )
        .order_by(Transaction.date)
    )
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail="No cash flows found for this portfolio")

    # 2. Build cash flows from investor perspective:
    # deposit (qty > 0) → investor pays out → negative for IRR
    # withdrawal (qty < 0) → investor receives → positive for IRR
    cash_flows: list[tuple[date_cls, float]] = []
    total_investi = 0.0
    total_retire = 0.0
    for row_date, qty, amt_eur in rows:
        cf = -float(amt_eur)   # negate: deposit = negative, withdrawal = positive
        cash_flows.append((row_date, cf))
        if cf < 0:
            total_investi += abs(cf)
        else:
            total_retire += cf

    # 3. Current value = total portfolio value — fetch the latest daily snapshot
    snap = await db.execute(
        select(DailySnapshot.total_eur, DailySnapshot.date)
        .where(DailySnapshot.portfolio_id == portfolio_id)
        .order_by(DailySnapshot.date.desc())
        .limit(1)
    )
    snap_row = snap.one_or_none()
    if not snap_row:
        raise HTTPException(status_code=404, detail="No snapshot available")

    valeur_actuelle = float(snap_row.total_eur)
    snap_date = snap_row.date
    cash_flows.append((snap_date, valeur_actuelle))

    # 4. XIRR Newton-Raphson
    t0 = cash_flows[0][0]

    def npv(r: float) -> float:
        total = 0.0
        for d, cf in cash_flows:
            t = (d - t0).days / 365.25
            total += cf / (1 + r) ** t
        return total

    def npv_deriv(r: float) -> float:
        total = 0.0
        for d, cf in cash_flows:
            t = (d - t0).days / 365.25
            total -= t * cf / (1 + r) ** (t + 1)
        return total

    r = 0.10
    for _ in range(1000):
        f = npv(r)
        fp = npv_deriv(r)
        if abs(fp) < 1e-12:
            break
        r_new = r - f / fp
        if abs(r_new - r) < 1e-8:
            r = r_new
            break
        r = r_new

    if math.isnan(r) or math.isinf(r):  # pragma: no cover — dead code: Newton-Raphson raises ValueError/TypeError before producing NaN with fractional exponents
        raise HTTPException(status_code=422, detail="TRI incalculable")

    return TRIOut(
        tri_pct=round(r * 100, 2),
        tri_label=f"{r * 100:.2f} % / an",
        total_investi=round(total_investi, 2),
        total_retire=round(total_retire, 2),
        valeur_actuelle=round(valeur_actuelle, 2),
        nb_flux=len(cash_flows) - 1,
    )
