-- Seed data for local/dev use. Rate card figures VERIFIED live against
-- claude.com/pricing (fetched during this build, September 2026): Claude
-- Sonnet 5 at $2/$10 per million input/output tokens, Claude Haiku 4.5 at
-- $1/$5; both models use a 1.25x cache-write and 0.1x cache-read
-- multiplier on the base input rate. Stored in USD, matching how both AWS
-- and Anthropic publish these rates; the ledger stores computed call costs
-- in INR (see decision_type_configs.currency) using a separately-configured
-- conversion.
--
-- These are real, current model rates, not fictional numbers.
--
-- model_id below (e.g. 'apac.anthropic.claude-sonnet-5') is an illustrative
-- placeholder — NOT independently verified against AWS's current Bedrock
-- model-ID catalog for the ap-south-1/apac cross-region inference profile
-- naming. A real deployment must replace this with the actual Bedrock
-- model ID or inference-profile ARN from AWS's own console/catalog at
-- deploy time (UNKNOWN — this sandbox has no AWS account to look it up
-- against).

INSERT INTO rate_card_entries
  (id, model_id, effective_from, input_rate_per_million, output_rate_per_million,
   cache_write_multiplier, cache_read_multiplier, currency, source)
VALUES
  (gen_random_uuid(), 'apac.anthropic.claude-sonnet-5', '2026-01-01T00:00:00Z',
   2.00, 10.00, 1.25, 0.10, 'USD', 'claude.com/pricing, fetched live 2026-09-30'),
  (gen_random_uuid(), 'apac.anthropic.claude-haiku-4-5', '2026-01-01T00:00:00Z',
   1.00, 5.00, 1.25, 0.10, 'USD', 'claude.com/pricing, fetched live 2026-09-30')
ON CONFLICT (model_id, effective_from) DO NOTHING;

-- Decision-type configs: one row per (system, decision_type) that the
-- simulation harness (simulation/) exercises. Ceilings and reservation
-- estimates are illustrative starting points for local demo use, an
-- ENGINEERING-DECISION — a real deployment must choose these
-- deliberately, not copy them.

INSERT INTO decision_type_configs
  (system, decision_type, enforcement_mode, daily_ceiling, currency,
   fallback_model_id, routing_model_id, reservation_estimate)
VALUES
  ('assistant', 'fabric_query', 'degrade', 40000.0000, 'INR',
   'apac.anthropic.claude-haiku-4-5', 'apac.anthropic.claude-sonnet-5', 5.0000),
  ('assistant', 'retry_grounding', 'hard_stop', 15000.0000, 'INR',
   NULL, 'apac.anthropic.claude-sonnet-5', 5.0000),
  ('logistics', 'exception_refund', 'hard_stop', 20000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 3.0000),
  ('logistics', 'exception_delay', 'hard_stop', 15000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 3.0000),
  ('bridge', 'bridge_lookup', 'hard_stop', 10000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 1.0000),
  ('support', 'draft_reply', 'degrade', 50000.0000, 'INR',
   'apac.anthropic.claude-haiku-4-5', 'apac.anthropic.claude-sonnet-5', 4.0000),
  ('safety', 'input_check', 'hard_stop', 15000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 1.0000),
  ('safety', 'redteam_drill', 'hard_stop', 20000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 2.0000),
  ('monitoring', 'eval_scheduled', 'hard_stop', 15000.0000, 'INR',
   NULL, 'apac.anthropic.claude-haiku-4-5', 3.0000)
ON CONFLICT (system, decision_type) DO NOTHING;

-- A worked example of a calendar override: a known high-demand sale
-- weekend gets a deliberately higher, pre-approved ceiling instead of a
-- panic-raised one.
INSERT INTO ceiling_calendar_overrides
  (id, system, decision_type, override_date, ceiling, reason, approved_by)
VALUES
  (gen_random_uuid(), 'assistant', 'fabric_query', '2026-11-08', 120000.0000,
   'Diwali sale weekend — approved pre-emptively ahead of the seasonal traffic spike',
   'ops-lead')
ON CONFLICT DO NOTHING;
