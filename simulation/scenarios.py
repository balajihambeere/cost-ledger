"""Four scenarios exercising the Attribute/Budget system end-to-end, run
against the real API (over HTTP, with real auth) rather than asserted in
prose. Each function returns a plain dict summary so run_all.py and the
test suite (tests/scenarios/) can both use them.
"""

from __future__ import annotations

import uuid
from datetime import date

from simulation.client import admin_client, system_client


def ensure_config(admin, **config) -> None:
    resp = admin.put("/v1/budget/configs", json=config)
    resp.raise_for_status()


def retry_storm(max_attempts: int = 50) -> dict:
    """A slow downstream lookup makes the caller retry the same grounding
    query over and over. Without a pre-spend ceiling this can run
    unnoticed for days, quietly multiplying real spend. With a hard_stop
    ceiling on this decision type, the wrapper stops accepting new retries
    within milliseconds of crossing it — this reproduces that: the same
    decision_id, incrementing attempt_number, until the ceiling blocks it,
    proving the block happens at all, not after a bill.
    """
    admin = admin_client()
    ensure_config(
        admin,
        system="assistant",
        decision_type="retry_grounding",
        enforcement_mode="hard_stop",
        daily_ceiling="0.05",
        currency="INR",
        routing_model_id="apac.anthropic.claude-sonnet-5",
        reservation_estimate="0.001",
    )
    admin.close()

    client = system_client("assistant")
    decision_id = str(uuid.uuid4())
    attempts = 0
    blocked = False
    total_cost = 0.0
    for attempt in range(1, max_attempts + 1):
        outcome = client.call(
            decision_type="retry_grounding",
            customer_identifier="internal:grounding-retry-loop",
            text="slow catalog lookup for SKU MZB-3390, retrying",
            decision_id=decision_id,
            attempt_number=attempt,
        )
        attempts = attempt
        if outcome.status_code == 429:
            blocked = True
            break
        total_cost += float(outcome.body.get("cost", 0))
    client.close()

    return {
        "scenario": "retry_storm",
        "attempts_before_stop": attempts,
        "blocked": blocked,
        "total_cost": total_cost,
    }


def redteam_drill(volume: int = 30) -> dict:
    """A scheduled adversarial drill, run at several times normal volume
    against an isolated evaluation set — real cost, but concentrated in
    its own decision_type row rather than blended into ordinary traffic,
    so it can be told apart from a genuine incident.
    """
    admin = admin_client()
    ensure_config(
        admin,
        system="safety",
        decision_type="redteam_drill",
        enforcement_mode="hard_stop",
        daily_ceiling="5.00",
        currency="INR",
        routing_model_id="apac.anthropic.claude-haiku-4-5",
        reservation_estimate="0.001",
    )
    admin.close()

    client = system_client("safety")
    succeeded = 0
    for i in range(volume):
        outcome = client.call(
            decision_type="redteam_drill",
            customer_identifier=f"internal:redteam-eval-set:{i}",
            text=f"adversarial probe #{i}",
        )
        if outcome.ok:
            succeeded += 1
    client.close()

    return {"scenario": "redteam_drill", "requested": volume, "succeeded": succeeded}


