"""Read-only queries over the attributed_calls ledger: spend by
system/decision_type (with cost per decision, not just cost per call),
and spend for one canonical customer across every system (the payoff of
identity resolution).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth import require_admin
from api.app.deps import get_db
from api.app.schemas import CustomerSpendResponse, CustomerSpendRow, LedgerRow, LedgerSummaryResponse

router = APIRouter(prefix="/v1/ledger", tags=["ledger"], dependencies=[Depends(require_admin)])

_CALLS_SQL = text(
    """
    SELECT system, decision_type, COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS total_cost
    FROM attributed_calls
    WHERE created_at >= :start AND created_at < :end
    GROUP BY system, decision_type
    """
)

_DECISIONS_SQL = text(
    """
    SELECT system, decision_type,
           COUNT(*) FILTER (WHERE succeeded) AS successful_decisions
    FROM (
        SELECT decision_id, system, decision_type,
               BOOL_OR(status IN ('success', 'degraded')) AS succeeded
        FROM attributed_calls
        WHERE created_at >= :start AND created_at < :end
        GROUP BY decision_id, system, decision_type
    ) per_decision
    GROUP BY system, decision_type
    """
)

_CUSTOMER_SQL = text(
    """
    SELECT system, decision_type, COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS cost
    FROM attributed_calls
    WHERE customer_id = :customer_id
    GROUP BY system, decision_type
    ORDER BY system, decision_type
    """
)


@router.get("/summary", response_model=LedgerSummaryResponse)
async def summary(
    start: date = Query(default_factory=lambda: date.today() - timedelta(days=7)),
    end: date = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db),
) -> LedgerSummaryResponse:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    calls_result = await db.execute(_CALLS_SQL, {"start": start_dt, "end": end_dt})
    calls_by_key = {(r.system, r.decision_type): r for r in calls_result}

    decisions_result = await db.execute(_DECISIONS_SQL, {"start": start_dt, "end": end_dt})
    decisions_by_key = {(r.system, r.decision_type): r.successful_decisions for r in decisions_result}

    rows: list[LedgerRow] = []
    grand_total = Decimal(0)
    for (system, decision_type), call_row in calls_by_key.items():
        successful = decisions_by_key.get((system, decision_type), 0)
        total_cost = Decimal(call_row.total_cost)
        grand_total += total_cost
        rows.append(
            LedgerRow(
                system=system,
                decision_type=decision_type,
                calls=call_row.calls,
                total_cost=total_cost,
                successful_decisions=successful,
                cost_per_decision=(total_cost / successful) if successful else None,
            )
        )

    rows.sort(key=lambda r: r.total_cost, reverse=True)
    return LedgerSummaryResponse(start=start, end=end, rows=rows, grand_total_cost=grand_total)


@router.get("/customers/{canonical_id}", response_model=CustomerSpendResponse)
async def customer_spend(
    canonical_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CustomerSpendResponse:
    result = await db.execute(_CUSTOMER_SQL, {"customer_id": str(canonical_id)})
    rows = [
        CustomerSpendRow(system=r.system, decision_type=r.decision_type, calls=r.calls, cost=Decimal(r.cost))
        for r in result
    ]
    total = sum((r.cost for r in rows), Decimal(0))
    return CustomerSpendResponse(canonical_id=str(canonical_id), rows=rows, total_cost=total)
