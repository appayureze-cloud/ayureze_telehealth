# Ingestion

## Running it

```bash
docker compose up -d postgres
alembic upgrade head
python scripts/run_ingestion.py     # ~36s, real numbers below
python -c "from database import SessionLocal; from deduplication import run_deduplication; db = SessionLocal(); print(run_deduplication(db))"
```

`scripts/run_ingestion.py` runs every source's ingester in dependency
order (herb_database before bhaishajya, since bhaishajya's
`HAS_INGREDIENT` relationships look up already-ingested herb concepts by
name) and prints real, per-source counts — read, imported, rejected,
concepts created, names created — never a claim of success without
numbers behind it.

## Real results, this build's own last run (2026-09-26)

| Source | Read | Imported | Rejected | Concepts | Names |
|---|---|---|---|---|---|
| herb_database | 360 | 360 | 0 | 360 | 2,390 |
| bhaishajya | 176 | 176 | 0 | 176 | 283 |
| pathology | 203 | 203 | 0 | 203 | 406 |
| siddhanta | 162 | 162 | 0 | 162 | 302 |
| ayurwiki | 3,957 | 3,957 | 0 | 3,957 | 3,957 |
| namaste | 14 | 14 | 0 | 14 | 28 |
| **Total** | **4,872** | **4,872** | **0** | **5,085*** | **7,366** |

\* 5,085 total concepts = 4,872 directly-sourced + 213 unverified
`BIO-DISEASE` stub concepts created from source-asserted biomedical
correlations (pathology's `correlation` field, NAMASTE's parenthetical
gloss) — see `docs/DATA_QUALITY_REPORT.md`.

"0 rejected" does NOT mean "0 data quality issues" — see
`docs/DATA_QUALITY_REPORT.md` for the honest breakdown (107 unresolved
ingredient references, 22 unparsed Siddhanta name formats, 11 thin
AyurWiki stubs, etc.) that these ingesters counted and reported rather
than silently dropped.

## Per-source mapping decisions

Each ingester's own module docstring documents its exact field mapping —
read `ingestion/<source>/ingest.py` directly for the authoritative,
current version. Summary:

- **herb_database**: `name`→preferred, `botanical_name`→botanical,
  `english_name`→synonym, `sanskrit_synonyms[]`→synonym. No stable source
  ID exists — array index used as `source_record_id`.
- **bhaishajya**: `main_ingredients[]` resolved against already-ingested
  HERB concepts by exact normalized name match → `HAS_INGREDIENT`
  relationship when found (468 real relationships created); an
  unresolved ingredient name (107 of them — the source's own dosage/
  ingredient text uses looser phrasing than the herb database's canonical
  names) is recorded as an `alias` name on the formulation's own concept
  instead of silently discarded.
- **pathology**: the `correlation` field (a REAL source-asserted
  biomedical term, e.g. Amavata → "Rheumatoid Arthritis") creates an
  unverified `BIO-DISEASE` stub concept + a `RELATED_TO` (never
  `EXACT_MATCH`) relationship, confidence 0.5.
- **siddhanta**: `name` field format `"Latin (Devanagari)"` is split into
  two separate `ConceptName` rows; 22 of 162 records didn't match that
  pattern and were used verbatim (counted, not silently mis-parsed).
- **ayurwiki**: only `docs/{herbs,medicines,concepts,physiology}` (3,957
  of the repository's ~5,400+ total articles) were retrieved — no
  approved domain type covers yoga/traditions/manufacturers. A REAL BUG
  was found and fixed during this build: an initial non-recursive glob
  missed two subdirectories (`medicines/proprietary/`,
  `concepts/prakriti/`), undercounting by 215 files until caught and
  fixed (`rglob` instead of `glob`) — see the git history for this exact
  commit.
- **namaste**: `term_english`'s parenthetical gloss (e.g. "Amavata
  (Rheumatoid Arthritis)") is split the same way as siddhanta's Latin/
  Devanagari pattern, and linked via `RELATED_TO` the same way as
  pathology's `correlation` field.

## A real, honest limitation found mid-build

The AyurWiki ingester's directory walk initially used `Path.glob("*.md")`
(non-recursive). `find data/raw/ayurwiki/docs -iname "*.md"` (which
recurses by default) had already correctly counted 3,957 files for the
manifest, but the ingester's own non-recursive glob only picked up 3,742
— a silent 215-file undercount that would have shipped invisibly if not
caught by cross-checking the ingester's own printed count against the
manifest's independently-derived number. Fixed by switching to `rglob`.
This is exactly the kind of bug real testing against real data catches
that a spec-compliance review of the code alone would not — recorded here
deliberately, not smoothed over.

## Re-running / idempotency

Ingesters are **not** currently idempotent against re-running without a
truncate first — running `scripts/run_ingestion.py` twice against the same
database would create duplicate concepts (a second complete set of new
`concept_id`s), not silently skip already-ingested records. This is a
known Phase 1 limitation (see the final report's "known limitations") —
a real production ingestion pipeline would need a stable natural key per
source record (most of these sources have no stable ID field at all, an
upstream data-quality gap in the sources themselves, not something this
pipeline can fabricate) to detect "already ingested" reliably.
