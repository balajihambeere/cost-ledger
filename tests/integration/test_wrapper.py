"""ledger_core.wrapper.call_model — the full composition
(identity -> budget -> call -> cost -> ledger), against real Postgres and
Redis with the mock Bedrock client."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ledger_core import wrapper
from ledger_core.bedrock_client import MockScenario
from ledger_core.budget import BudgetCeilingReached, budget_key
from ledger_core.db.models import AttributedCall
from ledger_core.wrapper import NoDecisionTypeConfigured
from tests.conftest import make_decision_type_config

MESSAGES = [{"role": "user", "content": [{"text": "does this saree run true to size?"}]}]


@pytest.mark.asyncio
async def test_unconfigured_decision_type_is_refused(db_session, redis_client, mock_bedrock, unique_suffix):
    with pytest.raises(NoDecisionTypeConfigured):
        await wrapper.call_model(
            db_session, redis_client, mock_bedrock,
            system=f"sys_{unique_suffix}", decision_type="never_configured",
            raw_customer_identifier="cust1", messages=MESSAGES,
        )


@pytest.mark.asyncio
async def test_successful_call_is_recorded_with_real_cost(
    db_session, redis_client, mock_bedrock, rate_cards, unique_suffix
):
    system = f"sys_{unique_suffix}"
    await make_decision_type_config(db_session, system=system, daily_ceiling="1000.0000")

    result = await wrapper.call_model(
        db_session, redis_client, mock_bedrock,
        system=system, decision_type="test_decision",
        raw_customer_identifier="cust1", messages=MESSAGES,
    )

    assert result.status == "success"
    assert result.cost > 0

    row = (
        await db_session.execute(
            select(AttributedCall).where(AttributedCall.decision_id == result.decision_id)
        )
    ).scalar_one()
    assert row.status == "success"
    assert row.system == system
    assert row.customer_id.startswith("unresolved:")  # never linked in this test


@pytest.mark.asyncio
async def test_blocked_call_is_recorded_and_raises(
    db_session, redis_client, mock_bedrock, rate_cards, unique_suffix
):
    system = f"sys_{unique_suffix}"
    await make_decision_type_config(
        db_session, system=system, daily_ceiling="0.0000", reservation_estimate="1.0000"
    )

    with pytest.raises(BudgetCeilingReached):
        await wrapper.call_model(
            db_session, redis_client, mock_bedrock,
            system=system, decision_type="test_decision",
            raw_customer_identifier="cust1", messages=MESSAGES,
        )

    rows = (
        await db_session.execute(select(AttributedCall).where(AttributedCall.system == system))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "blocked"
    assert rows[0].cost == 0


@pytest.mark.asyncio
async def test_retries_share_decision_id_and_sum_cost(
    db_session, redis_client, mock_bedrock, rate_cards, unique_suffix
):
    """Cost-per-decision, not cost-per-call — every attempt at
    the same task shares one decision_id and their costs sum."""
    system = f"sys_{unique_suffix}"
    await make_decision_type_config(db_session, system=system, daily_ceiling="1000.0000")

    decision_id = uuid.uuid4()
    r1 = await wrapper.call_model(
        db_session, redis_client, mock_bedrock,
        system=system, decision_type="test_decision",
        raw_customer_identifier="cust1", messages=MESSAGES,
        decision_id=decision_id, attempt_number=1,
    )
    r2 = await wrapper.call_model(
        db_session, redis_client, mock_bedrock,
        system=system, decision_type="test_decision",
        raw_customer_identifier="cust1", messages=MESSAGES,
        decision_id=decision_id, attempt_number=2,
    )

    assert r1.decision_id == r2.decision_id == decision_id

    rows = (
        await db_session.execute(select(AttributedCall).where(AttributedCall.decision_id == decision_id))
    ).scalars().all()
    assert len(rows) == 2
    assert {r.attempt_number for r in rows} == {1, 2}
    assert sum(r.cost for r in rows) == r1.cost + r2.cost


@pytest.mark.asyncio
async def test_bedrock_failure_releases_reservation_and_records_failed_row(
    db_session, redis_client, mock_bedrock, rate_cards, unique_suffix
):
    system = f"sys_{unique_suffix}"
    await make_decision_type_config(
        db_session, system=system, daily_ceiling="1000.0000", reservation_estimate="5.0000"
    )
    mock_bedrock.register_scenario(
        "TRIGGER_FAILURE",
        MockScenario(raises=RuntimeError("simulated transient Bedrock error")),
    )
    bad_messages = [{"role": "user", "content": [{"text": "TRIGGER_FAILURE please"}]}]

    with pytest.raises(RuntimeError, match="simulated transient Bedrock error"):
        await wrapper.call_model(
            db_session, redis_client, mock_bedrock,
            system=system, decision_type="test_decision",
            raw_customer_identifier="cust1", messages=bad_messages,
        )

    key = budget_key(system, "test_decision", date.today())
    spent = await redis_client.get(key)
    assert spent is None or Decimal(spent) == Decimal(0)

    rows = (
        await db_session.execute(select(AttributedCall).where(AttributedCall.system == system))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed"


@pytest.mark.asyncio
async def test_customer_identity_is_resolved_when_linked(
    db_session, redis_client, mock_bedrock, rate_cards, unique_suffix
):
    from ledger_core import identity

    system = f"sys_{unique_suffix}"
    await make_decision_type_config(db_session, system=system, daily_ceiling="1000.0000")

    canonical = await identity.link_identifier(db_session, system=system, raw_identifier="raw1")
    await db_session.commit()

    result = await wrapper.call_model(
        db_session, redis_client, mock_bedrock,
        system=system, decision_type="test_decision",
        raw_customer_identifier="raw1", messages=MESSAGES,
    )

    assert result.customer_id == str(canonical)
