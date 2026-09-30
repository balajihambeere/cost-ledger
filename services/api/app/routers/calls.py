"""POST /v1/calls — the HTTP front door to ledger_core.wrapper.call_model.

This is the only endpoint the six simulated systems are allowed to reach;
the caller's identity (`system`) comes from its API key, not from the
request body, so no system can tag a call as belonging to another one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.bedrock_client import BedrockClient
from ledger_core.budget import BudgetCeilingReached
from ledger_core.wrapper import NoDecisionTypeConfigured, call_model

from api.app.auth import require_service_api_key
from api.app.deps import get_bedrock_client, get_db, get_redis_client
from api.app.schemas import CallRequest, CallResponse

router = APIRouter(prefix="/v1/calls", tags=["calls"])


@router.post("", response_model=CallResponse)
async def create_call(
    body: CallRequest,
    system: str = Depends(require_service_api_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    bedrock: BedrockClient = Depends(get_bedrock_client),
) -> CallResponse:
    messages = [m.model_dump() for m in body.messages]
    try:
        result = await call_model(
            db,
            redis,
            bedrock,
            system=system,
            decision_type=body.decision_type,
            raw_customer_identifier=body.customer_identifier,
            messages=messages,
            system_prompt=body.system_prompt,
            decision_id=body.decision_id,
            attempt_number=body.attempt_number,
        )
    except NoDecisionTypeConfigured as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except BudgetCeilingReached as exc:
        # call_model already recorded a 'blocked' AttributedCall row and a
        # budget_events row for this breach before re-raising; get_db's
        # session_scope() commits that audit trail even though we're about
        # to raise an HTTPException here — see ledger_core.db.base.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {
                "message": str(exc),
                "system": exc.system,
                "decision_type": exc.decision_type,
                "spent_today": str(exc.spent_today),
                "ceiling": str(exc.ceiling),
            },
        ) from exc

    return CallResponse(
        decision_id=result.decision_id,
        attempt_number=result.attempt_number,
        status=result.status,
        model_id=result.model_id,
        output_text=result.output_text,
        cost=result.cost,
        customer_id=result.customer_id,
        request_id=result.request_id,
    )
