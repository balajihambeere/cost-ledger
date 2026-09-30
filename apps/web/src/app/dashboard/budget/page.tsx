"use client";

import { useEffect, useState } from "react";
import { ShieldAlert, TrendingDown, CalendarClock, ShieldOff, ShieldCheck } from "lucide-react";
import {
  getConfigs,
  getBudgetEvents,
  getBudgetStatus,
  DecisionTypeConfig,
  BudgetEvent,
  BudgetStatus,
  ApiError,
} from "@/lib/api";

function fmtMoney(v: string): string {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

const EVENT_META: Record<string, { icon: typeof ShieldAlert; className: string }> = {
  hard_stop: { icon: ShieldAlert, className: "bg-red-500/10 text-red-400" },
  fail_closed: { icon: ShieldOff, className: "bg-red-500/10 text-red-400" },
  degrade: { icon: TrendingDown, className: "bg-amber-500/10 text-amber-400" },
  fail_open: { icon: TrendingDown, className: "bg-amber-500/10 text-amber-400" },
  calendar_override_applied: { icon: CalendarClock, className: "bg-indigo-500/10 text-indigo-400" },
};

function eventMeta(eventType: string) {
  return EVENT_META[eventType] ?? { icon: ShieldCheck, className: "bg-zinc-500/10 text-zinc-400" };
}

function usageBarClass(pct: number): string {
  if (pct >= 100) return "bg-red-500";
  if (pct >= 75) return "bg-amber-500";
  return "bg-emerald-500";
}

export default function BudgetPage() {
  const [configs, setConfigs] = useState<DecisionTypeConfig[]>([]);
  const [events, setEvents] = useState<BudgetEvent[]>([]);
  const [statuses, setStatuses] = useState<Record<string, BudgetStatus>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([getConfigs(), getBudgetEvents()])
      .then(([cfgs, evts]) => {
        setConfigs(cfgs);
        setEvents(evts);
        return Promise.all(
          cfgs.map((c) =>
            getBudgetStatus(c.system, c.decision_type)
              .then((s) => [`${c.system}/${c.decision_type}`, s] as const)
              .catch(() => null)
          )
        );
      })
      .then((pairs) => {
        const map: Record<string, BudgetStatus> = {};
        for (const pair of pairs) {
          if (pair) map[pair[0]] = pair[1];
        }
        setStatuses(map);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load budget data"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-10">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Budget</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          A ceiling that sees a call before it happens, with a behavior chosen deliberately per
          decision type — hard stop for background work, graceful degradation for anything a real
          customer is waiting on.
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}
      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!loading && (
        <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-raised/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">System</th>
                  <th className="px-5 py-3 font-medium">Decision type</th>
                  <th className="px-5 py-3 font-medium">Mode</th>
                  <th className="px-5 py-3 font-medium">Model</th>
                  <th className="px-5 py-3 text-right font-medium">Today&apos;s spend</th>
                  <th className="px-5 py-3 text-right font-medium">Ceiling</th>
                  <th className="px-5 py-3 font-medium">Used</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {configs.map((c) => {
                  const status = statuses[`${c.system}/${c.decision_type}`];
                  const pctNum = status ? Number(status.percent_used) : null;
                  return (
                    <tr key={`${c.system}-${c.decision_type}`} className="transition hover:bg-surface-raised/60">
                      <td className="px-5 py-3">
                        <span className="inline-flex items-center rounded-md bg-surface-raised px-2 py-0.5 text-xs font-medium text-foreground">
                          {c.system}
                        </span>
                      </td>
                      <td className="px-5 py-3 font-mono text-xs text-muted">{c.decision_type}</td>
                      <td className="px-5 py-3">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            c.enforcement_mode === "hard_stop"
                              ? "bg-zinc-500/10 text-zinc-400"
                              : "bg-emerald-500/10 text-emerald-400"
                          }`}
                        >
                          {c.enforcement_mode}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-xs text-muted-foreground">
                        {c.routing_model_id}
                        {c.fallback_model_id && (
                          <span className="block text-muted-foreground/70">&#8618; {c.fallback_model_id}</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums font-medium text-foreground">
                        {status ? `₹${fmtMoney(status.spent_today)}` : "—"}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums text-muted">
                        ₹{fmtMoney(c.daily_ceiling)}
                        {status?.ceiling_source === "calendar_override" && (
                          <span className="ml-1.5 rounded-full bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-medium text-indigo-400">
                            override
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {pctNum !== null ? (
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-raised">
                              <div
                                className={`h-full rounded-full ${usageBarClass(pctNum)}`}
                                style={{ width: `${Math.min(pctNum, 100)}%` }}
                              />
                            </div>
                            <span
                              className={`text-xs tabular-nums ${
                                pctNum >= 100
                                  ? "font-semibold text-red-400"
                                  : pctNum >= 75
                                    ? "font-medium text-amber-400"
                                    : "text-muted-foreground"
                              }`}
                            >
                              {pctNum.toFixed(1)}%
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {configs.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-5 py-10 text-center text-muted-foreground">
                      No decision types configured yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {!loading && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-foreground">
            Recent budget events
            <span className="ml-2 font-normal text-muted-foreground">
              — every hard stop, degrade, and fail-safe, logged distinguishably from ordinary traffic
            </span>
          </h3>
          <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border bg-surface-raised/60 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium">When</th>
                    <th className="px-5 py-3 font-medium">System / decision type</th>
                    <th className="px-5 py-3 font-medium">Event</th>
                    <th className="px-5 py-3 text-right font-medium">Spent</th>
                    <th className="px-5 py-3 text-right font-medium">Ceiling</th>
                    <th className="px-5 py-3 font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {events.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-5 py-10 text-center text-muted-foreground">
                        No budget events yet — nothing has hit a ceiling.
                      </td>
                    </tr>
                  )}
                  {events.map((ev) => {
                    const meta = eventMeta(ev.event_type);
                    const Icon = meta.icon;
                    return (
                      <tr key={ev.id} className="transition hover:bg-surface-raised/60">
                        <td className="px-5 py-3 text-xs text-muted-foreground">
                          {new Date(ev.occurred_at).toLocaleString()}
                        </td>
                        <td className="px-5 py-3 text-muted">
                          {ev.system}/{ev.decision_type}
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${meta.className}`}
                          >
                            <Icon className="h-3 w-3" strokeWidth={2.5} />
                            {ev.event_type}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-right tabular-nums text-muted">
                          ₹{fmtMoney(ev.spent_today)}
                        </td>
                        <td className="px-5 py-3 text-right tabular-nums text-muted">
                          ₹{fmtMoney(ev.ceiling)}
                        </td>
                        <td className="px-5 py-3 text-xs text-muted-foreground">{ev.detail || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