def seasonal_demand_spike(volume: int = 40) -> dict:
    """An ordinary daily ceiling, sized for a normal day, breaks real
    customer experience on a day traffic is deliberately driven up (a
    sale, a promotion). Runs the burst twice: once against the plain
    default ceiling (some calls degrade to the fallback model, some are
    blocked), once with a calendar override in place for today (headroom,
    no blocking) — demonstrating the fix, not just the failure.

    Uses a fresh decision_type per invocation (fabric_query_sim_<suffix>)
    rather than the literal "fabric_query" so repeated runs on the same
    calendar day never inherit another run's accumulated spend or calendar
    override — deliberately, since this system has no "reset today's
    spend" capability and shouldn't (that's real financial history), so
    the scenario keeps itself repeatable instead of needing one.
    """
    decision_type = f"fabric_query_sim_{uuid.uuid4().hex[:8]}"
    admin = admin_client()
    ensure_config(
        admin,
        system="assistant",
        decision_type=decision_type,
        enforcement_mode="degrade",
        daily_ceiling="0.01",
        currency="INR",
        fallback_model_id="apac.anthropic.claude-haiku-4-5",
        routing_model_id="apac.anthropic.claude-sonnet-5",
        reservation_estimate="0.00104",
    )

    def run_burst() -> tuple[int, int, int]:
        client = system_client("assistant")
        primary = degraded = blocked = 0
        for i in range(volume):
            outcome = client.call(
                decision_type=decision_type,
                customer_identifier=f"cust_seasonal_{i}",
                text="does this saree run true to size?",
            )
            if outcome.status_code == 429:
                blocked += 1
            elif outcome.body.get("status") == "degraded":
                degraded += 1
            elif outcome.ok:
                primary += 1
        client.close()
        return primary, degraded, blocked

    without_override = run_burst()

    today = date.today()
    override_resp = admin.put(
        "/v1/budget/calendar-overrides",
        json={
            "system": "assistant",
            "decision_type": decision_type,
            "override_date": today.isoformat(),
            "ceiling": "0.10",
            "reason": "simulated high-demand day",
            "approved_by": "simulation-harness",
        },
    )
    override_resp.raise_for_status()
    admin.close()

    with_override = run_burst()

    return {
        "scenario": "seasonal_demand_spike",
        "without_override": {"primary": without_override[0], "degraded": without_override[1], "blocked": without_override[2]},
        "with_override": {"primary": with_override[0], "degraded": with_override[1], "blocked": with_override[2]},
    }


def cross_system_customer_query() -> dict:
    """One ordinary customer's ordinary day, across three systems, each
    tagging them with a different local identifier — then linked to one
    canonical account so their total spend can be queried honestly,
    instead of only per-system or as a company-wide average.
    """
    admin = admin_client()
    for cfg in (
        dict(system="assistant", decision_type="fabric_query", enforcement_mode="degrade",
             daily_ceiling="10.00", currency="INR", fallback_model_id="apac.anthropic.claude-haiku-4-5",
             routing_model_id="apac.anthropic.claude-sonnet-5", reservation_estimate="0.001"),
        dict(system="logistics", decision_type="exception_delay", enforcement_mode="hard_stop",
             daily_ceiling="10.00", currency="INR",
             routing_model_id="apac.anthropic.claude-haiku-4-5", reservation_estimate="0.001"),
        dict(system="support", decision_type="draft_reply", enforcement_mode="degrade",
             daily_ceiling="10.00", currency="INR", fallback_model_id="apac.anthropic.claude-haiku-4-5",
             routing_model_id="apac.anthropic.claude-sonnet-5", reservation_estimate="0.001"),
    ):
        ensure_config(admin, **cfg)

    email_hash = "a41f9c2"
    order_id = "ORD-88214"
    ticket_id = "TCK-55031"

    # Identity is linked *before* the calls — this demonstrates the
    # resolver working as designed going forward, not its own known
    # pre-link gap (the resolver only ever applies to activity recorded
    # after an identifier is linked; see packages/ledger_core/identity.py).
    link_resp = admin.post("/v1/identity/link", json={"system": "assistant", "raw_identifier": email_hash})
    link_resp.raise_for_status()
    canonical_id = link_resp.json()["canonical_id"]
    admin.post("/v1/identity/link", json={
        "system": "logistics", "raw_identifier": order_id, "canonical_id": canonical_id
    }).raise_for_status()
    admin.post("/v1/identity/link", json={
        "system": "support", "raw_identifier": ticket_id, "canonical_id": canonical_id
    }).raise_for_status()

    assistant = system_client("assistant")
    assistant.call(decision_type="fabric_query", customer_identifier=email_hash,
                 text="does the maroon zari-border saree run true to size?")
    assistant.close()

    logistics = system_client("logistics")
    logistics.call(decision_type="exception_delay", customer_identifier=order_id,
               text="delivery delayed two days, issuing credit")
    logistics.close()

    support = system_client("support")
    support.call(decision_type="draft_reply", customer_identifier=ticket_id,
                 text="confirming the credit has landed")
    support.close()

    spend_resp = admin.get(f"/v1/ledger/customers/{canonical_id}")
    spend_resp.raise_for_status()
    admin.close()

    return {"scenario": "cross_system_customer_query", "canonical_id": canonical_id, "spend": spend_resp.json()}
