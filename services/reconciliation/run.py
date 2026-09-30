"""CLI entrypoint for the monthly reconciliation job. Intended to be run on
a schedule (cron, or manually) against a real CUR export once one exists;
see docs/operations.md.

Usage:
    python -m reconciliation.run --start 2026-09-01 --end 2026-09-30 \
        --invoice-csv /path/to/invoice.csv
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date

from ledger_core.db.base import init_engine, session_scope

from reconciliation.reconcile import load_invoice_csv, run_reconciliation


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Cost Ledger reconciliation")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--invoice-csv", required=True)
    args = parser.parse_args()

    database_url = os.environ["DATABASE_URL"]
    init_engine(database_url)

    invoice_rows = load_invoice_csv(args.invoice_csv)

    async with session_scope() as session:
        results = await run_reconciliation(
            session,
            period_start=args.start,
            period_end=args.end,
            invoice_rows=invoice_rows,
            source_file=args.invoice_csv,
        )

    for r in results:
        flag = " ** " if abs(r.gap_pct) >= 10 else "    "
        print(f"{flag}{r.model_id:35s} {r.usage_type:12s} "
              f"est={r.estimated_cost:>12} actual={r.actual_cost:>12} gap={r.gap_pct:>7}%")


if __name__ == "__main__":
    asyncio.run(main())
