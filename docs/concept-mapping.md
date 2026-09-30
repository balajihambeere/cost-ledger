# Concept-to-Code Mapping

Every concept this system implements, where it's actually implemented (not just documented), and what test proves it works.

| Concept | Implementation | Test |
| --- | --- | --- |
| Unattributed AI spend (the problem) | The absence this whole system prevents — see the "before" state described in `docs/architecture.md` §1 | N/A — a problem statement, not a component |
| Resource-level cost tags are the wrong grain | Documented as a rejected approach in `docs/architecture.md` §2; not built | N/A |
| Bedrock request metadata (`requestMetadata`) | `packages/ledger_core/bedrock_client.py::validate_request_metadata`, used by both `BotoBedrockClient` and `MockBedrockClient` | `tests/unit/test_bedrock_client.py::test_valid_metadata_passes`, `test_too_many_entries_rejected`, `test_sixteen_entries_is_the_real_limit_and_is_allowed`, `test_key_too_long_rejected`, `test_value_too_long_rejected` |
| One shared wrapper — no code path can skip tagging | `packages/ledger_core/wrapper.py::call_model` is the only function in this codebase that may call a `BedrockClient`; enforced by code structure (no system imports `bedrock_client` directly) | `tests/integration/test_wrapper.py` (6 tests) exercises the full composition |
| Per-call cost from token usage | `packages/ledger_core/cost.py::compute_cost` | `tests/unit/test_cost.py::test_plain_call_no_cache`, `test_haiku_is_half_sonnet_on_sticker_price_alone` |
| Estimate ≠ invoice; reconcile monthly at model/usage-type grain | `services/reconciliation/reconcile.py::run_reconciliation`, `services/api/app/routers/reconciliation.py` | Manually verified via `database/seed/sample_invoice.csv` through `POST /v1/reconciliation/run`; no automated test (no real invoice source exists to test against — see Unknowns) |
| Cache write (1.25×) / read (0.10×) multipliers | `packages/ledger_core/cost.py::compute_cost` | `tests/unit/test_cost.py::test_cache_write_costs_more_than_plain_input`, `test_cache_read_costs_a_tenth_of_plain_input`, `test_unread_cache_write_is_a_net_loss_vs_no_caching_at_all` |
| Cost per decision, not cost per call | `AttributedCall.decision_id` groups every attempt at one task; `services/api/app/routers/ledger.py::summary` computes `total_cost / successful_decisions` | `tests/integration/test_wrapper.py::test_retries_share_decision_id_and_sum_cost`; end-to-end via `simulation/scenarios.py::retry_storm` |
| Bounded pilot before committing to a large/automatable spend | Deliberately **not** a system feature — it's an organizational practice the Ledger's real numbers make possible. See `docs/architecture.md` §3.1 | N/A by design |
| AWS Budgets actions are too slow for a real ceiling | Documented as a rejected primary mechanism in `docs/architecture.md` §2; a real deployment would still run it as an independent account-wide backstop (not provisioned — no AWS account) | N/A |
| Pre-spend ceiling, checked before the call | `packages/ledger_core/budget.py::evaluate` — Redis-backed atomic reservation, called from `wrapper.call_model` before `bedrock.converse` | `tests/integration/test_budget.py::test_call_under_ceiling_is_allowed`, `test_call_over_ceiling_is_hard_stopped`; live: `simulation/scenarios.py::retry_storm` |
| Reservation released on block/failure | `packages/ledger_core/budget.py::release`, called from `wrapper.py` on `BudgetCeilingReached` and on a Bedrock exception | `tests/integration/test_budget.py::test_reservation_is_released_when_call_is_blocked`, `tests/integration/test_wrapper.py::test_bedrock_failure_releases_reservation_and_records_failed_row` |
| A ceiling isn't one thing — hard_stop vs. graceful degradation | `DecisionTypeConfig.enforcement_mode`, branch logic in `budget.py::evaluate` | `tests/integration/test_budget.py::test_degrade_mode_falls_back_to_cheaper_model` |
| Calendar-aware ceilings for known high-demand dates | `CeilingCalendarOverride` model, `budget.py::effective_ceiling` | `tests/integration/test_budget.py::test_calendar_override_beats_default_ceiling_on_matching_date`; live: `simulation/scenarios.py::seasonal_demand_spike` |
| Every ceiling breach/degrade logged distinguishably | `BudgetEvent` model, written by `budget.py::_log_event` on every hard_stop/degrade/fail-open/fail-closed | Visible on the dashboard's `/dashboard/budget` events table; `tests/integration/test_wrapper.py` implicitly (blocked calls produce rows); verified manually to actually persist (see the `session_scope` transaction fix below) |
| Identity resolution across systems | `packages/ledger_core/identity.py::resolve_customer_id`, `link_identifier`; `CustomerAccount`/`CustomerIdentifier` models | `tests/integration/test_identity.py` (5 tests); live: `simulation/scenarios.py::cross_system_customer_query` |
| Fuzzy/silent identity matching is refused | `identity.py::link_identifier` raises `ValueError` on a conflicting reassignment rather than guessing | `tests/integration/test_identity.py::test_relinking_to_a_different_account_is_refused` |
| Identity resolution applies going forward only | No retroactive backfill exists anywhere in this codebase; `resolve_customer_id` returns `unresolved:{system}:{raw_id}` for anything never explicitly linked | Documented behavior; the dashboard's customer-lookup page states this explicitly when a query returns no rows |

## Bugs this system's own tests found (evidence, not a claim)

Per this project's own evidence rule ("do not claim tests passed unless you actually ran them"), three real, reproducible bugs were found and fixed during this build — not hypothetical:

1. **`updated_at`/`created_at` lazy-load crash** — reading a server-side-default timestamp off an ORM object immediately after `flush()` (without `refresh()`) raised `MissingGreenlet` under async SQLAlchemy. Fixed in `services/api/app/routers/budget.py`.
2. **Audit trail silently rolled back on an intentional 429** — `get_db`'s session dependency rolled back *any* propagating exception, including the deliberate `HTTPException` raised for a budget-ceiling breach — discarding the very `blocked`-status ledger row and `BudgetEvent` needed to make that breach visible. Fixed in `packages/ledger_core/db/base.py::session_scope` (see its docstring for the full reasoning).
3. **Calendar-override upsert threw an unhandled 500 on a duplicate key** — re-approving an override for a date that already had one crashed instead of updating it. Fixed by making `PUT /v1/budget/calendar-overrides` a real upsert (`services/api/app/routers/budget.py`).

All three were caught by the automated test suite or the live simulation harness, not by code review — see `tests/integration/test_budget.py` and `tests/scenarios/test_scenarios.py`.

## Explicitly out of scope

A broader model-routing stage (choosing the cheapest model that still clears a quality bar) and a waste-detection/reclaim stage (finding and reclaiming redundant spend after the fact) are not implemented — this build covers attribution and budget enforcement only. Nothing in this codebase implements them, and no function or module here is named as if it does (per `prompt.md`'s own rule against fake implementations — e.g. no `route_to_cheapest_model()` that doesn't actually route).
