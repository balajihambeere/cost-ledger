"use client";

import { useEffect, useMemo, useState } from "react";
import { Wallet, PhoneCall, Layers3, TrendingUp } from "lucide-react";
import { getLedgerSummary, LedgerSummary, ApiError } from "@/lib/api";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function fmtMoney(v: string | number): string {
  const n = Number(v);
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

function fmtInt(n: number): string {
  return n.toLocaleString();
}

export default function LedgerPage() {
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const [start, setStart] = useState(isoDate(weekAgo));
  const [end, setEnd] = useState(isoDate(today));
  const [summary, setSummary] = useState<LedgerSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getLedgerSummary(start, end)
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load ledger"))
      .finally(() => setLoading(false));
  }, [start, end]);

  const stats = useMemo(() => {
    if (!summary) return null;
    const totalCalls = summary.rows.reduce((sum, r) => sum + r.calls, 0);
    const totalDecisions = summary.rows.reduce((sum, r) => sum + r.successful_decisions, 0);
    const systems = new Set(summary.rows.map((r) => r.system)).size;
    return { totalCalls, totalDecisions, systems };
  }, [summary]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Attributed spend</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            What every rupee bought — by system and decision type, not blended into &ldquo;the AI
            stack.&rdquo; Cost per decision counts every retry attempt, divided only by the
            decisions that actually succeeded.
          </p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Start
            </label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-foreground focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              End
            </label>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm text-foreground focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </div>
        </div>
      </div>

      {error && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}

      {loading && <StatSkeleton />}

      {summary && !loading && stats && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={Wallet}
            iconClass="bg-indigo-500/10 text-indigo-400"
            label="Grand total"
            value={`₹${fmtMoney(summary.grand_total_cost)}`}
          />
          <StatCard
            icon={PhoneCall}
            iconClass="bg-sky-500/10 text-sky-400"
            label="Total calls"
            value={fmtInt(stats.totalCalls)}
          />
          <StatCard
            icon={TrendingUp}
            iconClass="bg-emerald-500/10 text-emerald-400"
            label="Successful decisions"
            value={fmtInt(stats.totalDecisions)}
          />
          <StatCard
            icon={Layers3}
            iconClass="bg-violet-500/10 text-violet-400"
            label="Systems reporting"
            value={fmtInt(stats.systems)}
          />
        </div>
      )}

      {summary && !loading && (
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-raised/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">System</th>
                  <th className="px-5 py-3 font-medium">Decision type</th>
                  <th className="px-5 py-3 text-right font-medium">Calls</th>
                  <th className="px-5 py-3 text-right font-medium">Successful decisions</th>
                  <th className="px-5 py-3 text-right font-medium">Total cost</th>
                  <th className="px-5 py-3 text-right font-medium">Cost / decision</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {summary.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center text-muted-foreground">
                      No attributed spend in this range.
                    </td>
                  </tr>
                )}
                {summary.rows.map((row) => (
                  <tr
                    key={`${row.system}-${row.decision_type}`}
                    className="transition hover:bg-surface-raised/60"
                  >
                    <td className="px-5 py-3">
                      <span className="inline-flex items-center rounded-md bg-surface-raised px-2 py-0.5 text-xs font-medium text-foreground">
                        {row.system}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs text-muted">{row.decision_type}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-muted">{row.calls}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-muted">
                      {row.successful_decisions}
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums font-medium text-foreground">
                      ₹{fmtMoney(row.total_cost)}
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-muted">
                      {row.cost_per_decision ? `₹${fmtMoney(row.cost_per_decision)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon: Icon,
  iconClass,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  iconClass: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-sm">
      <div className={`mb-3 flex h-9 w-9 items-center justify-center rounded-lg ${iconClass}`}>
        <Icon className="h-4.5 w-4.5" strokeWidth={2} />
      </div>
      <div className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="animate-pulse rounded-xl border border-border bg-surface p-5">
          <div className="mb-3 h-9 w-9 rounded-lg bg-surface-raised" />
          <div className="h-7 w-20 rounded bg-surface-raised" />
          <div className="mt-2 h-3 w-24 rounded bg-surface-raised" />
        </div>
      ))}
    </div>
  );
}
