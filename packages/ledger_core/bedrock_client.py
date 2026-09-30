"""Bedrock client abstraction.

The shared wrapper (packages/ledger_core/wrapper.py) is the only path any
system may use to reach Bedrock, so no code path can skip attribution
tagging. This module is the layer directly below that wrapper: a small
`BedrockClient` Protocol matching the real
`boto3` `bedrock-runtime` `converse` request/response shape (VERIFIED
against docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
and docs.aws.amazon.com/bedrock/latest/userguide/cost-mgmt-request-metadata.html,
fetched live), with two implementations:

  - `BotoBedrockClient` — real AWS calls via boto3. Used when
    BEDROCK_CLIENT_MODE=boto3 and real credentials are configured.
  - `MockBedrockClient`  — deterministic, no network, no AWS account
    required. Used by default (BEDROCK_CLIENT_MODE=mock) and by every test
    and the simulation harness, since this sandbox has no AWS credentials
    to test against. Swapping to the real client requires only
    configuration — no code change — because both honor the same Protocol
    and the same request/response shape.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Protocol


class RequestMetadataError(ValueError):
    """Raised when requestMetadata would violate Bedrock's real limits:
    at most 16 entries, each key/value at most 256 characters
    (VERIFIED against the Converse API reference)."""


def validate_request_metadata(metadata: dict[str, str]) -> None:
    if len(metadata) > 16:
        raise RequestMetadataError(
            f"requestMetadata supports at most 16 entries, got {len(metadata)}"
        )
    for key, value in metadata.items():
        if len(key) > 256:
            raise RequestMetadataError(f"requestMetadata key too long (>256 chars): {key!r}")
        if len(value) > 256:
            raise RequestMetadataError(
                f"requestMetadata value too long (>256 chars) for key {key!r}"
            )


@dataclass(frozen=True)
class TokenUsage:
    """Mirrors the real Converse API's `usage` object field names exactly:
    inputTokens, outputTokens, cacheReadInputTokens, cacheWriteInputTokens,
    totalTokens (VERIFIED against the live API reference)."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ConverseResult:
    output_text: str
    stop_reason: str
    usage: TokenUsage
    request_id: str


class BedrockClient(Protocol):
    def converse(
        self,
        *,
        model_id: str,
        messages: list[dict],
        request_metadata: dict[str, str],
        system_prompt: str | None = None,
    ) -> ConverseResult: ...


class BotoBedrockClient:
    """Real AWS Bedrock client. Not exercised in this sandbox (no AWS
    credentials available) — the request/response shape it builds is
    VERIFIED against AWS's own API reference, but the network call itself
    is untested here. Point BEDROCK_CLIENT_MODE=boto3 with real credentials
    to use it."""

    def __init__(self, region_name: str) -> None:
        import boto3  # imported lazily so `mock` mode never requires boto3/creds

        self._client = boto3.client("bedrock-runtime", region_name=region_name)

    def converse(
        self,
        *,
        model_id: str,
        messages: list[dict],
        request_metadata: dict[str, str],
        system_prompt: str | None = None,
    ) -> ConverseResult:
        validate_request_metadata(request_metadata)
        kwargs: dict = {
            "modelId": model_id,
            "messages": messages,
            "requestMetadata": request_metadata,
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]

        response = self._client.converse(**kwargs)
        usage = response["usage"]
        output_message = response["output"]["message"]
        output_text = "".join(
            block.get("text", "") for block in output_message.get("content", [])
        )
        return ConverseResult(
            output_text=output_text,
            stop_reason=response["stopReason"],
            usage=TokenUsage(
                input_tokens=usage["inputTokens"],
                output_tokens=usage["outputTokens"],
                cache_read_input_tokens=usage.get("cacheReadInputTokens", 0),
                cache_write_input_tokens=usage.get("cacheWriteInputTokens", 0),
            ),
            request_id=response.get("ResponseMetadata", {}).get("RequestId", str(uuid.uuid4())),
        )


@dataclass
class MockScenario:
    """Lets tests and the simulation harness script exactly the behavior a
    call should have, keyed by a deterministic hash of its content — so a
    simulated "slow catalog lookup" input always produces the same
    forced-retry behavior, without depending on a real model's actual
    output.
    """

    output_text: str = "mock response"
    input_tokens: int = 120
    output_tokens: int = 80
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    stop_reason: str = "end_turn"
    raises: Exception | None = None


class MockBedrockClient:
    """Deterministic stand-in for Bedrock. Default behavior: a small, cheap
    fixed-size response. Tests and the simulation harness register scenarios
    keyed by model_id or by a marker in the message content to reproduce
    specific incidents (a slow lookup that always needs a retry, a
    red-team drill's adversarial volume, etc.) without any network call.
    """

    def __init__(self) -> None:
        self._default = MockScenario()
        self._by_marker: dict[str, MockScenario] = {}

    def register_scenario(self, marker: str, scenario: MockScenario) -> None:
        """Any call whose last user message contains `marker` gets this
        scenario's usage/output instead of the default."""
        self._by_marker[marker] = scenario

    def set_default(self, scenario: MockScenario) -> None:
        self._default = scenario

    def converse(
        self,
        *,
        model_id: str,
        messages: list[dict],
        request_metadata: dict[str, str],
        system_prompt: str | None = None,
    ) -> ConverseResult:
        validate_request_metadata(request_metadata)

        last_text = ""
        if messages:
            for block in messages[-1].get("content", []):
                last_text += block.get("text", "")

        scenario = self._default
        for marker, candidate in self._by_marker.items():
            if marker in last_text:
                scenario = candidate
                break

        if scenario.raises is not None:
            raise scenario.raises

        request_id = str(
            uuid.UUID(hashlib.sha256((last_text + model_id).encode()).hexdigest()[:32])
        )
        return ConverseResult(
            output_text=scenario.output_text,
            stop_reason=scenario.stop_reason,
            usage=TokenUsage(
                input_tokens=scenario.input_tokens,
                output_tokens=scenario.output_tokens,
                cache_read_input_tokens=scenario.cache_read_input_tokens,
                cache_write_input_tokens=scenario.cache_write_input_tokens,
            ),
            request_id=request_id,
        )


def build_bedrock_client(mode: str, region_name: str) -> BedrockClient:
    if mode == "mock":
        return MockBedrockClient()
    if mode == "boto3":
        return BotoBedrockClient(region_name=region_name)
    raise ValueError(f"Unknown BEDROCK_CLIENT_MODE: {mode!r} (expected 'mock' or 'boto3')")
