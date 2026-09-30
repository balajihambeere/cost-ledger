"""The Budget stage: a pre-spend ceiling on AI call spend.

A pre-spend ceiling check backed by a fast, shared store every instance of
the wrapper can read and update in milliseconds — not a billing system
that lags a day (AWS Budgets/Cost Explorer refresh at most once every 24
hours) and not a human paged by an alert (real but still measured in
minutes, not milliseconds, in a live drill). This module is that fast
store, implemented on Redis.

A ceiling isn't one thing. Two enforcement modes, chosen per decision
type:
  - hard_stop — for background work (e.g. grounding retries). A call over
    the ceiling never reaches Bedrock; on-call is alerted.
  - degrade   — for customer-facing work. A call over the ceiling falls
    back to a cheaper configured model instead of failing outright.

Concurrency (ENGINEERING-DECISION — see docs/architecture.md Section 7): a
naive implementation would read the running total, then write it after
the call completes, which races if two calls are in flight at once. This
module reserves a conservative per-call estimate atomically *before* the
call, then true_up() corrects it to the real cost once known, using
Redis's atomic INCRBYFLOAT so no two callers can both slip in under a
ceiling that only one of them actually fit under.

Fail-safe direction when Redis itself is unreachable (ENGINEERING-DECISION):
degrade-mode decisions fail OPEN (serve the customer — customer-facing
failure is itself a real, measured cost). hard_stop-mode decisions fail
CLOSED (refuse the call — an unwatched spend is the larger risk for
background work). Either way, the fact that this happened is logged as
its own BudgetEvent, not silently absorbed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import redis.exceptions
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.db.models import BudgetEvent, CeilingCalendarOverride, DecisionTypeConfig

KEY_PREFIX = "cost_ledger:budget"
KEY_TTL_SECONDS = 60 * 60 * 48  # 2 days — a running total only ever needs to answer "today"


def budget_key(system: str, decision_type: str, on_date: date) -> str:
    return f"{KEY_PREFIX}:{system}:{decision_type}:{on_date.isoformat()}"


class BudgetCeilingReached(Exception):
    def __init__(self, system: str, decision_type: str, spent_today: Decimal, ceiling: Decimal):
        self.system = system
        self.decision_type = decision_type
        self.spent_today = spent_today
        self.ceiling = ceiling
        super().__init__(
            f"{system}/{decision_type} budget ceiling reached: "
            f"spent {spent_today} against a ceiling of {ceiling}"
        )


@dataclass
class BudgetDecision:
    """What the wrapper should do next, decided *before* the Bedrock call."""

    allowed: bool
    model_id: str
    degraded: bool
    reservation_key: str | None
    reservation_amount: Decimal
    ceiling: Decimal
    spent_before: Decimal


async def effective_ceiling(
    session: AsyncSession, *, system: str, decision_type: str, config: DecisionTypeConfig, on_date: date
) -> Decimal:
    """A calendar override, approved in advance, beats the default daily
    ceiling on a known high-demand date."""
    stmt = select(CeilingCalendarOverride).where(
        CeilingCalendarOverride.system == system,
        CeilingCalendarOverride.decision_type == decision_type,
        CeilingCalendarOverride.override_date == on_date,
    )
    result = await session.execute(stmt)
    override = result.scalar_one_or_none()
    if override is not None:
        return Decimal(str(override.ceiling))
    return Decimal(str(config.daily_ceiling))


async def _reserve(redis: Redis, key: str, amount: Decimal, ceiling: Decimal) -> tuple[bool, Decimal]:
    """Atomically add `amount` to the running total; if that crosses the
    ceiling, roll the reservation back. Returns (allowed, spent_before)."""
    new_total = Decimal(str(await redis.incrbyfloat(key, float(amount))))
    await redis.expire(key, KEY_TTL_SECONDS)
    if new_total > ceiling:
        await redis.incrbyfloat(key, float(-amount))
        return False, new_total - amount
    return True, new_total - amount


async def true_up(redis: Redis, key: str, reservation_amount: Decimal, actual_cost: Decimal) -> None:
    """Correct a reservation to the real cost once the call has completed."""
    delta = actual_cost - reservation_amount
    if delta != 0:
        await redis.incrbyfloat(key, float(delta))
        await redis.expire(key, KEY_TTL_SECONDS)


async def release(redis: Redis, key: str, reservation_amount: Decimal) -> None:
    """Fully undo a reservation — used when a call never actually ran
    (e.g. it was blocked before reaching Bedrock)."""
    if reservation_amount != 0:
        await redis.incrbyfloat(key, float(-reservation_amount))


async def evaluate(
    session: AsyncSession,
    redis: Redis,
    *,
    system: str,
    decision_type: str,
    config: DecisionTypeConfig,
    on_date: date,
) -> BudgetDecision:
    """The pre-spend check the wrapper calls before every request. Returns
    a BudgetDecision telling the wrapper which model to call (if any) and
    what reservation to true up afterward."""
    ceiling = await effective_ceiling(
        session, system=system, decision_type=decision_type, config=config, on_date=on_date
    )
    key = budget_key(system, decision_type, on_date)
    reservation = Decimal(str(config.reservation_estimate))

    try:
        allowed, spent_before = await _reserve(redis, key, reservation, ceiling)
    except redis.exceptions.RedisError:
        return await _fail_safe(session, system, decision_type, config, ceiling)

    if allowed:
        return BudgetDecision(
            allowed=True,
            model_id=config.routing_model_id,
            degraded=False,
            reservation_key=key,
            reservation_amount=reservation,
            ceiling=ceiling,
            spent_before=spent_before,
        )

    if config.enforcement_mode == "degrade":
        fallback_reservation = reservation / 2  # a smaller model; trued up to its real cost after
        try:
            fb_allowed, fb_spent_before = await _reserve(redis, key, fallback_reservation, ceiling)
        except redis.exceptions.RedisError:
            return await _fail_safe(session, system, decision_type, config, ceiling)

        await _log_event(
            session,
            system=system,
            decision_type=decision_type,
            event_type="degrade",
            spent_today=spent_before,
            ceiling=ceiling,
            detail=f"fell back to {config.fallback_model_id}",
        )
        if fb_allowed:
            return BudgetDecision(
                allowed=True,
                model_id=config.fallback_model_id,  # type: ignore[arg-type]
                degraded=True,
                reservation_key=key,
                reservation_amount=fallback_reservation,
                ceiling=ceiling,
                spent_before=fb_spent_before,
            )
        # Even the cheaper fallback would cross the ceiling. Documented
        # ENGINEERING-DECISION: treat it as a hard stop rather than degrade
        # indefinitely.
        await _log_event(
            session,
            system=system,
            decision_type=decision_type,
            event_type="hard_stop",
            spent_today=fb_spent_before,
            ceiling=ceiling,
            detail="fallback model would also exceed the ceiling",
        )
        raise BudgetCeilingReached(system, decision_type, fb_spent_before, ceiling)

    await _log_event(
        session,
        system=system,
        decision_type=decision_type,
        event_type="hard_stop",
        spent_today=spent_before,
        ceiling=ceiling,
        detail=None,
    )
    raise BudgetCeilingReached(system, decision_type, spent_before, ceiling)


async def _fail_safe(
    session: AsyncSession,
    system: str,
    decision_type: str,
    config: DecisionTypeConfig,
    ceiling: Decimal,
) -> BudgetDecision:
    if config.enforcement_mode == "degrade":
        await _log_event(
            session,
            system=system,
            decision_type=decision_type,
            event_type="fail_open",
            spent_today=Decimal(0),
            ceiling=ceiling,
            detail="Redis unavailable — degrade-mode decision failed open",
        )
        return BudgetDecision(
            allowed=True,
            model_id=config.routing_model_id,
            degraded=False,
            reservation_key=None,
            reservation_amount=Decimal(0),
            ceiling=ceiling,
            spent_before=Decimal(0),
        )
    await _log_event(
        session,
        system=system,
        decision_type=decision_type,
        event_type="fail_closed",
        spent_today=Decimal(0),
        ceiling=ceiling,
        detail="Redis unavailable — hard_stop-mode decision failed closed",
    )
    raise BudgetCeilingReached(system, decision_type, Decimal(0), ceiling)


async def _log_event(
    session: AsyncSession,
    *,
    system: str,
    decision_type: str,
    event_type: str,
    spent_today: Decimal,
    ceiling: Decimal,
    detail: str | None,
    decision_id: uuid.UUID | None = None,
) -> None:
    session.add(
        BudgetEvent(
            system=system,
            decision_type=decision_type,
            event_type=event_type,
            spent_today=spent_today,
            ceiling=ceiling,
            decision_id=decision_id,
            detail=detail,
        )
    )
    await session.flush()
