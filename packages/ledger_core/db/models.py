"""ORM models for the Cost Ledger.

Table overview (see docs/architecture.md for the full concept map):
  - RateCardEntry           -> a versioned per-token rate card, never
                                hardcoded as a permanent truth.
  - DecisionTypeConfig       -> per (system, decision_type) ceiling +
                                enforcement mode (hard_stop | degrade).
  - CeilingCalendarOverride  -> a date-scoped ceiling that beats the
                                default on known high-demand dates.
  - AttributedCall           -> the ledger itself. One row per model call,
                                tagged with system/decision_type/
                                customer_id, grouped by decision_id for
                                cost-per-decision.
  - BudgetEvent               -> every hard-stop, degrade, and
                                calendar-override application, logged
                                distinguishably from ordinary traffic.
  - CustomerAccount /
    CustomerIdentifier       -> identity resolution, going forward only —
                                pre-resolver history is not backfilled.
  - ReconciliationRun         -> the estimate-vs-invoice gap, tracked
                                explicitly rather than hidden.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ledger_core.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class RateCardEntry(Base):
    """A versioned per-token rate for one model. Multiple rows per model_id
    are allowed — the current rate is the one with the latest
    effective_from <= now. Sticker prices move over time; this is never a
    hardcoded constant.
    """

    __tablename__ = "rate_card_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_rate_per_million: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    output_rate_per_million: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    cache_write_multiplier: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=1.25)
    cache_read_multiplier: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, default=0.10)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("model_id", "effective_from", name="uq_rate_card_model_effective"),
    )


class DecisionTypeConfig(Base):
    """Per (system, decision_type) budget configuration. The ceiling number
    AND the enforcement behavior are chosen deliberately per decision
    type, never copied or applied uniformly.
    """

    __tablename__ = "decision_type_configs"

    system: Mapped[str] = mapped_column(String(100), primary_key=True)
    decision_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    enforcement_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    daily_ceiling: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    fallback_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    routing_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # A conservative per-call cost estimate used to atomically *reserve*
    # budget before a call goes out (see packages/ledger_core/budget.py).
    # ENGINEERING-DECISION: a naive read-then-write of the running total
    # races under concurrent callers, so we reserve first, then true up
    # with the real cost once it's known.
    reservation_estimate: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "enforcement_mode IN ('hard_stop', 'degrade')", name="ck_enforcement_mode"
        ),
        CheckConstraint(
            "enforcement_mode != 'degrade' OR fallback_model_id IS NOT NULL",
            name="ck_degrade_requires_fallback",
        ),
    )


class CeilingCalendarOverride(Base):
    """A ceiling that beats the default on a specific date (e.g. a known
    high-traffic sale day). Approved in advance by a person — deliberately,
    not something raised in a panic mid-incident.
    """

    __tablename__ = "ceiling_calendar_overrides"

    id: Mapped[uuid.UUID] = _uuid_pk()
    system: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    override_date: Mapped[date] = mapped_column(nullable=False)
    ceiling: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["system", "decision_type"],
            ["decision_type_configs.system", "decision_type_configs.decision_type"],
        ),
        UniqueConstraint(
            "system", "decision_type", "override_date", name="uq_calendar_override"
        ),
    )


class CustomerAccount(Base):
    """One canonical customer. Identity resolution applies going forward
    only — pre-resolution history stays honestly unlinkable, and this
    schema does not pretend otherwise.
    """

    __tablename__ = "customer_accounts"

    canonical_id: Mapped[uuid.UUID] = _uuid_pk()
    display_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    identifiers: Mapped[list["CustomerIdentifier"]] = relationship(back_populates="account")


class CustomerIdentifier(Base):
    """Maps one system's local identifier (email hash, order ID, ticket ID)
    to one canonical customer — three honest strangers, collapsed to one
    ID, going forward only.
    """

    __tablename__ = "customer_identifiers"

    system: Mapped[str] = mapped_column(String(100), primary_key=True)
    raw_identifier: Mapped[str] = mapped_column(String(500), primary_key=True)
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.canonical_id"), nullable=False, index=True
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped[CustomerAccount] = relationship(back_populates="identifiers")


class AttributedCall(Base):
    """The Ledger itself — one row per model call. Append-only: rows are
    never updated or deleted. Past history can't be rewritten to fix a
    gap; the fix is to make sure the same gap never happens again going
    forward.
    """

    __tablename__ = "attributed_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False, default=1)
    system: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cache_write_input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    bedrock_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed', 'degraded', 'blocked')", name="ck_call_status"
        ),
        Index("ix_calls_system_decision_created", "system", "decision_type", "created_at"),
        Index("ix_calls_customer_created", "customer_id", "created_at"),
    )


class BudgetEvent(Base):
    """Every ceiling breach, degrade, and calendar-override application —
    logged distinguishably from ordinary traffic. Without this, a flat
    spend line on a dashboard looks identical whether it's a demand drop
    or an enforced stop, and only cross-referencing by hand tells them
    apart.
    """

    __tablename__ = "budget_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    system: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    spent_today: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    ceiling: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('hard_stop', 'degrade', 'calendar_override_applied', "
            "'fail_open', 'fail_closed')",
            name="ck_event_type",
        ),
    )


class ReconciliationRun(Base):
    """Estimate-vs-invoice comparison at model/usage-type grain, per month.
    The real-time estimate and the actual invoice are two different
    questions — this table is where the gap between them is recorded, not
    smoothed over.
    """

    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    usage_type: Mapped[str] = mapped_column(String(100), nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    actual_cost: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    gap_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "period_start", "period_end", "model_id", "usage_type", name="uq_reconciliation_period"
        ),
    )
