from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.bedrock_client import BedrockClient, build_bedrock_client
from ledger_core.db.base import session_scope
from ledger_core.redis_client import get_redis

from api.app.config import Settings, get_settings

_bedrock_client: BedrockClient | None = None


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


def get_redis_client() -> Redis:
    return get_redis()


def get_bedrock_client(settings: Settings = Depends(get_settings)) -> BedrockClient:
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = build_bedrock_client(settings.bedrock_client_mode, settings.aws_region)
    return _bedrock_client
