"""Cost computation.

Formula (VERIFIED cache multipliers against claude.com/pricing, fetched
live: 5-minute cache write = 1.25x base input rate, cache read = 0.1x base
input rate; both Sonnet 5 and Haiku 4.5 use the same multipliers):

    cost = input_tokens * input_rate
         + cache_write_input_tokens * input_rate * cache_write_multiplier
         + cache_read_input_tokens  * input_rate * cache_read_multiplier
         + output_tokens * output_rate

Rates are per-million-tokens, matching how Anthropic and AWS publish them,
so callers divide by 1_000_000. The rate card is never hardcoded — see
RateCardEntry in ledger_core.db.models — a sticker price is a moving
target, not a permanent truth, so it's a versioned, editable config
instead.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from ledger_core.bedrock_client import TokenUsage
from ledger_core.db.models import RateCardEntry

MILLION = Decimal(1_000_000)


def compute_cost(usage: TokenUsage, rate: RateCardEntry) -> Decimal:
    input_rate = Decimal(str(rate.input_rate_per_million))
    output_rate = Decimal(str(rate.output_rate_per_million))
    cache_write_mult = Decimal(str(rate.cache_write_multiplier))
    cache_read_mult = Decimal(str(rate.cache_read_multiplier))

    cost = (
        Decimal(usage.input_tokens) * input_rate
        + Decimal(usage.cache_write_input_tokens) * input_rate * cache_write_mult
        + Decimal(usage.cache_read_input_tokens) * input_rate * cache_read_mult
        + Decimal(usage.output_tokens) * output_rate
    ) / MILLION

    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
