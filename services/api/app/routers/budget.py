"""Budget configuration and status. Every ceiling here is something a
person deliberately set (via PUT, upsert semantics — re-approving is a
normal, expected action, not an error), never a default the system
invented.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.budget import budget_key, effective_ceiling
from ledger_core.db.models import BudgetEvent, CeilingCalendarOverride, DecisionTypeConfig

from api.app.auth import require_admin
from api.app.deps import get_db, get_redis_client
from api.app.schemas import (
    BudgetEventOut,
    BudgetStatusResponse,
    CalendarOverrideIn,
    CalendarOverrideOut,
    DecisionTypeConfigIn,
    DecisionTypeConfigOut,
)

router = APIRouter(prefix="/v1/budget", tags=["budget"], dependencies=[Depends(require_admin)])


@router.get("/configs", response_model=list[DecisionTypeConfigOut])
async def list_configs(db: AsyncSession = Depends(get_db)) -> list[DecisionTypeConfigOut]:
    result = await db.execute(select(DecisionTypeConfig))
    return [DecisionTypeConfigOut.model_validate(c, from_attributes=True) for c in result.scalars()]


@router.put("/configs", response_model=DecisionTypeConfigOut)
async def upsert_config(
    body: DecisionTypeConfigIn, db: AsyncSession = Depends(get_db)
) -> DecisionTypeConfigOut:
    if body.enforcement_mode not in ("hard_stop", "degrade"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "enforcement_mode must be hard_stop or degrade")
    if body.enforcement_mode == "degrade" and not body.fallback_model_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "degrade mode requires fallback_model_id"
        )

    existing = await db.get(DecisionTypeConfig, (body.system, body.decision_type))
    if existing is None:
        existing = DecisionTypeConfig(system=body.system, decision_type=body.decision_type)
        db.add(existing)

    existing.enforcement_mode = body.enforcement_mode
    existing.daily_ceiling = body.daily_ceiling
    existing.currency = body.currency
    existing.fallback_model_id = body.fallback_model_id
    existing.routing_model_id = body.routing_model_id
    existing.reservation_estimate = body.reservation_estimate
    await db.flush()
    await db.refresh(existing)  # updated_at is a server-side default; refresh to read it back
    return DecisionTypeConfigOut.model_validate(existing, from_attributes=True)


@router.get("/calendar-overrides", response_model=list[CalendarOverrideOut])
async def list_overrides(db: AsyncSession = Depends(get_db)) -> list[CalendarOverrideOut]:
    result = await db.execute(select(CeilingCalendarOverride))
    return [CalendarOverrideOut.model_validate(o, from_attributes=True) for o in result.scalars()]


@router.put("/calendar-overrides", response_model=CalendarOverrideOut)
async def upsert_override(
    body: CalendarOverrideIn, db: AsyncSession = Depends(get_db)
) -> CalendarOverrideOut:
    """Upsert, not insert-only: re-approving an override for a date that
    already has one (e.g. the ceiling needs adjusting, or a scenario is
    re-run) updates it in place rather than failing on the unique
    constraint over (system, decision_type, override_date) — the same
    "a person can revise a deliberate decision" spirit as PUT
    /v1/budget/configs above, not a bug to route around at the call site.
    """
    config = await db.get(DecisionTypeConfig, (body.system, body.decision_type))
    if config is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No decision_type_config exists for {body.system}/{body.decision_type} yet — "
            "create the default config before adding a calendar override for it",
        )

    existing = await db.execute(
        select(CeilingCalendarOverride).where(
            CeilingCalendarOverride.system == body.system,
            CeilingCalendarOverride.decision_type == body.decision_type,
            CeilingCalendarOverride.override_date == body.override_date,
        )
    )
    override = existing.scalar_one_or_none()
    if override is None:
        override = CeilingCalendarOverride(**body.model_dump())
        db.add(override)
    else:
        override.ceiling = body.ceiling
        override.reason = body.reason
        override.approved_by = body.approved_by

    await db.flush()
    await db.refresh(override)  # created_at is a server-side default; refresh to read it back
    return CalendarOverrideOut.model_validate(override, from_attributes=True)


@router.delete("/calendar-overrides", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    system: str = Query(...),
    decision_type: str = Query(...),
    override_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    """The inverse of a deliberate approval is a deliberate removal — a
    calendar override is itself a decision someone made and should stay
    revisable, the same discipline applied to the ceiling itself.
    """
    existing = await db.execute(
        select(CeilingCalendarOverride).where(
            CeilingCalendarOverride.system == system,
            CeilingCalendarOverride.decision_type == decision_type,
            CeilingCalendarOverride.override_date == override_date,
        )
    )
    override = existing.scalar_one_or_none()
    if override is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such calendar override")
    await db.delete(override)
    await db.flush()


@router.get("/status", response_model=BudgetStatusResponse)
async def budget_status(
    system: str = Query(...),
    decision_type: str = Query(...),
    on_date: date = Query(default_factory=date.today, alias="date"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> BudgetStatusResponse:
    config = await db.get(DecisionTypeConfig, (system, decision_type))
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No config for this system/decision_type")

    ceiling = await effective_ceiling(
        db, system=system, decision_type=decision_type, config=config, on_date=on_date
    )
    override_exists = await db.execute(
        select(CeilingCalendarOverride).where(
            CeilingCalendarOverride.system == system,
            CeilingCalendarOverride.decision_type == decision_type,
            CeilingCalendarOverride.override_date == on_date,
        )
    )
    ceiling_source = "calendar_override" if override_exists.scalar_one_or_none() else "default"

    key = budget_key(system, decision_type, on_date)
    raw = await redis.get(key)
    spent_today = Decimal(str(raw)) if raw is not None else Decimal(0)

    return BudgetStatusResponse(
        system=system,
        decision_type=decision_type,
        date=on_date,
        spent_today=spent_today,
        ceiling=ceiling,
        ceiling_source=ceiling_source,
        percent_used=(spent_today / ceiling * 100) if ceiling else Decimal(0),
    )


@router.get("/events", response_model=list[BudgetEventOut])
async def list_events(
    system: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetEventOut]:
    stmt = select(BudgetEvent).order_by(BudgetEvent.occurred_at.desc()).limit(limit)
    if system:
        stmt = stmt.where(BudgetEvent.system == system)
    result = await db.execute(stmt)
    return [BudgetEventOut.model_validate(e, from_attributes=True) for e in result.scalars()]
