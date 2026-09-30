"use client";

import { FormEvent, useState } from "react";
import { Search, UserSearch, Info } from "lucide-react";
import { getCustomerSpend, CustomerSpend, ApiError } from "@/lib/api";

function fmtMoney(v: string): string {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

export default function CustomersPage() {
  const [canonicalId, setCanonicalId] = useState("");
  const [spend, setSpend] = useState<CustomerSpend | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canonicalId.trim()) return;
    setLoading(true);
    setError(null);
    setSpend(null);
    try {
      setSpend(await getCustomerSpend(canonicalId.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? "Could not find that customer." : "Failed to load spend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Customer lookup</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Answered honestly: what did every AI-driven decision for one real customer actually
          cost, across every system that touched them — not a company-wide average.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-3">
        <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={canonicalId}
            onChange={(e) => setCanonicalId(e.target.value)}
            placeholder="Canonical customer ID (UUID)"
            className="w-full rounded-lg border border-border bg-surface py-2.5 pl-9 pr-3 text-sm font-mono text-foreground placeholder:text-muted-foreground focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="shrink-0 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-indigo-950/30 transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Looking up…" : "Look up"}
        </button>
      </form>

      {error && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      {!spend && !error && !loading && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center">
          <UserSearch className="h-8 w-8 text-muted-foreground" strokeWidth={1.5} />
          <p className="mt-3 text-sm text-muted-foreground">
            Enter a canonical customer ID above to see their attributed spend.
          </p>
        </div>
      )}

      {spend && (
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-raised/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">System</th>
                  <th className="px-5 py-3 font-medium">Decision type</th>
                  <th className="px-5 py-3 text-right font-medium">Calls</th>
                  <th className="px-5 py-3 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {spend.rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-5 py-10">
                      <div className="mx-auto flex max-w-md items-start gap-2.5 text-center">
                        <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        <p className="text-left text-muted-foreground">
                          No attributed spend for this customer — either they haven&apos;t been
                          active, or their activity predates identity resolution being linked
                          (this is honest, not a bug — pre-link history stays unjoinable by
                          design).
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
                {spend.rows.map((row) => (
                  <tr key={`${row.system}-${row.decision_type}`} className="transition hover:bg-surface-raised/60">
                    <td className="px-5 py-3">
                      <span className="inline-flex items-center rounded-md bg-surface-raised px-2 py-0.5 text-xs font-medium text-foreground">
                        {row.system}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs text-muted">{row.decision_type}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-muted">{row.calls}</td>
                    <td className="px-5 py-3 text-right tabular-nums font-medium text-foreground">
                      ₹{fmtMoney(row.cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
              {spend.rows.length > 0 && (
                <tfoot className="border-t border-border bg-surface-raised/40 font-medium">
                  <tr>
                    <td colSpan={3} className="px-5 py-3 text-right text-muted">
                      Total
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-foreground">
                      ₹{fmtMoney(spend.total_cost)}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
