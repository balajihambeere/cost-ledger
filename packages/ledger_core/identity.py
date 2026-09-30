"""Identity resolution.

Three systems, three honest local identifiers (an email hash, an order ID,
a ticket ID), none of them the same string. `resolve_customer_id` collapses
whichever one a caller has into one canonical customer ID *before* it's
used for tagging, so a per-customer query can follow one real person across
every system.

Deliberately conservative: an identifier that hasn't been explicitly
linked to a canonical account resolves to
`unresolved:{system}:{raw_identifier}`, never guessed via a fuzzy match —
a fuzzy match on contact details (email/phone) can silently merge two
unrelated customers who happen to share one, which is worse than no
answer at all. Linking happens through `link_identifier`, standing in for
what in a real deployment would be backed by each system's own account
layer; here it's an explicit, auditable mapping table (see
CustomerIdentifier in ledger_core.db.models) that a caller populates once
it knows two local IDs belong to the same person.

This fixes coverage going forward only — rows recorded before an
identifier was linked stay tagged with their unresolved form, and this
module does not attempt to retroactively rewrite them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.db.models import CustomerAccount, CustomerIdentifier


def unresolved_tag(system: str, raw_identifier: str) -> str:
    return f"unresolved:{system}:{raw_identifier}"


async def resolve_customer_id(session: AsyncSession, *, system: str, raw_identifier: str) -> str:
    stmt = select(CustomerIdentifier).where(
        CustomerIdentifier.system == system,
        CustomerIdentifier.raw_identifier == raw_identifier,
    )
    result = await session.execute(stmt)
    mapping = result.scalar_one_or_none()
    if mapping is None:
        return unresolved_tag(system, raw_identifier)
    return str(mapping.canonical_id)


async def link_identifier(
    session: AsyncSession,
    *,
    system: str,
    raw_identifier: str,
    canonical_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Link one system's local identifier to a canonical customer account.
    If canonical_id is omitted, a new account is created — the entry point
    for the very first system to ever see this customer. Idempotent: linking
    the same (system, raw_identifier) again is a no-op if it already points
    at the same account, and raises if it would silently reassign a
    previously-linked identifier to a different customer (a mistake here is
    exactly the kind of silent guess this module refuses to make).
    """
    existing = await session.execute(
        select(CustomerIdentifier).where(
            CustomerIdentifier.system == system,
            CustomerIdentifier.raw_identifier == raw_identifier,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        if canonical_id is not None and row.canonical_id != canonical_id:
            raise ValueError(
                f"{system}:{raw_identifier} is already linked to account "
                f"{row.canonical_id}, refusing to silently reassign to {canonical_id}"
            )
        return row.canonical_id

    if canonical_id is None:
        account = CustomerAccount()
        session.add(account)
        await session.flush()
        canonical_id = account.canonical_id
    else:
        account_exists = await session.execute(
            select(CustomerAccount).where(CustomerAccount.canonical_id == canonical_id)
        )
        if account_exists.scalar_one_or_none() is None:
            raise ValueError(f"No such canonical account: {canonical_id}")

    session.add(
        CustomerIdentifier(system=system, raw_identifier=raw_identifier, canonical_id=canonical_id)
    )
    try:
        await session.flush()
    except IntegrityError as exc:  # concurrent link of the same identifier
        await session.rollback()
        raise ValueError(f"{system}:{raw_identifier} was linked concurrently") from exc

    return canonical_id
