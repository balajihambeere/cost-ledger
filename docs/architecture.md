# Cost Ledger — Architecture & Requirements

Status legend used throughout this document: `VERIFIED` (tested/confirmed), `REQUIREMENT` (a functional requirement this system is built to satisfy), `ENGINEERING-DECISION` (chosen during this build), `ASSUMPTION` (required because information was missing), `UNKNOWN` (not currently established).

## 1. What this application is

An AI system with real spending power (model calls, retries, agent runs) and no accounting behind any of it is a real, common failure mode: nobody has tied a rupee of spend to a decision, a customer, or an outcome, and the first anyone hears about a problem is an invoice three times the forecast. This application is a real cost-management system that prevents that, covering the first two stages of a four-stage cost-management cycle — **Attribute → Budget → Route → Reclaim**:

- **Attribute** — force every model call through a shared client that requires a `system` and `decision_type` before it will run; tag the call via Bedrock's real `requestMetadata` mechanism; compute a per-call cost estimate from real token usage; group retry chains under one `decision_id` so cost is measured **per decision**, not per call; resolve each system's local customer identifier to one canonical ID; reconcile the estimate against actual invoice data monthly.
- **Budget** — a pre-spend ceiling check inside the same client, backed by a fast running total (not a billing system that lags a day), with two enforcement behaviors chosen per decision type (hard-stop for background work, graceful degradation for customer-facing work), plus calendar-based ceiling overrides for known high-demand dates.

**Route** (choosing the cheapest model that still clears a quality bar) and **Reclaim** (finding and reclaiming waste after the fact) are real, related problems but are **out of scope for this build** — building them here would be scope invention beyond what was actually asked for.

## 2. Concept map

| Concept | What it means | Application component |
| --- | --- | --- |
| Unattributed AI spend (the problem) | An AI system spends money with no accounting tying spend to a decision/customer/outcome | The problem this whole system exists to prevent |
| Resource-level cost tags are insufficient | AWS cost allocation tags describe a resource (an endpoint), not an individual call | Documented as a rejected approach; not built |
| Bedrock request metadata | Per-call tags via `requestMetadata` (Converse) / `X-Amzn-Bedrock-Request-Metadata` header (InvokeModel); ≤16 entries; only recorded if invocation logging is enabled in-Region; not enforced by AWS | `packages/ledger_core/bedrock_client.py` |
| Convention-based tagging silently fails | A team's calls can go untagged indefinitely because of a regional logging setting nobody knew to check, with no error, no warning | Solved by making the wrapper the *only* path to Bedrock — no code path can skip tagging |
| Shared wrapper client | One internal client every system calls instead of reaching Bedrock directly; tagging logic lives inside it | `packages/ledger_core/wrapper.py` (`call_model`) |
| Per-call cost from token usage | `usage.inputTokens` / `usage.outputTokens` × a rate card, computed the moment the call finishes | `packages/ledger_core/cost.py` |
| Estimate vs. invoice reconciliation | The estimate is a sticker-rate estimate, reconciled against the real invoice monthly at model/usage-type grain; a real gap between the two must be tracked, not hidden | `services/reconciliation/` |
| Cache write/read multipliers | 5-minute cache write = 1.25× base input; cache read = 0.1× base input | `cost.py` — `VERIFIED` against `claude.com/pricing`, Sept 2026 |
| Cost per decision, not per call | Retries must be summed under one `decision_id`; a cheaper model can cost more per decision once retries/overhead are counted | `wrapper.py` decision-chain grouping; `ledger` query layer |
| Bounded pilot before large/automatable spend | Large or automatable proposals earn a small, bounded, measured pilot before full funding — not a benchmark, not a vibe | An organizational practice this system's real numbers make possible; deliberately not a UI feature — see §3.1 |
| AWS Budgets actions are too slow | Cost Explorer refreshes ≥24h; not a pre-spend ceiling | Documented as an account-wide backstop layer only, not the primary mechanism (not provisioned in this build — no AWS account) |
| Pre-spend ceiling in the wrapper | Check a running total *before* the call goes out; block if it would cross the ceiling | `packages/ledger_core/budget.py` — Redis-backed running totals |
| A ceiling isn't one thing | Same number/behavior for every decision type is itself a failure mode; customer-facing decisions need graceful degradation, not a hard stop | Per-decision-type `enforcement_mode` (`hard_stop` \| `degrade`) + fallback model config |
| Calendar-aware ceilings | A fixed daily number is wrong on a day everyone planned to be unusual (a sale, a promotion) | `ceiling_calendar_overrides` table |
| Identity resolution | Each system's local customer ID (email hash / order ID / ticket ID) must resolve to one canonical ID before tagging, or per-customer queries silently under-count | `packages/ledger_core/identity.py` |
| No retroactive fix | Pre-resolution history stays honestly unlinkable — this system refuses to fake a retroactive join | `identity_map` table only applies going forward; documented limitation, not "fixed" |

