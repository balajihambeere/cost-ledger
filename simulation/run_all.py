"""Runs all four scenarios against the live API and prints a summary.
Invoked as `python -m simulation.run_all` (see the `simulation` service
in docker-compose.yml, profile "simulation")."""

from __future__ import annotations

import json

from simulation.scenarios import (
    cross_system_customer_query,
    redteam_drill,
    retry_storm,
    seasonal_demand_spike,
)


def main() -> None:
    print("=== Cost Ledger simulation ===\n")

    print("-- retry_storm --")
    print(json.dumps(retry_storm(), indent=2))

    print("\n-- redteam_drill --")
    print(json.dumps(redteam_drill(), indent=2))

    print("\n-- seasonal_demand_spike --")
    print(json.dumps(seasonal_demand_spike(), indent=2))

    print("\n-- cross_system_customer_query --")
    print(json.dumps(cross_system_customer_query(), indent=2))


if __name__ == "__main__":
    main()
