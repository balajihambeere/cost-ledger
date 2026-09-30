"""Fixtures wire tests to the *real* Postgres and Redis started by
`docker compose up postgres redis` (host-mapped ports — see
docker-compose.yml). No mocking of the database or cache: the whole point
of this build is that the wrapper's behavior (atomic reservations, ceiling
checks, identity resolution) is only trustworthy if proven against the
real thing it depends on. Only Bedrock itself is mocked (see
ledger_core.bedrock_client.MockBedrockClient) — this sandbox has no AWS
account to test against for real.

Run with: docker compose up -d postgres redis && pytest
(DATABASE_URL/REDIS_URL default to the host-mapped ports from .env.example)
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ledger_core.bedrock_client import MockBedrockClient
from ledger_core.db.models import DecisionTypeConfig, RateCardEntry

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ledger_app:change-me-in-real-deployments@localhost:55432/cost_ledger",
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:63790/1")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def mock_bedrock() -> MockBedrockClient:
    return MockBedrockClient()


@pytest.fixture
def unique_suffix() -> str:
    """Every test that creates a decision_type_config uses a unique system
    name so tests can run concurrently and never collide on the same
    (system, decision_type) primary key or the same Redis ceiling key."""
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def rate_cards(db_session: AsyncSession) -> None:
    """Ensures the two real rate cards exist (idempotent — matches
    database/seed/seed.sql) so cost computation has something to divide by."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    for model_id, input_rate, output_rate in (
        ("apac.anthropic.claude-sonnet-5", 2.00, 10.00),
        ("apac.anthropic.claude-haiku-4-5", 1.00, 5.00),
    ):
        existing = await db_session.execute(
            select(RateCardEntry).where(RateCardEntry.model_id == model_id)
        )
        if existing.scalar_one_or_none() is None:
            db_session.add(
                RateCardEntry(
                    model_id=model_id,
                    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    input_rate_per_million=input_rate,
                    output_rate_per_million=output_rate,
                    cache_write_multiplier=1.25,
                    cache_read_multiplier=0.10,
                    currency="USD",
                    source="test fixture",
                )
            )
    await db_session.commit()


async def make_decision_type_config(
    db_session: AsyncSession,
    *,
    system: str,
    decision_type: str = "test_decision",
    enforcement_mode: str = "hard_stop",
    daily_ceiling: str = "1000.0000",
    fallback_model_id: str | None = None,
    routing_model_id: str = "apac.anthropic.claude-sonnet-5",
    reservation_estimate: str = "1.0000",
) -> DecisionTypeConfig:
    config = DecisionTypeConfig(
        system=system,
        decision_type=decision_type,
        enforcement_mode=enforcement_mode,
        daily_ceiling=daily_ceiling,
        currency="INR",
        fallback_model_id=fallback_model_id,
        routing_model_id=routing_model_id,
        reservation_estimate=reservation_estimate,
    )
    db_session.add(config)
    await db_session.commit()
    return config