## 3. Requirements

### 3.1 Functional (`REQUIREMENT` unless noted)

- Every model call must pass `system`, `decision_type`, and a raw customer identifier before it can execute (no code path bypasses this).
- Every call is tagged via Bedrock `requestMetadata` with the canonical `system`, `decision_type`, `decision_id`, and resolved `customer_id`.
- Every call's cost is computed from real token usage (`inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheWriteInputTokens`) against a versioned, configurable rate card — never hardcoded as a permanent truth, since prices change (`ENGINEERING-DECISION`, in response to the fact that sticker prices are a moving target).
- Retry attempts at the same underlying task share one `decision_id`; the Ledger can report both cost-per-call and cost-per-decision.
- A per-system, per-decision-type daily spend ceiling can be configured; a call that would cross it is evaluated *before* the request reaches Bedrock.
- Ceiling behavior is configurable per decision type: `hard_stop` (raise, alert on-call, no charge incurred) or `degrade` (fall back to a cheaper configured model, log the degradation, no customer-facing failure).
- A calendar of date-scoped ceiling overrides can be configured and takes precedence over the default daily ceiling on matching dates.
- Any system's local customer identifier can be resolved to one canonical customer ID; unresolved identifiers are tagged `unresolved:<system>:<raw_id>` rather than silently dropped or guessed via fuzzy matching (`REQUIREMENT` — fuzzy/email-based matching is explicitly rejected as untrustworthy; it can silently merge two unrelated customers who happen to share a contact detail).
- A report can be produced for: total attributed spend by system × decision_type over a date range; cost per decision (successful decisions only in the denominator); spend for one canonical customer across all systems; ceiling status (current spend vs. ceiling) per system × decision_type; reconciliation gap between estimated and actual invoice cost, at model/usage-type grain, per month.
- Reconciliation against a real invoice is a distinct, explicit process — the estimate is never presented as the bill.
- **Bounded pilots for large/automatable spend proposals**: this system does not automate this — it's an organizational practice, not a feature — but it's worth documenting because it's the reason cost-per-decision and per-customer spend reporting exist at all. Before committing to a large or automatable proposal (a new system, a continuous-retraining pipeline, anything that could compound quietly), run it as a bounded pilot: narrow scope (one system, one decision type, a fixed schedule rather than a continuous trigger), routed through the wrapper so every call is attributed and budgeted from the start. Let it run long enough to produce real numbers, then compare real cost against real return before committing further. That's a conversation a person has, informed by this system's real numbers — not an API this system exposes.

### 3.2 Non-functional (`ENGINEERING-DECISION` unless noted)

