"""ledger_core.bedrock_client — the requestMetadata limits are VERIFIED
against AWS's live Converse API reference (16 entries max, 256 chars per
key/value); this locks that contract down so a future change can't
silently drift from it."""

from __future__ import annotations

import pytest

from ledger_core.bedrock_client import (
    MockBedrockClient,
    MockScenario,
    RequestMetadataError,
    validate_request_metadata,
)


def test_valid_metadata_passes():
    validate_request_metadata({"system": "assistant", "decision_type": "fabric_query"})


def test_too_many_entries_rejected():
    metadata = {f"key{i}": "v" for i in range(17)}
    with pytest.raises(RequestMetadataError):
        validate_request_metadata(metadata)


def test_sixteen_entries_is_the_real_limit_and_is_allowed():
    metadata = {f"key{i}": "v" for i in range(16)}
    validate_request_metadata(metadata)  # must not raise


def test_key_too_long_rejected():
    with pytest.raises(RequestMetadataError):
        validate_request_metadata({"k" * 257: "v"})


def test_value_too_long_rejected():
    with pytest.raises(RequestMetadataError):
        validate_request_metadata({"key": "v" * 257})


def test_mock_client_default_scenario():
    client = MockBedrockClient()
    result = client.converse(
        model_id="test-model", messages=[{"content": [{"text": "hello"}]}], request_metadata={}
    )
    assert result.usage.input_tokens > 0
    assert result.output_text == "mock response"


def test_mock_client_marker_scenario():
    client = MockBedrockClient()
    client.register_scenario(
        "SLOW_LOOKUP", MockScenario(output_text="degraded", input_tokens=50, output_tokens=10)
    )
    result = client.converse(
        model_id="test-model",
        messages=[{"content": [{"text": "this hits a SLOW_LOOKUP condition"}]}],
        request_metadata={},
    )
    assert result.output_text == "degraded"
    assert result.usage.input_tokens == 50


def test_mock_client_raises_when_scenario_says_to():
    client = MockBedrockClient()
    client.register_scenario("FAIL", MockScenario(raises=RuntimeError("simulated Bedrock error")))
    with pytest.raises(RuntimeError, match="simulated Bedrock error"):
        client.converse(
            model_id="test-model",
            messages=[{"content": [{"text": "trigger FAIL condition"}]}],
            request_metadata={},
        )


def test_mock_client_deterministic_request_id():
    client = MockBedrockClient()
    messages = [{"content": [{"text": "same input twice"}]}]
    r1 = client.converse(model_id="m", messages=messages, request_metadata={})
    r2 = client.converse(model_id="m", messages=messages, request_metadata={})
    assert r1.request_id == r2.request_id
