# Architecture — existing repository audit (Phase 1, step 1)

This document is the required first deliverable of the AyurEze Terminology
Engine's Phase 1: an audit of the existing `ayureze_telehealth` repository,
done **before** any new code was written, so the new engine reuses
compatible infrastructure instead of duplicating or conflicting with it.
Everything below was verified directly against the repository as it stood
on 2026-09-26 — nothing here is assumed.

## 1. Does a terminology engine already exist?

**No.** A repo-wide search for "terminology" turns up exactly one existing
module: `apps/ai-agent/app/pipeline/terminology.py`. That module is part of
the **medical safety validator** for the real-time translation pipeline —
it extracts numbers/dosages/frequencies/protected terms from a single
utterance being translated, purely to compare source vs. translated text
for safety purposes. It has no concept registry, no search, no persistence,
and is not a terminology database in any sense. It is unrelated to this
project and this project must not import from or depend on it (per this
phase's explicit isolation requirement).

There is no `terminology`, `concepts`, `ayurveda`, or similar directory
anywhere else in the repo. This is a genuinely new system.

## 2. Existing technology stack

| Component | Existing choice | Where |
|---|---|---|
| Session/auth API | Go 1.26.0 | `apps/api/` |
| AI/translation pipeline | Python 3.11.15 (venv), FastAPI 0.115.6, Pydantic 2.10.4 | `apps/ai-agent/` |
| Web SDK | TypeScript | `sdk/web/` |
| Mobile SDK | Flutter/Dart | `sdk/flutter/` (referenced by CI; not audited further, irrelevant to this phase) |
| Database | PostgreSQL 16.4-alpine, single shared instance, DB name `ayureze_telehealth` | `infrastructure/docker/docker-compose.yml` |
| Cache | Redis 7.2-alpine | same compose file |
| Real-time media | LiveKit + coturn (TURN) | same compose file |
| Observability | OpenTelemetry collector, Prometheus, Loki, Promtail, Grafana | same compose file |
| CI | GitHub Actions (`.github/workflows/ci.yml`, `security.yml`) | Go job (fmt/vet/build/test + a separate integration job with real Postgres/Redis/LiveKit service containers), Python job (ruff + pytest for `apps/ai-agent`), Web job (typecheck/test/build) |

**Only the Go API (`apps/api`) currently touches PostgreSQL.** It uses
hand-written, numbered SQL migration files (`apps/api/internal/db/migrations/
0001_core_schema.up.sql` / `.down.sql`, etc.) applied via
`apps/api/internal/db/migrate.go` — a lightweight, no-framework approach.
There is **no existing SQLAlchemy/Alembic usage anywhere in this repo** —
`apps/ai-agent` is a stateless ML pipeline service with no database
dependency at all (confirmed: no `postgres`/`psycopg`/`sqlalchemy` import
anywhere in `apps/ai-agent/app/`). This means the terminology engine is the
**first Python service in this repository to use PostgreSQL**, and
introducing SQLAlchemy 2 + Alembic (as this phase's spec requires) adds a
genuinely new pattern rather than conflicting with an existing one.

`apps/ai-agent`'s Python version is 3.11.15, pinned via its CI job
(`actions/setup-python@v5`, `python-version: "3.11"`) and its own `.venv`.
This phase's spec calls for **Python 3.12** for the new engine — a
deliberate, compatible choice: the terminology engine is fully isolated
(own directory, own dependencies, own virtual environment, own Docker
image) and never imports `apps/ai-agent` code or vice versa, so there is no
version-compatibility requirement to preserve. This is noted here rather
than silently deviating from the spec without explanation.

## 3. Environment configuration pattern

Existing services read configuration from environment variables via a root
`.env`/`.env.example` pair (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, `REDIS_HOST`, etc.).
`apps/ai-agent` uses `pydantic-settings.BaseSettings` for typed config
(`apps/ai-agent/app/config.py`). The terminology engine's own `config/`
module follows the same `pydantic-settings` pattern for consistency, but
uses **its own env var prefix and its own `.env.example`**, isolated from
the root one — this phase must not add required variables to the existing
root `.env`/`.env.example` that other services would need to satisfy.

## 4. Docker Compose

The existing `infrastructure/docker/docker-compose.yml` is a single,
large compose file wiring together every existing service (LiveKit,
coturn, the Go API, the AI agent, the full observability stack) on a
shared `ayureze-net` network, using a **shared PostgreSQL instance and a
single database** (`ayureze_telehealth`).

**Decision for this phase**: the terminology engine gets its **own,
separate `docker-compose.yml`** inside `ayureze-terminology-engine/`, with
its **own PostgreSQL container and its own database name**
(`ayureze_terminology`), rather than being added as a new service into the
existing shared compose file or sharing the existing Postgres instance/
database. Rationale, matching this phase's explicit constraints:

- The task states this must be a **standalone** system in Phase 1, not
  connected to existing production infrastructure.
- Modifying `infrastructure/docker/docker-compose.yml` would mean editing
  a file every existing production service depends on — exactly the
  "do not modify existing production telehealth code" instruction this
  phase must honor.
- A separate compose file means `docker compose up -d` inside
  `ayureze-terminology-engine/` runs and tests this system in complete
  isolation, with zero risk to the existing stack, and zero risk of the
  existing stack's `docker compose up -d` accidentally starting terminology
  infrastructure it doesn't need.
- Merging the two into one shared Postgres instance is a reasonable
  **future** infrastructure decision (real disk/ops savings) once this
  engine is reviewed and approved to integrate — but it is explicitly out
  of scope for "build a standalone engine in Phase 1," and doing it now
  would be exactly the kind of premature integration Phase 1 is written to
  prevent.

Redis is not used by the terminology engine in this phase — Postgres alone
comfortably meets the stated p95 < 100ms local-lookup target (see
`docs/DATA_QUALITY_REPORT.md`'s benchmark section), and the spec says
"Redis may be added only if actually needed." Adding it speculatively
would violate this phase's explicit "do not introduce infrastructure
without a documented technical requirement" instruction.

## 5. Testing framework

`apps/ai-agent` uses `pytest` + `pytest-asyncio`, with marker-based test
selection (`-m models`, `-m integration`) to separate fast unit tests from
slow/real-model tests — the CI Python job runs the fast subset only. The
terminology engine's own test suite (`tests/unit/`, `tests/integration/`,
`tests/fixtures/`) follows the same `pytest` convention for familiarity,
again fully isolated in its own directory with its own `pytest.ini`/
`pyproject.toml` test configuration — it is not added to `apps/ai-agent`'s
test run or CI job.

## 6. CI

**This phase deliberately does NOT modify `.github/workflows/ci.yml` or
`security.yml`.** Adding a new CI job for the terminology engine is a
reasonable next step, but doing so touches a file shared by every existing
service's CI gate — exactly the kind of existing-infrastructure change
this phase's instructions say to avoid. The terminology engine's test
suite and Docker Compose setup are fully runnable locally
(`pytest`, `docker compose up -d`) without any CI change; wiring a new,
additive `terminology-engine` job into the existing workflow file is
recommended as the concrete first task of the next phase (see this
project's own final report for the full recommendation).

## 7. Resulting decisions for this project

| Decision | Reuse existing, or new? | Why |
|---|---|---|
| Postgres 16 (image, extensions: full-text search + `pg_trgm`, both built into stock `postgres:16` images) | New container, same Postgres **major version** (16) for consistency | Isolation; both extensions are already compiled into the standard `postgres:16.4-alpine`-family image, no custom image needed |
| Python 3.12, FastAPI, Pydantic v2 | New service | Spec requirement; no existing Python 3.12 service to reuse |
| SQLAlchemy 2 + Alembic | New pattern for this repo | No existing Python+Postgres service exists to reuse from; Go's SQL-migration approach is a different language/toolchain and not reusable by a Python service |
| Docker Compose | Separate file, separate network, separate Postgres instance | Standalone-system requirement; never touch the existing shared compose file |
| Redis | Not used | Not needed to hit the performance target; spec says add only when justified |
| pgvector | Not used in Phase 1 | Not yet demonstrated necessary — no semantic search requirement established; deterministic FTS/trigram search is what this phase implements and benchmarks |
| CI | Not modified | Avoid touching shared existing infrastructure; documented as next-phase work instead |

## 8. What this project must never do (restated from the task, for this
   document's own completeness)

- Never import `apps/ai-agent` pipeline code (translation, TTS, Safety
  Validator, LiveKit client) — verified there is zero such import anywhere
  in this project's own source.
- Never write to the existing shared PostgreSQL database or its migration
  files under `apps/api/internal/db/migrations/`.
- Never modify `infrastructure/docker/docker-compose.yml`,
  `.github/workflows/*.yml`, or any file under `apps/`.
- Never call an LLM, perform diagnosis, or process patient data — this is
  a terminology lookup/search service over public reference data only.
