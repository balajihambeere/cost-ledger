"""Looks up the rate card entry in effect for a model right now — the
latest RateCardEntry with effective_from <= now. Raises if no rate card has
ever been configured for the model, rather than silently defaulting to
zero cost — a silent zero would hide real spend just as effectively as an
untagged call would."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.db.models import RateCardEntry


class NoRateCardConfigured(RuntimeError):
    pass


async def current_rate(session: AsyncSession, model_id: str) -> RateCardEntry:
    now = datetime.now(timezone.utc)
    stmt = (
        select(RateCardEntry)
        .where(RateCardEntry.model_id == model_id, RateCardEntry.effective_from <= now)
        .order_by(RateCardEntry.effective_from.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise NoRateCardConfigured(
            f"No rate card entry configured for model_id={model_id!r} effective at {now.isoformat()}"
        )
    return entry
