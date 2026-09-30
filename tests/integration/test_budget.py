"""The Budget stage, against real Postgres and real Redis.

The concurrency test in particular only means something against a real
Redis — it's exercising the exact race a naive read-then-write
implementation wouldn't handle (see docs/architecture.md Section 7 and
packages/ledger_core/budget.py).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from ledger_core import budget
from ledger_core.budget import BudgetCeilingReached
from tests.conftest import make_decision_type_config


@pytest.mark.asyncio
async def test_call_under_ceiling_is_allowed(db_session, redis_client, unique_suffix):
    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="100.0000", reservation_estimate="10.0000"
    )
    decision = await budget.evaluate(
        db_session, redis_client, system=system, decision_type="test_decision",
        config=config, on_date=date.today(),
    )
    assert decision.allowed
    assert decision.model_id == config.routing_model_id
    assert not decision.degraded


@pytest.mark.asyncio
async def test_call_over_ceiling_is_hard_stopped(db_session, redis_client, unique_suffix):
    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="5.0000", reservation_estimate="10.0000",
        enforcement_mode="hard_stop",
    )
    with pytest.raises(BudgetCeilingReached) as exc_info:
        await budget.evaluate(
            db_session, redis_client, system=system, decision_type="test_decision",
            config=config, on_date=date.today(),
        )
    assert exc_info.value.ceiling == Decimal("5.0000")


@pytest.mark.asyncio
async def test_reservation_is_released_when_call_is_blocked(db_session, redis_client, unique_suffix):
    """A blocked call must not leave its reservation stuck in the running
    total — otherwise the ceiling would ratchet down forever from blocked
    attempts alone."""
    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="5.0000", reservation_estimate="10.0000",
        enforcement_mode="hard_stop",
    )
    key = budget.budget_key(system, "test_decision", date.today())

    with pytest.raises(BudgetCeilingReached):
        await budget.evaluate(
            db_session, redis_client, system=system, decision_type="test_decision",
            config=config, on_date=date.today(),
        )

    spent = await redis_client.get(key)
    assert spent is None or Decimal(spent) == Decimal(0)


@pytest.mark.asyncio
async def test_degrade_mode_falls_back_to_cheaper_model(db_session, redis_client, unique_suffix):
    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="10.0000", reservation_estimate="6.0000",
        enforcement_mode="degrade", fallback_model_id="apac.anthropic.claude-haiku-4-5",
        routing_model_id="apac.anthropic.claude-sonnet-5",
    )
    # first call consumes 6 of the 10 ceiling
    d1 = await budget.evaluate(
        db_session, redis_client, system=system, decision_type="test_decision",
        config=config, on_date=date.today(),
    )
    assert d1.allowed and not d1.degraded

    # second call's 6-unit reservation would push total to 12 > 10 ceiling;
    # degrade mode should fall back to the smaller 3-unit reservation
    # (6 + 3 = 9 <= 10) rather than raise
    d2 = await budget.evaluate(
        db_session, redis_client, system=system, decision_type="test_decision",
        config=config, on_date=date.today(),
    )
    assert d2.allowed
    assert d2.degraded
    assert d2.model_id == "apac.anthropic.claude-haiku-4-5"


@pytest.mark.asyncio
async def test_calendar_override_beats_default_ceiling_on_matching_date(
    db_session, redis_client, unique_suffix
):
    from ledger_core.db.models import CeilingCalendarOverride

    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="5.0000", reservation_estimate="1.0000",
    )
    override_date = date.today() + timedelta(days=30)
    db_session.add(
        CeilingCalendarOverride(
            system=system, decision_type="test_decision", override_date=override_date,
            ceiling="500.0000", reason="test", approved_by="pytest",
        )
    )
    await db_session.commit()

    ceiling_on_override_day = await budget.effective_ceiling(
        db_session, system=system, decision_type="test_decision", config=config, on_date=override_date
    )
    ceiling_on_ordinary_day = await budget.effective_ceiling(
        db_session, system=system, decision_type="test_decision", config=config, on_date=date.today()
    )
    assert ceiling_on_override_day == Decimal("500.0000")
    assert ceiling_on_ordinary_day == Decimal("5.0000")


@pytest.mark.asyncio
async def test_concurrent_calls_never_overshoot_the_ceiling(db_session, redis_client, unique_suffix):
    """A naive implementation would read the running total, then write it
    after the call completes — racy under concurrency. This is the test
    that would fail against that naive version and must pass against the
    atomic reserve-then-true-up implementation here: exactly 5 of 20
    concurrent callers should fit under a ceiling sized for exactly 5.
    """
    system = f"sys_{unique_suffix}"
    config = await make_decision_type_config(
        db_session, system=system, daily_ceiling="5.0000", reservation_estimate="1.0000",
        enforcement_mode="hard_stop",
    )

    from ledger_core.db.base import init_engine, session_scope
    from tests.conftest import TEST_DATABASE_URL

    init_engine(TEST_DATABASE_URL)

    async def attempt() -> bool:
        async with session_scope() as session:
            try:
                await budget.evaluate(
                    session, redis_client, system=system, decision_type="test_decision",
                    config=config, on_date=date.today(),
                )
                return True
            except BudgetCeilingReached:
                return False

    results = await asyncio.gather(*(attempt() for _ in range(20)))
    assert sum(results) == 5
