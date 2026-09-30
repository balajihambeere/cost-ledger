"""The shared wrapper client.

One shared internal client that every system calls instead of reaching
Bedrock directly. Every call requires a system name and a decision type
as arguments before it will run at all — there is no code path that can
reach the model without them.

This module is that wrapper. `call_model` is the *only* supported way for
any of the six simulated systems (or a real one, later) to reach Bedrock in
this codebase. It composes, in order:

  1. identity resolution — packages/ledger_core/identity.py
  2. budget evaluation    — packages/ledger_core/budget.py
  3. the actual model call — packages/ledger_core/bedrock_client.py
  4. cost computation      — packages/ledger_core/cost.py
  5. ledger recording      — AttributedCall, append-only

A caller retrying the same underlying task passes the same `decision_id`
back in with an incremented `attempt_number`, so cost-per-decision can be
computed as SUM(cost) GROUP BY decision_id, not per call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core import budget, cost as cost_module, identity, rate_card
from ledger_core.bedrock_client import BedrockClient
from ledger_core.budget import BudgetCeilingReached
from ledger_core.db.models import AttributedCall, DecisionTypeConfig


class NoDecisionTypeConfigured(RuntimeError):
    """Raised when a caller asks for a (system, decision_type) that nobody
    has deliberately configured a ceiling for yet. Every ceiling must be
    set on purpose, one at a time — this refuses to invent a default
    rather than silently letting an unconfigured decision type spend
    without limit."""


@dataclass(frozen=True)
class WrapperResult:
    decision_id: uuid.UUID
    attempt_number: int
    status: str  # success | failed | degraded | blocked
    model_id: str
    output_text: str | None
    cost: Decimal
    customer_id: str
    request_id: str | None


async def _load_config(session: AsyncSession, system: str, decision_type: str) -> DecisionTypeConfig:
    stmt = select(DecisionTypeConfig).where(
        DecisionTypeConfig.system == system, DecisionTypeConfig.decision_type == decision_type
    )
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        raise NoDecisionTypeConfigured(
            f"No budget configuration exists for system={system!r} "
            f"decision_type={decision_type!r}. Configure a ceiling before this "
            f"decision type can spend anything — see services/api routers/budget.py."
        )
    return config


async def call_model(
    session: AsyncSession,
    redis: Redis,
    bedrock: BedrockClient,
    *,
    system: str,
    decision_type: str,
    raw_customer_identifier: str,
    messages: list[dict],
    system_prompt: str | None = None,
    decision_id: uuid.UUID | None = None,
    attempt_number: int = 1,
) -> WrapperResult:
    config = await _load_config(session, system, decision_type)
    customer_id = await identity.resolve_customer_id(
        session, system=system, raw_identifier=raw_customer_identifier
    )
    decision_id = decision_id or uuid.uuid4()
    on_date = datetime.now(timezone.utc).date()

    try:
        decision = await budget.evaluate(
            session,
            redis,
            system=system,
            decision_type=decision_type,
            config=config,
            on_date=on_date,
        )
    except BudgetCeilingReached:
        session.add(
            AttributedCall(
                decision_id=decision_id,
                attempt_number=attempt_number,
                system=system,
                decision_type=decision_type,
                customer_id=customer_id,
                model_id=config.routing_model_id,
                input_tokens=0,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_write_input_tokens=0,
                cost=Decimal(0),
                status="blocked",
            )
        )
        await session.flush()
        raise

    request_metadata = {
        "system": system,
        "decision_type": decision_type,
        "decision_id": str(decision_id),
        "customer_id": customer_id,
    }

    try:
        result = bedrock.converse(
            model_id=decision.model_id,
            messages=messages,
            request_metadata=request_metadata,
            system_prompt=system_prompt,
        )
    except Exception:
        if decision.reservation_key is not None:
            await budget.release(redis, decision.reservation_key, decision.reservation_amount)
        session.add(
            AttributedCall(
                decision_id=decision_id,
                attempt_number=attempt_number,
                system=system,
                decision_type=decision_type,
                customer_id=customer_id,
                model_id=decision.model_id,
                input_tokens=0,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_write_input_tokens=0,
                cost=Decimal(0),
                status="failed",
            )
        )
        await session.flush()
        raise

    rate = await rate_card.current_rate(session, decision.model_id)
    call_cost = cost_module.compute_cost(result.usage, rate)

    if decision.reservation_key is not None:
        await budget.true_up(redis, decision.reservation_key, decision.reservation_amount, call_cost)

    status = "degraded" if decision.degraded else "success"
    session.add(
        AttributedCall(
            decision_id=decision_id,
            attempt_number=attempt_number,
            system=system,
            decision_type=decision_type,
            customer_id=customer_id,
            model_id=decision.model_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_input_tokens=result.usage.cache_read_input_tokens,
            cache_write_input_tokens=result.usage.cache_write_input_tokens,
            cost=call_cost,
            status=status,
            bedrock_request_id=result.request_id,
        )
    )
    await session.flush()

    return WrapperResult(
        decision_id=decision_id,
        attempt_number=attempt_number,
        status=status,
        model_id=decision.model_id,
        output_text=result.output_text,
        cost=call_cost,
        customer_id=customer_id,
        request_id=result.request_id,
    )
