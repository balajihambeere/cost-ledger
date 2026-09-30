"""A thin HTTP client standing in for what each of the six simulated
systems would embed — every simulated system talks to the Ledger only
through POST /v1/calls, authenticated with its own API key, exactly the
boundary a real system would cross. Nothing here reaches Bedrock directly;
that's the whole point of the shared wrapper (packages/ledger_core/wrapper.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass
class CallOutcome:
    ok: bool
    status_code: int
    body: dict


class SystemClient:
    def __init__(self, system: str, api_key: str, base_url: str, timeout: float = 10.0) -> None:
        self.system = system
        self._client = httpx.Client(
            base_url=base_url, headers={"X-API-Key": api_key}, timeout=timeout
        )

    def call(
        self,
        *,
        decision_type: str,
        customer_identifier: str,
        text: str,
        decision_id: str | None = None,
        attempt_number: int = 1,
    ) -> CallOutcome:
        body = {
            "decision_type": decision_type,
            "customer_identifier": customer_identifier,
            "messages": [{"role": "user", "content": [{"text": text}]}],
            "attempt_number": attempt_number,
        }
        if decision_id:
            body["decision_id"] = decision_id
        response = self._client.post("/v1/calls", json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        return CallOutcome(ok=response.status_code == 200, status_code=response.status_code, body=payload)

    def close(self) -> None:
        self._client.close()


def system_client(system: str) -> SystemClient:
    base_url = os.environ.get("API_BASE_URL") or os.environ.get("NEXT_PUBLIC_API_BASE_URL") or "http://api:8000"
    keys = os.environ.get("SERVICE_API_KEYS", "")
    key_map = dict(pair.split(":", 1) for pair in keys.split(",") if ":" in pair)
    if system not in key_map:
        raise RuntimeError(f"No API key configured for system={system!r} in SERVICE_API_KEYS")
    return SystemClient(system=system, api_key=key_map[system], base_url=base_url)


class AdminClient:
    """For the simulation harness's own setup steps (creating decision-type
    configs, linking identities) — the same admin surface the dashboard
    uses, authenticated the same way a human operator would be."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 10.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)
        token_response = self._client.post(
            "/v1/auth/token", data={"username": username, "password": password}
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        self._client.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self._client.get(path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self._client.put(path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self._client.post(path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self._client.delete(path, **kwargs)

    def close(self) -> None:
        self._client.close()


def admin_client() -> AdminClient:
    base_url = os.environ.get("API_BASE_URL") or os.environ.get("NEXT_PUBLIC_API_BASE_URL") or "http://api:8000"
    return AdminClient(
        base_url=base_url,
        username=os.environ.get("ADMIN_USERNAME", "admin"),
        password=os.environ.get("ADMIN_PASSWORD", "change-me-dev-only"),
    )
