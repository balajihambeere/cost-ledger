# Cost Ledger

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-App_Router-000000?logo=nextdotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-Tailwind_CSS-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-35%20passing%20(local)-brightgreen)

A real cost-attribution and budget-enforcement system for AI/LLM workloads, covering two stages of a four-stage cost-management cycle — **Attribute → Budget → Route → Reclaim** — for making AI system spend visible and deliberate instead of a surprise on a monthly invoice. This application implements exactly the first two, **Attribute** and **Budget**, no more, no less. Route (model routing) and Reclaim (waste detection) are a broader scope, deliberately not built here.

Full requirements, architecture rationale, and every `REQUIREMENT` vs `ENGINEERING-DECISION` vs `ASSUMPTION` call made during this build: **[docs/architecture.md](docs/architecture.md)**. Concept map: **[docs/concept-mapping.md](docs/concept-mapping.md)**.

## What it does

Every AI system call in this codebase is forced through one shared client (`packages/ledger_core/wrapper.py`) that:

1. **Resolves identity** — translates a caller's local customer identifier into one canonical ID.
2. **Checks budget** — atomically reserves against a per-system, per-decision-type daily ceiling *before* the call goes out; blocks or gracefully degrades to a cheaper model depending on how that decision type is configured.
3. **Calls the model** — via a real Bedrock `Converse`-API-shaped client, tagging the call with `requestMetadata`.
4. **Computes cost** — from real token usage against a versioned rate card, correctly handling prompt-cache write/read multipliers.
5. **Records the ledger row** — append-only, grouped by `decision_id` so retries are measured as one decision, not N calls.

A FastAPI backend exposes this as a REST API; a Next.js dashboard shows a real-time spend report (spend by system/decision type, per-customer lookup, budget status, the events audit trail).

