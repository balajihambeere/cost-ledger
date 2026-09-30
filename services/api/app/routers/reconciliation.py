from __future__ import annotations

import tempfile
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.db.models import ReconciliationRun

from reconciliation.reconcile import load_invoice_csv, run_reconciliation

from api.app.auth import require_admin
from api.app.deps import get_db
from api.app.schemas import ReconciliationRowOut, ReconciliationRunResponse

router = APIRouter(
    prefix="/v1/reconciliation", tags=["reconciliation"], dependencies=[Depends(require_admin)]
)


@router.post("/run", response_model=ReconciliationRunResponse)
async def trigger_run(
    period_start: date = Query(...),
    period_end: date = Query(...),
    invoice_csv: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunResponse:
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp.write(await invoice_csv.read())
        tmp_path = tmp.name

    invoice_rows = load_invoice_csv(tmp_path)
    results = await run_reconciliation(
        db,
        period_start=period_start,
        period_end=period_end,
        invoice_rows=invoice_rows,
        source_file=invoice_csv.filename or tmp_path,
    )

    return ReconciliationRunResponse(
        period_start=period_start,
        period_end=period_end,
        rows=[
            ReconciliationRowOut(
                model_id=r.model_id,
                usage_type=r.usage_type,
                estimated_cost=r.estimated_cost,
                actual_cost=r.actual_cost,
                gap_pct=r.gap_pct,
            )
            for r in results
        ],
    )


@router.get("/runs", response_model=ReconciliationRunResponse)
async def list_runs(
    period_start: date = Query(...),
    period_end: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunResponse:
    stmt = select(ReconciliationRun).where(
        ReconciliationRun.period_start == period_start, ReconciliationRun.period_end == period_end
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return ReconciliationRunResponse(
        period_start=period_start,
        period_end=period_end,
        rows=[
            ReconciliationRowOut(
                model_id=r.model_id,
                usage_type=r.usage_type,
                estimated_cost=r.estimated_cost,
                actual_cost=r.actual_cost,
                gap_pct=r.gap_pct,
            )
            for r in rows
        ],
    )
