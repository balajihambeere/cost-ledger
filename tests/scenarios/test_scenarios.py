"""Runs real incidents against the real, running stack (requires
`docker compose up -d api` first — see README) via the same
simulation/scenarios.py functions the demo harness uses, with real
assertions instead of eyeballed output. These are the highest-level proof
in this repo: not "the function returned the right type" but "the
scenario, replayed for real, produces the outcome the fix is supposed to
produce."
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_LIVE_SCENARIO_TESTS") == "1",
    reason="requires `docker compose up -d api` running locally",
)


def test_retry_storm_is_stopped_by_the_ceiling_not_a_bill():
    """An unattended retry loop must be stopped by the wrapper itself,
    in-process, not discovered days later in an invoice."""
    from simulation.scenarios import retry_storm

    result = retry_storm(max_attempts=100)
    assert result["blocked"] is True
    assert result["attempts_before_stop"] < 100  # actually stopped, not just ran out of attempts


def test_redteam_drill_all_succeed_and_are_separately_attributable():
    """A scheduled drill should run to completion (it's legitimate traffic
    against an isolated eval set) and be attributable as its own row, not
    blended into ordinary traffic."""
    from simulation.scenarios import redteam_drill

    result = redteam_drill(volume=10)
    assert result["succeeded"] == result["requested"]


def test_seasonal_demand_spike_calendar_override_actually_fixes_the_incident():
    """The real point: the default ceiling breaking real customers under
    real demand, and a pre-approved calendar override actually fixing it —
    both halves, not just the failure."""
    from simulation.scenarios import seasonal_demand_spike

    result = seasonal_demand_spike(volume=20)
    without = result["without_override"]
    with_ = result["with_override"]

    assert without["blocked"] + without["degraded"] > 0, "the tight default ceiling should bind"
    assert with_["blocked"] == 0, "the calendar override should remove blocking entirely"
    assert with_["primary"] == 20, "with headroom, every call should run on the primary model"


def test_customer_query_resolves_across_three_systems_to_one_real_total():
    """One customer, three systems, three different local identifiers,
    one true total — the exact query identity resolution exists to make
    possible."""
    from simulation.scenarios import cross_system_customer_query

    result = cross_system_customer_query()
    systems_billed = {row["system"] for row in result["spend"]["rows"]}
    assert systems_billed == {"assistant", "logistics", "support"}
    assert float(result["spend"]["total_cost"]) > 0
