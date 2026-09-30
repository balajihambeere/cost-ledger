from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class MessageContentBlock(BaseModel):
    text: str


class Message(BaseModel):
    role: str
    content: list[MessageContentBlock]


class CallRequest(BaseModel):
    decision_type: str
    customer_identifier: str = Field(..., description="Raw, system-local customer identifier")
    messages: list[Message]
    system_prompt: str | None = None
    decision_id: uuid.UUID | None = Field(
        None, description="Pass the same decision_id back in for a retry of the same task"
    )
    attempt_number: int = 1


class CallResponse(BaseModel):
    decision_id: uuid.UUID
    attempt_number: int
    status: str
    model_id: str
    output_text: str | None
    cost: Decimal
    customer_id: str
    request_id: str | None


class LedgerRow(BaseModel):
    system: str
    decision_type: str
    calls: int
    total_cost: Decimal
    successful_decisions: int
    cost_per_decision: Decimal | None


class LedgerSummaryResponse(BaseModel):
    start: date
    end: date
    rows: list[LedgerRow]
    grand_total_cost: Decimal


class CustomerSpendRow(BaseModel):
    system: str
    decision_type: str
    calls: int
    cost: Decimal


class CustomerSpendResponse(BaseModel):
    canonical_id: str
    rows: list[CustomerSpendRow]
    total_cost: Decimal


class DecisionTypeConfigIn(BaseModel):
    system: str
    decision_type: str
    enforcement_mode: str
    daily_ceiling: Decimal
    currency: str = "INR"
    fallback_model_id: str | None = None
    routing_model_id: str
    reservation_estimate: Decimal


class DecisionTypeConfigOut(DecisionTypeConfigIn):
    updated_at: datetime


class CalendarOverrideIn(BaseModel):
    system: str
    decision_type: str
    override_date: date
    ceiling: Decimal
    reason: str
    approved_by: str


class CalendarOverrideOut(CalendarOverrideIn):
    id: uuid.UUID
    created_at: datetime


class BudgetStatusResponse(BaseModel):
    system: str
    decision_type: str
    date: date
    spent_today: Decimal
    ceiling: Decimal
    ceiling_source: str  # "default" | "calendar_override"
    percent_used: Decimal


class BudgetEventOut(BaseModel):
    id: uuid.UUID
    system: str
    decision_type: str
    event_type: str
    spent_today: Decimal
    ceiling: Decimal
    decision_id: uuid.UUID | None
    detail: str | None
    occurred_at: datetime


class IdentityLinkRequest(BaseModel):
    system: str
    raw_identifier: str
    canonical_id: uuid.UUID | None = None


class IdentityLinkResponse(BaseModel):
    canonical_id: uuid.UUID


class ReconciliationRowOut(BaseModel):
    model_id: str
    usage_type: str
    estimated_cost: Decimal
    actual_cost: Decimal
    gap_pct: Decimal


class ReconciliationRunResponse(BaseModel):
    period_start: date
    period_end: date
    rows: list[ReconciliationRowOut]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
