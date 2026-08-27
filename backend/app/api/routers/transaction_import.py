# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Bulk transaction import — download a filled-in Excel template, validate it (dry-run, no DB
writes), then commit the rows the user selects. See CLAUDE.md's "Bulk transaction import
(Excel)" section for the full Sens table and the conventions this endpoint set encodes.
"""
from __future__ import annotations

import json
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pgqueuer import Queries
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pgq import get_pgq_queries
from app.services.transaction_service import (
    TransactionCreate,
    trigger_snapshot_recompute,
    create_transaction_core,
)
from app.core.database import get_db
from app.services.import_service import (
    RowResult,
    build_template_workbook,
    load_reference_data,
    parse_uploaded_workbook,
    validate_import,
)

router = APIRouter(tags=["transaction-import"])


class ResolvedOut(BaseModel):
    portfolio_id: int
    account_id: int
    portfolio_name: str
    account_name: str
    date: str
    type: str
    operation: Optional[str]
    ticker: str
    currency: str
    exchange_rate: float
    quantity: float
    unit_price: float
    courtage_eur: float
    ttf_eur: float


class DuplicateOut(BaseModel):
    kind: str
    transaction_id: Optional[int] = None
    row_number: Optional[int] = None


class RowResultOut(BaseModel):
    row_number: int
    status: str
    sens: Optional[str]
    resolved: Optional[ResolvedOut] = None
    errors: list[str]
    warnings: list[str]
    duplicate_of: Optional[DuplicateOut] = None


class SummaryOut(BaseModel):
    total_rows: int
    ok: int
    errors: int
    duplicates: int


class ValidateResponse(BaseModel):
    rows: list[RowResultOut]
    summary: SummaryOut


class CommitResponse(BaseModel):
    status: str
    imported_count: int
    created_transaction_ids: list[int]


def _row_result_to_out(r: RowResult) -> RowResultOut:
    resolved_out = None
    if r.resolved is not None:
        resolved_out = ResolvedOut(
            portfolio_id=r.resolved.portfolio_id,
            account_id=r.resolved.account_id,
            portfolio_name=r.resolved.portfolio_name,
            account_name=r.resolved.account_name,
            date=r.resolved.date.isoformat(),
            type=r.resolved.type,
            operation=r.resolved.operation,
            ticker=r.resolved.ticker,
            currency=r.resolved.currency,
            exchange_rate=r.resolved.exchange_rate,
            quantity=r.resolved.quantity,
            unit_price=r.resolved.unit_price,
            courtage_eur=r.resolved.courtage_eur,
            ttf_eur=r.resolved.ttf_eur,
        )
    duplicate_out = None
    if r.duplicate_of is not None:
        duplicate_out = DuplicateOut(
            kind=r.duplicate_of.kind,
            transaction_id=r.duplicate_of.transaction_id,
            row_number=r.duplicate_of.row_number,
        )
    return RowResultOut(
        row_number=r.row_number, status=r.status, sens=r.sens,
        resolved=resolved_out, errors=r.errors, warnings=r.warnings,
        duplicate_of=duplicate_out,
    )


@router.get("/template/{filename}")
async def download_import_template(filename: str, db: AsyncSession = Depends(get_db)):
    # `filename` is unused (always the same constant) — its only purpose is to make the
    # download URL itself end in a real filename. Some WebKit-based browsers (e.g. Epiphany,
    # this app's fallback native-window mode on Linux) ignore Content-Disposition when
    # naming a download triggered via a synthetic <a download> click and instead generate a
    # random UUID name; putting the filename in the URL path is the standard, portable
    # workaround since virtually every browser/webview falls back to the URL's last path
    # segment when it can't otherwise determine a name.
    ref = await load_reference_data(db)
    wb = build_template_workbook(ref)
    buffer = BytesIO()
    wb.save(buffer)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="modele_import_transactions.xlsx"'},
    )


async def _read_and_parse_upload(file: UploadFile) -> list[dict]:
    """Shared by /validate and /commit — reads the upload and parses it, normalizing any
    parse failure (bad file type, missing sheet) into a 400 rather than a raw 500."""
    file_bytes = await file.read()
    try:
        return parse_uploaded_workbook(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/validate", response_model=ValidateResponse)
async def validate_import_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    raw_rows = await _read_and_parse_upload(file)
    result = await validate_import(db, raw_rows)
    return ValidateResponse(
        rows=[_row_result_to_out(r) for r in result.rows],
        summary=SummaryOut(**result.summary.__dict__),
    )


@router.post("/commit", response_model=CommitResponse)
async def commit_import_file(
    file: UploadFile = File(...),
    include_rows: str = Form(...),
    db: AsyncSession = Depends(get_db),
    queries: Queries = Depends(get_pgq_queries),
):
    try:
        include_row_numbers = set(json.loads(include_rows))
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="include_rows doit être une liste JSON de numéros de ligne.")

    raw_rows = await _read_and_parse_upload(file)

    # Never trust client-echoed data — re-validate from scratch against the freshly
    # uploaded bytes and current DB state (decision: commit is all-or-nothing, and DB
    # state may have changed since the user's earlier /validate call).
    result = await validate_import(db, raw_rows)
    by_row = {r.row_number: r for r in result.rows}

    included: list[RowResult] = []
    for row_number in include_row_numbers:
        row = by_row.get(row_number)
        if row is None or row.status == "error":
            detail = f"Ligne {row_number} : " + (
                "; ".join(row.errors) if row is not None else "ligne introuvable dans le fichier."
            )
            raise HTTPException(status_code=422, detail=detail)
        included.append(row)

    included.sort(key=lambda r: (r.resolved.portfolio_id, r.resolved.account_id, r.resolved.date, r.row_number))

    created_ids: list[int] = []
    created_dates = []
    try:
        for row in included:
            r = row.resolved
            body = TransactionCreate(
                portfolio_id=r.portfolio_id, account_id=r.account_id, date=r.date,
                type=r.type, ticker=r.ticker, currency=r.currency, exchange_rate=r.exchange_rate,
                quantity=r.quantity, unit_price=r.unit_price, operation=r.operation,
                courtage_eur=r.courtage_eur, ttf_eur=r.ttf_eur,
            )
            tx = await create_transaction_core(body, db)
            created_ids.append(tx.id)
            created_dates.append(tx.date)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Échec de l'import : {exc}")

    if created_ids:
        await db.commit()
        await trigger_snapshot_recompute(included[0].resolved.portfolio_id, min(created_dates), queries)

    return CommitResponse(status="ok", imported_count=len(created_ids), created_transaction_ids=created_ids)
