# AyurEze Terminology Engine — Phase 1

A standalone Ayurveda + biomedical terminology registry, search, and
resolution API. Built from scratch, isolated from the rest of the
`ayureze_telehealth` repository.

## What this does

- Ingests real, approved Ayurveda datasets (5 GitHub repositories +
  NAMASTE) into a normalized, deduplicated, provenance-tracked canonical
  concept registry in PostgreSQL.
- Serves deterministic search/resolution over that registry — exact
  match, synonym match, scientific/botanical name match, transliteration
  match, prefix match, and `pg_trgm` fuzzy match, each labeled with a real
  `match_type` and `confidence`, never an inflated or guessed score.
- Provides an adapter architecture for 6 biomedical terminologies (ICD-11,
  SNOMED CT, LOINC, RxNorm, MeSH, ATC) — live lookups against
  externally-licensed services, never a bulk local copy. `RxNormAdapter`
  and `MeshAdapter` are genuinely working against real public APIs today;
  `SnomedAdapter` is deliberately disabled until a real license + server
  are configured; `AtcAdapter` is permanently disabled per its source's
  own explicit "no commercial redistribution" terms.
- Tracks full provenance: every canonical concept traces back to the
  exact raw source record it came from.
- Runs a staged deduplication pipeline that flags likely duplicates for
  human review — it never auto-merges.

**Real numbers from this build's own last run**: 5,085 canonical concepts,
7,366 names, 683 evidenced relationships, 4,872 source records, 802
deduplication candidates. See `docs/DATA_QUALITY_REPORT.md`.

## What this does NOT do

- Does not call an LLM, generate medical advice, or perform diagnosis.
- Does not connect to the AyurEze AI pipeline, Qwen3-ASR, any translation
  model, Qwen3-TTS, the Safety Validator, or LiveKit — verified zero
  imports of any of that code anywhere in this project.
- Does not process patient data or live audio.
- Does not bulk-copy SNOMED CT, LOINC, RxNorm, MeSH, or ATC content into
  its own database — see `docs/LICENSE_MATRIX.md` for exactly why, per
  terminology.
- Does not auto-merge duplicate concepts, or auto-assign `EXACT_MATCH`
  between an Ayurvedic and a biomedical concept.
- Does not modify any file outside `ayureze-terminology-engine/`.

## Architecture

```
SOURCE DATA (GitHub repos, real files)
    -> data/raw/<source>/                (immutable snapshots)
    -> ingestion/<source>/ingest.py       (parses, canonicalizes)
    -> normalization/normalize.py         (deterministic, non-destructive)
    -> models.Concept / ConceptName / SourceRecord / ConceptRelationship
    -> deduplication/pipeline.py          (flags candidates, never merges)
    -> PostgreSQL (pg_trgm + generated tsvector full-text search)
    -> terminology/search.py + api/       (FastAPI, deterministic ranking)
```

See `docs/ARCHITECTURE.md` for the existing-repository audit this project
started from, and the isolation decisions (separate Postgres, separate
Docker Compose, separate CI — nothing shared with the telehealth stack).

## Setup

```bash
cd ayureze-terminology-engine
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in TERMINOLOGY_POSTGRES_PASSWORD
docker compose up -d postgres
alembic upgrade head
```

## Ingestion

```bash
python scripts/run_ingestion.py
python -c "from database import SessionLocal; from deduplication import run_deduplication; db = SessionLocal(); print(run_deduplication(db))"
```

See `docs/INGESTION.md` for real per-source counts and every field-mapping
decision.

## Running the API

```bash
uvicorn api.main:app --reload --port 8100
# or: docker compose up -d
curl http://localhost:8100/health
curl "http://localhost:8100/v1/terminology/search?q=Guduchi"
```

OpenAPI docs at `http://localhost:8100/docs`. See `docs/API.md` for real
captured example responses for every endpoint.

## Database

PostgreSQL 16, its own container/database (`ayureze_terminology`,
port 5433 by default — deliberately not 5432, which the existing
telehealth stack's own Postgres uses). Schema managed by Alembic
(`alembic upgrade head` / `alembic revision --autogenerate`). See
`docs/DATA_MODEL.md`.

## Testing

```bash
pip install -e ".[dev]"
docker compose up -d postgres
createdb -h localhost -p 5433 -U terminology ayureze_terminology_test  # once
pytest tests/                    # 59 tests: unit + integration, all real
pytest tests/unit                # no database required
```

Real search latency benchmark: `python scripts/benchmark.py` — this
build's own last run: **p95 = 8.97ms** against the full 5,085-concept
database (target: <100ms).

## Licensing

**Read `docs/LICENSE_MATRIX.md` before using this data commercially.**
Four of the five Ayurveda sources are plain CC-BY-4.0 (commercial-safe,
attribution required). **AyurWiki is CC-BY-SA-4.0 (ShareAlike)** — a real,
unresolved question about whether combining it into a proprietary
database creates a ShareAlike obligation on the combined output; get real
legal review before shipping AyurWiki-derived content commercially.
NAMASTE's license is genuinely unknown (no LICENSE file exists). ATC/DDD
bulk redistribution is explicitly prohibited by its own source. SNOMED CT
requires a real Affiliate License (realistically free for this product's
target markets, but not yet obtained) before its adapter can be enabled.

## Limitations (honest, not hidden)

- ~~Ingestion is not idempotent~~ **fixed (2026-09-26)** — re-running
  `scripts/run_ingestion.py` without truncating first is now safe: a
  second run against the same data reports `concepts_created: 0,
  names_created: 0` for all 6 sources (verified for real, twice, not just
  asserted) — see `docs/INGESTION.md`.
- NAMASTE ingestion covers 14 real sample rows, not the full 7,363-code
  dataset (which lives in a live external system outside this phase's
  approved sources).
- Deduplication candidates are flagged, never resolved — 802 pending
  candidates currently await human review (`deduplication_candidates`
  table), including a real, high-confidence case (Giloy/Amrita, both
  *Tinospora cordifolia*) found in this build's own data.
- `GET /v1/biomedical/{system}/search` is wired in for all 6 biomedical
  systems. `rxnorm`/`mesh` genuinely work today (real public APIs, no
  credentials needed — verified with real live queries). `icd11`/`loinc`/
  `snomed` are written and tested for fail-closed behavior (real `503`s)
  but not exercised against a real license/credentials in this
  environment; `atc` has no automated lookup path at all, by design.
- No authentication layer — appropriate for this phase's standalone,
  non-patient-data scope (see `docs/SECURITY.md`).

See `docs/DATA_QUALITY_REPORT.md` for the full, itemized data quality
findings, and the project's final report (delivered separately) for the
complete evidence-based status and recommended next phase.
