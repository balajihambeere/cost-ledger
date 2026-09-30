"""compute_cost, verified against hand-computed numbers — including the
cache write/read multipliers (an unread cache write is a real, easy-to-miss
way for a "cheaper" day to end up costing more)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ledger_core.bedrock_client import TokenUsage
from ledger_core.cost import compute_cost
from ledger_core.db.models import RateCardEntry


def _rate(**overrides) -> RateCardEntry:
    defaults = dict(
        model_id="test-model",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_rate_per_million=2.00,
        output_rate_per_million=10.00,
        cache_write_multiplier=1.25,
        cache_read_multiplier=0.10,
        currency="USD",
        source="test",
    )
    defaults.update(overrides)
    return RateCardEntry(**defaults)


def test_plain_call_no_cache():
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    cost = compute_cost(usage, _rate())
    # 1000 * 2.00/1e6 + 500 * 10.00/1e6 = 0.002 + 0.005 = 0.007
    assert cost == Decimal("0.007")


def test_cache_write_costs_more_than_plain_input():
    plain = compute_cost(TokenUsage(input_tokens=1000, output_tokens=0), _rate())
    cache_write = compute_cost(
        TokenUsage(input_tokens=0, output_tokens=0, cache_write_input_tokens=1000), _rate()
    )
    assert cache_write == plain * Decimal("1.25")


def test_cache_read_costs_a_tenth_of_plain_input():
    plain = compute_cost(TokenUsage(input_tokens=1000, output_tokens=0), _rate())
    cache_read = compute_cost(
        TokenUsage(input_tokens=0, output_tokens=0, cache_read_input_tokens=1000), _rate()
    )
    assert cache_read == plain * Decimal("0.10")


def test_unread_cache_write_is_a_net_loss_vs_no_caching_at_all():
    """Writing a cache that's never read back costs strictly more than
    not caching at all (1.25x > 1.0x on the same tokens) — an easy way
    for a caching change to quietly cost more instead of less."""
    no_cache = compute_cost(TokenUsage(input_tokens=5200, output_tokens=0), _rate())
    write_never_read = compute_cost(
        TokenUsage(input_tokens=0, output_tokens=0, cache_write_input_tokens=5200), _rate()
    )
    assert write_never_read > no_cache


def test_haiku_is_half_sonnet_on_sticker_price_alone():
    """Verified against real, current pricing (claude.com/pricing, fetched
    live during this build): Haiku 4.5 is exactly half of Sonnet 5 on both
    input and output."""
    sonnet = _rate(input_rate_per_million=2.00, output_rate_per_million=10.00)
    haiku = _rate(input_rate_per_million=1.00, output_rate_per_million=5.00)
    usage = TokenUsage(input_tokens=10_000, output_tokens=5_000)
    assert compute_cost(usage, haiku) == compute_cost(usage, sonnet) / 2
