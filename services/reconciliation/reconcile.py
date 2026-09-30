"""Reconciliation.

The real-time cost estimate this system produces is an estimate, and it
stays an estimate — it's reconciled against the actual bill every month,
at the model and usage-type level, because that's the finest grain the
invoice itself gives us.

AWS's own documentation (VERIFIED, fetched live during this build) confirms
the grain: "Neither classic CUR nor CUR 2.0 includes a per-request
identifier on its line items. Both aggregate cost by usage type over an
hour or a day." This module reconciles at exactly that grain — per
(model_id, usage_type), never per call — against an invoice source file in
a documented CSV shape (see database/seed/sample_invoice.csv), standing in
for a real CUR export until this is pointed at one.

Token-level usage types: 'input', 'output', 'cache_write', 'cache_read' —
finer than AWS's own real usage-type strings, but the same idea: which
*kind* of usage generated the cost, not which call.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_core.db.models import ReconciliationRun
from ledger_core.rate_card import current_rate

MILLION = Decimal(1_000_000)

_ESTIMATE_SQL = text(
    """
    SELECT model_id,
           COALESCE(SUM(input_tokens), 0) AS input_tokens,
           COALESCE(SUM(output_tokens), 0) AS output_tokens,
           COALESCE(SUM(cache_write_input_tokens), 0) AS cache_write_tokens,
           COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_tokens
    FROM attributed_calls
    WHERE created_at >= :start AND created_at < :end AND status != 'blocked'
    GROUP BY model_id
    """
)


@dataclass
class InvoiceRow:
    model_id: str
    usage_type: str  # input | output | cache_write | cache_read
    actual_cost: Decimal


def load_invoice_csv(path: str) -> list[InvoiceRow]:
    """Loads the documented CSV shape: model_id,usage_type,actual_cost"""
    rows: list[InvoiceRow] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                InvoiceRow(
                    model_id=row["model_id"],
                    usage_type=row["usage_type"],
                    actual_cost=Decimal(row["actual_cost"]),
                )
            )
    return rows


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


async def run_reconciliation(
    session: AsyncSession,
    *,
    period_start: date,
    period_end: date,
    invoice_rows: list[InvoiceRow],
    source_file: str,
) -> list[ReconciliationRun]:
    start_dt = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    estimate_result = await session.execute(_ESTIMATE_SQL, {"start": start_dt, "end": end_dt})

    estimated: dict[tuple[str, str], Decimal] = {}
    for row in estimate_result:
        rate = await current_rate(session, row.model_id)
        input_rate = Decimal(str(rate.input_rate_per_million))
        output_rate = Decimal(str(rate.output_rate_per_million))
        cache_write_mult = Decimal(str(rate.cache_write_multiplier))
        cache_read_mult = Decimal(str(rate.cache_read_multiplier))

        estimated[(row.model_id, "input")] = Decimal(row.input_tokens) * input_rate / MILLION
        estimated[(row.model_id, "output")] = Decimal(row.output_tokens) * output_rate / MILLION
        estimated[(row.model_id, "cache_write")] = (
            Decimal(row.cache_write_tokens) * input_rate * cache_write_mult / MILLION
        )
        estimated[(row.model_id, "cache_read")] = (
            Decimal(row.cache_read_tokens) * input_rate * cache_read_mult / MILLION
        )

    results: list[ReconciliationRun] = []
    for invoice_row in invoice_rows:
        key = (invoice_row.model_id, invoice_row.usage_type)
        est = estimated.get(key, Decimal(0))
        actual = invoice_row.actual_cost
        gap_pct = ((est - actual) / actual * 100) if actual != 0 else Decimal(0)

        run = ReconciliationRun(
            period_start=period_start,
            period_end=period_end,
            model_id=invoice_row.model_id,
            usage_type=invoice_row.usage_type,
            estimated_cost=_round(est),
            actual_cost=_round(actual),
            gap_pct=_round(gap_pct),
            source_file=source_file,
        )
        session.add(run)
        results.append(run)

    await session.flush()
    return results