![Cost Ledger system architecture: six simulated systems and the Next.js dashboard call the api service (FastAPI) over HTTP; the api service's ledger_core.wrapper is the only path to AWS Bedrock, resolving identity, checking the Redis budget ceiling, calling the model, and recording each call to the PostgreSQL ledger; a separate reconciliation job reads the ledger plus an invoice CSV and writes back the estimate-vs-actual gap.](docs/assets/architecture-diagram.svg)

## Screenshots

All four screenshots below are the real running app — captured live against the containerized stack (`docker compose up`), not mockups.

**Ledger** — attributed spend by system and decision type, with cost-per-decision:

![Ledger page showing four stat cards (grand total, total calls, successful decisions, systems reporting) and a spend table broken down by system and decision type](docs/assets/screenshots/ledger.jpg)

**Budget** — every decision type's ceiling, current spend, and usage, plus the events audit trail:

![Budget page showing a table of decision types with their enforcement mode, model, today's spend, ceiling, and a usage progress bar, including one at 99.8% and one with a calendar override badge](docs/assets/screenshots/budget.jpg)

**Customer lookup** — one canonical customer's spend across every system that touched them:

![Customer lookup page showing a searched canonical customer ID and a table of their spend across three systems, with a total row](docs/assets/screenshots/customer-lookup.jpg)

**Login**:

![Login page with the Cost Ledger logo mark, username and password fields, and an ambient dark background](docs/assets/screenshots/login.jpg)

## Tech stack

Backend: Python 3.12, FastAPI, PostgreSQL (the ledger), Redis (fast running-total store for the budget engine), `boto3` (real Bedrock client — mocked by default, see below), Alembic. Frontend: Next.js (App Router), TypeScript, Tailwind CSS. Full rationale for every choice: [docs/architecture.md §3](docs/architecture.md#3-requirements).

**No AWS account is required to run this.** `BEDROCK_CLIENT_MODE=mock` (the default) uses a deterministic in-process stand-in that matches the real `boto3` Bedrock `Converse` request/response shape exactly (verified against AWS's live API reference during this build). Set `BEDROCK_CLIENT_MODE=boto3` and provide real AWS credentials to point it at real Bedrock — no code changes needed, only configuration.

## Local setup

Requires Docker and Docker Compose.

```bash
cp .env.example .env
docker compose build api
docker compose up -d api          # brings up postgres, redis, runs migrations, starts the API
docker exec -i $(docker compose ps -q postgres) psql -U ledger_app -d cost_ledger < database/seed/seed.sql
docker compose build web
docker compose up -d web
```

- API: <http://localhost:58000> (docs at `/docs`)
- Web dashboard: <http://localhost:53000> — sign in with `ADMIN_USERNAME`/`ADMIN_PASSWORD` from `.env` (defaults: `admin` / `change-me-dev-only`)

Ports are intentionally non-default (`58000`, `55432`, `63790`, `53000`) — see the comments in `docker-compose.yml`; adjust freely if these happen to collide with something on your machine too.

### Try it: reproduce real incident patterns

```bash
docker compose --profile simulation run --rm simulation
```

Runs four scenarios against the live API and prints real results: a retry storm stopped by the ceiling in milliseconds, a red-team drill running to completion as its own attributable row, a seasonal-demand-day ceiling both breaking real traffic and being fixed by a calendar override, and a one-customer, three-system query resolving to a single honest total. Source: `simulation/scenarios.py`.

## Environment variables

See `.env.example` for the full list with explanations. Nothing sensitive is committed; copy it to `.env` and adjust for your environment. Key ones:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `REDIS_URL` | Redis connection string (budget engine's running-total store) |
| `BEDROCK_CLIENT_MODE` | `mock` (default) or `boto3` |
| `SERVICE_API_KEYS` | `system:key,system:key` — one API key per simulated system, checked on `POST /v1/calls` |
| `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Single-admin auth for the dashboard/admin API (see [Unknowns](docs/architecture.md#7-unknowns-assumptions-and-open-questions-do-not-guess-past-these) — no multi-user system exists yet) |
| `NEXT_PUBLIC_API_BASE_URL` | Baked into the web build at build time — the browser-reachable API URL |

## Database

Schema and migrations: `database/migrations/` (Alembic). Seed data (real, current Claude Sonnet 5 / Haiku 4.5 pricing, verified live against `claude.com/pricing` during this build, plus sample decision-type configs and a worked seasonal calendar-override example): `database/seed/seed.sql`. To apply migrations manually:

```bash
docker run --rm --network cost-ledger_default -e DATABASE_URL=postgresql+asyncpg://ledger_app:change-me-in-real-deployments@postgres:5432/cost_ledger cost-ledger-app:latest sh -c "alembic -c database/alembic.ini upgrade head"
```

Never use an in-memory structure in place of Postgres for the ledger — it's an append-only financial record, not a cache.

## Running tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d postgres redis    # tests run against the real thing, not mocks
pytest tests/unit/ tests/integration/  # 30 tests, no live API needed

docker compose up -d api               # for the scenario suite, which hits the real API
pytest tests/scenarios/                # 4 tests, reproduce real incident patterns with real assertions
```

35/35 pass as of this build. Only Bedrock is mocked; Postgres, Redis, and (for the scenario suite) the real HTTP API are exercised for real. Three real bugs were found and fixed by this test suite during development — see `docs/concept-mapping.md` for detail, or just read `packages/ledger_core/db/base.py`'s `session_scope` docstring for the most interesting one (an audit-trail-losing transaction bug that only a real Postgres could have caught).

## Documentation

- [docs/architecture.md](docs/architecture.md) — requirements, architecture, tech stack rationale, repo structure, implementation plan, unknowns/assumptions
- [docs/concept-mapping.md](docs/concept-mapping.md) — every concept, where it's implemented, how it's tested
- [docs/api.md](docs/api.md) — API reference
- [docs/operations.md](docs/operations.md) — deployment, monitoring, troubleshooting, recovery
- [docs/production-readiness.md](docs/production-readiness.md) — the final checklist, with evidence

## What this is not

A broader model-routing stage (choosing the cheapest model that still clears a quality bar) and a waste-detection/reclaim stage are not implemented — this build covers attribution and budget enforcement only, and building the rest here would be inventing scope beyond what was actually asked for. Real AWS infrastructure (Terraform/CDK, a provisioned RDS/ElastiCache/ECS deployment) is documented in `docs/operations.md` but not provisioned — this sandbox has no AWS account to provision or validate one against. A local Docker Compose deployment is what's actually been run and verified.
