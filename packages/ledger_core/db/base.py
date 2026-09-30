"""Async SQLAlchemy engine/session setup, shared by the API, budget engine,
reconciliation job, and simulation harness — every writer of the ledger uses
this same connection factory rather than rolling its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Commits whatever has been flushed even when an exception propagates
    out of the `yield` — not just on clean success.

    This matters specifically for the wrapper's audit trail (see
    ledger_core.wrapper.call_model): a budget-ceiling breach or a failed
    Bedrock call is recorded (added + flushed) *before* the corresponding
    exception is raised, precisely so it survives regardless of what the
    caller does with that exception next (e.g. the API turning it into an
    HTTP 429/500). Every write path in this codebase validates before
    writing rather than writing speculatively and rolling back, so a
    propagating exception here means "the request failed", not "the data
    written so far is invalid" — it should still be committed. If the
    commit itself fails (a genuine DB-level error), that's the one case
    where we roll back and let the failure propagate.
    """
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            raise
