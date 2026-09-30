// Thin typed client for the Cost Ledger API. Every read/admin endpoint
// under /v1 requires the JWT this app stores after login (see auth.ts) —
// matches the single-admin-account model documented in
// docs/architecture.md (no multi-user system exists yet).

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:58000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("costledger_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
  });
  if (!res.ok) throw new ApiError(res.status, "Invalid credentials");
  const data = await res.json();
  return data.access_token as string;
}

export interface LedgerRow {
  system: string;
  decision_type: string;
  calls: number;
  total_cost: string;
  successful_decisions: number;
  cost_per_decision: string | null;
}

export interface LedgerSummary {
  start: string;
  end: string;
  rows: LedgerRow[];
  grand_total_cost: string;
}

export function getLedgerSummary(start: string, end: string): Promise<LedgerSummary> {
  return request(`/v1/ledger/summary?start=${start}&end=${end}`);
}

export interface CustomerSpendRow {
  system: string;
  decision_type: string;
  calls: number;
  cost: string;
}

export interface CustomerSpend {
  canonical_id: string;
  rows: CustomerSpendRow[];
  total_cost: string;
}

export function getCustomerSpend(canonicalId: string): Promise<CustomerSpend> {
  return request(`/v1/ledger/customers/${canonicalId}`);
}

export interface DecisionTypeConfig {
  system: string;
  decision_type: string;
  enforcement_mode: "hard_stop" | "degrade";
  daily_ceiling: string;
  currency: string;
  fallback_model_id: string | null;
  routing_model_id: string;
  reservation_estimate: string;
  updated_at: string;
}

export function getConfigs(): Promise<DecisionTypeConfig[]> {
  return request("/v1/budget/configs");
}

export function upsertConfig(config: Omit<DecisionTypeConfig, "updated_at">): Promise<DecisionTypeConfig> {
  return request("/v1/budget/configs", { method: "PUT", body: JSON.stringify(config) });
}

export interface BudgetStatus {
  system: string;
  decision_type: string;
  date: string;
  spent_today: string;
  ceiling: string;
  ceiling_source: "default" | "calendar_override";
  percent_used: string;
}

export function getBudgetStatus(system: string, decisionType: string): Promise<BudgetStatus> {
  return request(`/v1/budget/status?system=${system}&decision_type=${decisionType}`);
}

export interface BudgetEvent {
  id: string;
  system: string;
  decision_type: string;
  event_type: string;
  spent_today: string;
  ceiling: string;
  decision_id: string | null;
  detail: string | null;
  occurred_at: string;
}

export function getBudgetEvents(system?: string): Promise<BudgetEvent[]> {
  const qs = system ? `?system=${system}` : "";
  return request(`/v1/budget/events${qs}`);
}

export interface CalendarOverride {
  id: string;
  system: string;
  decision_type: string;
  override_date: string;
  ceiling: string;
  reason: string;
  approved_by: string;
  created_at: string;
}

export function getCalendarOverrides(): Promise<CalendarOverride[]> {
  return request("/v1/budget/calendar-overrides");
}