- **Security**: the Ledger holds real cost and customer-linkage data; API requires authentication (API key for service-to-service, JWT for the dashboard's human users); no raw PII (email, phone) is ever written into `requestMetadata` (`VERIFIED` against AWS's own guidance: "avoid placing PII... in request metadata" — only the opaque canonical ID is tagged); secrets via environment variables, never committed.
- **Reliability**: a Bedrock/network failure must not silently lose attribution data (the call and its cost are recorded transactionally, or not attempted); the budget check must be safe under concurrent calls from multiple wrapper instances (atomic Redis increment, not read-then-write); a Redis outage must fail safe in a *declared* direction (see §7 — a real design decision this document makes explicitly, since no external spec resolves it).
- **Observability**: structured (JSON) logs for every wrapper call and every ceiling decision; `/health` and `/ready` endpoints; a `/metrics` endpoint; every ceiling breach and every degrade event is logged distinguishably from ordinary traffic (a flat spend line on a dashboard looks identical whether it's a demand drop or an enforced stop unless this distinction is made explicit).
- **Performance**: the pre-spend ceiling check must be fast enough not to materially change customer-facing latency — Redis-backed, target < 5 ms for the check itself, `ASSUMPTION` since no external spec states a number; chosen because the alternative reference points (a ≥24-hour-lag billing API, an ~11-minute human-paged alert) make "milliseconds" the obvious bar for something that's actually meant to act *before* spend happens.
- **Data retention**: the ledger is an append-only record of attributed spend; no automatic deletion is implemented in this build (`UNKNOWN` — retention policy and the applicable data-protection regime for a real deployment are not addressed here; flagged for the user to decide before production use).

### 3.3 Technical (`REQUIREMENT`: Python, a cost-attribution pipeline tying spend to decision/customer/system, and per-call cost logging and tagging. Everything below that line is an `ENGINEERING-DECISION`.)

- Backend language: Python 3.12 (`REQUIREMENT`).
- API framework: FastAPI (async, typed, OpenAPI docs generated for free) — `ENGINEERING-DECISION`. Alternative considered: Flask (simpler, but no native async/typed validation — rejected because the wrapper's own concurrency requirement makes async a real fit, not a fashion choice).
- Ledger store: PostgreSQL — `ENGINEERING-DECISION`; a durable, queryable, append-only ledger is exactly what a real-time spend ledger needs, and in-memory storage is never appropriate for persistent financial-style data.
- Fast running-total store: Redis — `ENGINEERING-DECISION`. The requirement is precise (a fast, shared store every instance of the wrapper can read and update in milliseconds) without naming a technology; Redis's atomic `INCRBYFLOAT`/Lua scripting is the direct real-world match for "check-and-increment without a race condition."
- Bedrock access: `boto3`, behind a small `BedrockClient` Protocol with two implementations — a real one (`boto3` `bedrock-runtime`) and a `MockBedrockClient` (deterministic token usage, no network) — `ENGINEERING-DECISION`, required because this sandbox has no AWS credentials; the interface is the real `boto3` Converse request/response shape (`VERIFIED` against AWS's API reference), so swapping in real credentials requires no code change, only configuration.
- Frontend: Next.js (App Router) + TypeScript + Tailwind CSS — `ENGINEERING-DECISION` (specified directly by the user during this build, superseding an earlier plain-Vite draft). Reproduces a real-time spend report: spend by system/decision type, per-customer lookup, budget status.
- Migrations: Alembic — `ENGINEERING-DECISION`.
- Background/scheduled job (reconciliation): a standalone script runnable via cron or manually — `ENGINEERING-DECISION`; no job queue framework introduced because this build has exactly one recurring job (monthly reconciliation) and a queue would be unjustified complexity.
- Containerization: Docker + Docker Compose for local/dev, per the user's explicit choice — real AWS deployment (`ap-south-1`) is documented but not provisioned, since this sandbox has no AWS account to provision or validate against.
- Auth: API-key (service-to-service, e.g. simulated assistant/logistics/etc. callers) + JWT (dashboard human users) — `ENGINEERING-DECISION`, a minimum viable auth model for this build.

## 4. Architecture

![Cost Ledger system architecture: six simulated systems and the Next.js dashboard call the api service (FastAPI) over HTTP; the api service's ledger_core.wrapper is the only path to AWS Bedrock, resolving identity, checking the Redis budget ceiling, calling the model, and recording each call to the PostgreSQL ledger; a separate reconciliation job reads the ledger plus an invoice CSV and writes back the estimate-vs-actual gap.](assets/architecture-diagram.svg)

*Icons: AWS Architecture Icons (Fargate, Amazon RDS, Amazon ElastiCache, Amazon Bedrock) and AWS Resource Icons (general-purpose glyphs), from the official icon package — [`docs/assets/icons/`](assets/icons/), regenerated via [`docs/assets/gen_architecture_diagram.py`](assets/gen_architecture_diagram.py).*

Every component exists because a specific real failure mode requires it:

- The wrapper is the single choke point because convention-based tagging (an expectation engineers "remember" to follow) silently fails.
- Redis exists because a 24-hour-lag store (AWS Budgets/Cost Explorer) and an ~11-minute human-reaction alert both fail to act *before* spend happens.
- The `decision_id` grouping exists because per-call cost hides the real comparison between two options once retries/overhead are counted.
- The identity map exists because per-system-local IDs fail to join without one.
- Reconciliation is a separate, explicit process (not folded into the live estimate) because the real-time estimate and the actual invoice are genuinely two different questions.

## 5. Repository structure

```text
cost-ledger/
├── apps/
│   └── web/                    # Next.js + Tailwind dashboard (real-time spend report)
├── services/
│   ├── api/                    # FastAPI app (routers, auth, DI)
│   └── reconciliation/         # monthly reconciliation job
│       # (ceiling evaluation/calendar-overrides/degrade logic lives in
│       #  packages/ledger_core/budget.py, not a separate service — every
│       #  wrapper call needs it inline, synchronously, before the Bedrock
│       #  call goes out; a separate microservice would just add a network
│       #  hop on the hot path for no benefit)
├── packages/
│   └── ledger_core/            # the shared wrapper: bedrock_client, cost, identity, wrapper, models
├── database/
│   ├── migrations/             # Alembic
│   └── seed/                   # sample rate cards, demo ceilings, identity fixtures
├── simulation/                 # six-system demo traffic generator replaying real scenarios
├── tests/
│   ├── unit/
│   ├── integration/
│   └── scenarios/               # retry-storm, seasonal-demand-spike, redteam-drill, cross-system-customer-query
├── docs/
│   ├── architecture.md          # this file
│   ├── concept-mapping.md
│   ├── api.md
│   ├── operations.md
│   └── production-readiness.md
├── scripts/
├── .env.example
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 6. Implementation plan (phased, tested after each phase)

1. Repo skeleton, Docker Compose, config.
2. Database schema + migrations.
3. `ledger_core`: Bedrock client abstraction, cost engine, identity resolution.
4. Budget engine (Redis-backed ceilings, degrade/hard-stop, calendar overrides).
5. Wrapper (`call_model`) wiring all of the above together — unit-tested with the mock client.
6. FastAPI backend (ledger queries, budget config, identity, reconciliation trigger, auth, health).
7. Reconciliation job.
8. Simulation harness reproducing real-world scenarios (retry storm, red-team drill, seasonal demand spike, cross-system customer query).
9. Next.js dashboard.
10. Full test suite (unit, integration, scenario).
11. Docs (README, concept mapping, API docs, ops runbook, production-readiness checklist).
12. End-to-end validation via Docker Compose (`docker compose up`, run simulation, verify dashboard shows real numbers) — run and results recorded honestly, not asserted.

## 7. Unknowns, assumptions, and open questions (do not guess past these)

- `UNKNOWN`: Redis-outage failure direction. Failing open (allow the call) reintroduces the original unattributed-spend risk; failing closed (block everything) turns an infra blip into an outage for every customer-facing decision type. **Decision for this build**: fail open for `degrade`-mode decision types (protects customers — customer-facing failure is itself a real, measured cost) and fail closed for `hard_stop`-mode decision types (protects the business — an unwatched background spend is the larger risk there), logged loudly either way. This is an `ENGINEERING-DECISION`, not something externally specified — documented so it can be revisited.
- `UNKNOWN`: real per-token rate card beyond Sonnet 5 / Haiku 4.5, and how the rate card is kept current in production (manual update vs. an API sync). Built as a versioned, editable config, not hardcoded.
- `UNKNOWN`: data retention / compliance regime applicable to a real deployment (the ledger links spend to real customers). Flagged, not decided.
- `ASSUMPTION`: 5 ms as the ceiling-check performance bar (see §3.2) — reasonable given the reference contrast points, not a number derived from a measured requirement.
- Route (model routing/efficiency) and Reclaim (waste detection) are intentionally **not built** — out of scope for this system as currently defined.
