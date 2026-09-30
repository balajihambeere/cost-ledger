"""Identity resolution admin endpoints. Linking is a deliberate act (an
admin says "these two local IDs are the same person"), never an automatic
fuzzy match — email/phone fuzzy matching is deliberately rejected because
it can silently merge two unrelated customers who happen to share one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ledger_core import identity
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth import require_admin
from api.app.deps import get_db
from api.app.schemas import IdentityLinkRequest, IdentityLinkResponse

router = APIRouter(prefix="/v1/identity", tags=["identity"], dependencies=[Depends(require_admin)])


@router.post("/link", response_model=IdentityLinkResponse)
async def link(body: IdentityLinkRequest, db: AsyncSession = Depends(get_db)) -> IdentityLinkResponse:
    try:
        canonical_id = await identity.link_identifier(
            db,
            system=body.system,
            raw_identifier=body.raw_identifier,
            canonical_id=body.canonical_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return IdentityLinkResponse(canonical_id=canonical_id)


@router.get("/resolve")
async def resolve(
    system: str = Query(...),
    raw_identifier: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    canonical = await identity.resolve_customer_id(db, system=system, raw_identifier=raw_identifier)
    return {"customer_id": canonical}
