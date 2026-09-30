"""Identity resolution, against the real Postgres started by docker
compose — not a mock, since the whole point being tested is real
uniqueness/foreign-key behavior."""

from __future__ import annotations

import uuid

import pytest

from ledger_core import identity


@pytest.mark.asyncio
async def test_unresolved_identifier_returns_tagged_string(db_session, unique_suffix):
    result = await identity.resolve_customer_id(
        db_session, system=f"sys_{unique_suffix}", raw_identifier="never_linked"
    )
    assert result == f"unresolved:sys_{unique_suffix}:never_linked"


@pytest.mark.asyncio
async def test_link_then_resolve_returns_canonical_id(db_session, unique_suffix):
    system = f"sys_{unique_suffix}"
    canonical = await identity.link_identifier(db_session, system=system, raw_identifier="raw1")
    await db_session.commit()

    resolved = await identity.resolve_customer_id(db_session, system=system, raw_identifier="raw1")
    assert resolved == str(canonical)


@pytest.mark.asyncio
async def test_three_systems_collapse_to_one_canonical_id(db_session, unique_suffix):
    """An email hash, an order ID, and a ticket ID, three different
    systems, one real customer."""
    s1, s2, s3 = f"assistant_{unique_suffix}", f"logistics_{unique_suffix}", f"support_{unique_suffix}"

    canonical = await identity.link_identifier(db_session, system=s1, raw_identifier="a41f9c2")
    await identity.link_identifier(
        db_session, system=s2, raw_identifier="ORD-88214", canonical_id=canonical
    )
    await identity.link_identifier(
        db_session, system=s3, raw_identifier="TCK-55031", canonical_id=canonical
    )
    await db_session.commit()

    r1 = await identity.resolve_customer_id(db_session, system=s1, raw_identifier="a41f9c2")
    r2 = await identity.resolve_customer_id(db_session, system=s2, raw_identifier="ORD-88214")
    r3 = await identity.resolve_customer_id(db_session, system=s3, raw_identifier="TCK-55031")

    assert r1 == r2 == r3 == str(canonical)


@pytest.mark.asyncio
async def test_relinking_to_a_different_account_is_refused(db_session, unique_suffix):
    """A fuzzy/silent reassignment is refused — an email-based match can
    silently merge two unrelated customers who happen to share one."""
    system = f"sys_{unique_suffix}"
    first_account = await identity.link_identifier(db_session, system=system, raw_identifier="raw1")
    await db_session.commit()

    other_account = uuid.uuid4()
    with pytest.raises(ValueError, match="refusing to silently reassign"):
        await identity.link_identifier(
            db_session, system=system, raw_identifier="raw1", canonical_id=other_account
        )

    # and the original mapping is untouched
    resolved = await identity.resolve_customer_id(db_session, system=system, raw_identifier="raw1")
    assert resolved == str(first_account)


@pytest.mark.asyncio
async def test_relinking_same_identifier_to_same_account_is_idempotent(db_session, unique_suffix):
    system = f"sys_{unique_suffix}"
    canonical = await identity.link_identifier(db_session, system=system, raw_identifier="raw1")
    await db_session.commit()

    again = await identity.link_identifier(
        db_session, system=system, raw_identifier="raw1", canonical_id=canonical
    )
    assert again == canonical
