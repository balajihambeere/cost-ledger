# Operations

## Deployment status (honest, per this project's own evidence rules)

`VERIFIED`: local deployment via Docker Compose — every service (`postgres`, `redis`, `migrate`, `api`, `web`, `simulation`) builds and runs; the full stack has been exercised end-to-end (migrations applied to a real Postgres, 35/35 automated tests passing against real Postgres+Redis, all four scenarios reproduced against the live API, the dashboard driven in a real browser against the live containerized API).

`UNKNOWN`/not attempted: a real AWS deployment (ECS/Lambda + RDS + ElastiCache in `ap-south-1`). This sandbox has no AWS account. Nothing in this document claims that deployment path has been tested — it's a documented target, not a validated one.

## Local deployment (what's actually been run)

```bash
cp .env.example .env               # adjust JWT_SECRET, ADMIN_PASSWORD, SERVICE_API_KEYS for anything beyond local dev
docker compose build api
docker compose up -d api           # postgres + redis + migrate (runs once) + api
docker exec -i $(docker compose ps -q postgres) psql -U ledger_app -d cost_ledger < database/seed/seed.sql
docker compose build web
docker compose up -d web
```

Health/readiness: `GET /health` (liveness only), `GET /ready` (checks Postgres + Redis are actually reachable) — wire these into your orchestrator's own health-check mechanism (Docker Compose already does, via `healthcheck:` in `docker-compose.yml`).

## Path to a real AWS deployment (documented, not provisioned)

1. **Database**: RDS PostgreSQL (Multi-AZ for production). Set `DATABASE_URL` accordingly; run `alembic -c database/alembic.ini upgrade head` as a deploy step, not manually.
2. **Cache/budget store**: ElastiCache for Redis. The budget engine's correctness (see `packages/ledger_core/budget.py`'s atomic-reservation design) depends on real Redis semantics (`INCRBYFLOAT` atomicity) — a Redis-compatible alternative must preserve that.
3. **Compute**: the `api` container is stateless and horizontally scalable as-is (all state lives in Postgres/Redis) — ECS Fargate or equivalent, behind a load balancer, is a reasonable fit. No code change required.
4. **Bedrock access**: set `BEDROCK_CLIENT_MODE=boto3`, `AWS_REGION=ap-south-1` (or your region), and grant the compute role `bedrock:InvokeModel` / `bedrock:Converse` via IAM — never embed AWS credentials in the container image or `.env`. Confirm the real Bedrock model IDs for your account/region before going live — the ones in `database/seed/seed.sql` are illustrative placeholders, not verified against a real Bedrock catalog (this sandbox has no AWS account to check against).
5. **Model invocation logging**: enable it in the target region (`docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html`) — `requestMetadata` is silently dropped from AWS's own logs otherwise.
6. **Secrets**: `JWT_SECRET`, `ADMIN_PASSWORD`, `SERVICE_API_KEYS`, database credentials — via AWS Secrets Manager or SSM Parameter Store, injected at container start, never baked into the image.
7. **Frontend**: `NEXT_PUBLIC_API_BASE_URL` is baked in at build time — build a separate image per environment, or move to a runtime-configurable approach if that's a real constraint for your deploy pipeline.
8. **CI/CD**: not implemented in this build (no CI platform available in this sandbox to validate against). A real pipeline should run `pytest tests/unit/ tests/integration/` against ephemeral Postgres/Redis (e.g. GitHub Actions services) on every PR, and the scenario suite against a deployed staging environment before promoting to production.

## Monitoring

- `/metrics` (Prometheus format) — currently exposes default process/request metrics via `prometheus-client`; no custom business metrics (e.g. "ceiling breaches per hour") are wired yet. `BudgetEvent` rows are queryable via `GET /v1/budget/events` and are the source of truth for that signal today — wiring a metrics exporter over that table is the natural next step, not yet built (scope discipline: not invented ahead of an actual need).
- Structured JSON logs (`structlog`) on every request, including `request_id`, method, path, status, duration — see `services/api/app/main.py`'s `request_logging` middleware.

## Common failures and recovery

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `POST /v1/calls` returns `400 NoDecisionTypeConfigured` | Nobody has deliberately set a ceiling for this `(system, decision_type)` yet | `PUT /v1/budget/configs` — this is by design, not a bug to route around |
| `POST /v1/calls` returns `429` unexpectedly | The daily ceiling has been reached (check `GET /v1/budget/status`) | Either it's working as intended, or the ceiling was set too tight — a common failure mode when a ceiling is set too conservatively. Consider a calendar override or a higher deliberate ceiling, not a code change |
| Redis unreachable | Network partition, Redis down | See the documented fail-safe behavior in `packages/ledger_core/budget.py` — `degrade`-mode decision types fail open (serve the customer), `hard_stop`-mode decision types fail closed (block). Both log a `fail_open`/`fail_closed` `BudgetEvent`. Restore Redis; no manual reconciliation needed — the running total naturally continues from real Postgres-recorded spend once Redis returns (though the specific *day's* total in Redis will restart from zero — a real gap, see Unknowns in `docs/architecture.md` §7) |
| Migration fails with `greenlet` import error | `sqlalchemy[asyncio]` extra not installed (this exact bug was hit and fixed during this build — see `pyproject.toml`) | Confirm you're running the current image; rebuild if stale |
| A budget-ceiling breach doesn't appear in `GET /v1/budget/events` | Would indicate the transaction bug fixed in `packages/ledger_core/db/base.py::session_scope` has regressed | Check that function's docstring; the fix ensures audit rows commit even when the request ultimately returns an error |

## Backup/recovery

Postgres is the durable system of record. Standard RDS automated backups (or `pg_dump` for a self-managed instance) apply — nothing bespoke is needed since the schema is a normal relational schema with no exotic extensions. Redis holds only same-day running totals, derivable by re-summing `attributed_calls` for the current date if lost — not a backup target.

## Rollback

Standard blue/green or rolling deployment at the container level; the API is stateless. Database migrations in `database/migrations/versions/` each have a `downgrade()` — test it before relying on it in a real incident (not exercised in this build beyond what Alembic's autogenerate produced).
