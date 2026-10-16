# Data model

Six tables, matching spec section 4's layering (raw → normalized →
canonical → relationships → search index → API). See `models/` for the
SQLAlchemy source of truth; this document explains the *why*, not just
restates the columns.

## `sources`

One row per approved data source — the DB-queryable mirror of
`data/manifests/source_manifest.json`. Every source is registered here,
including the 6 biomedical adapter-only sources with `record_count=0` —
`GET /v1/sources` must show the complete, honest picture of what's
approved/ingested/disabled, not just the ones that happened to run.

## `source_records` — raw, immutable provenance

`original_payload` (JSONB) stores the record **exactly as read** from the
raw source file — never post-normalization, never post-cleanup. This is
what makes every canonical concept traceable back to real evidence (spec
section 10). `concept_id` is nullable: a source record can exist before
canonicalization assigns it (matching the pipeline's own staging), though
in this build's actual ingesters every record is canonicalized in the
same transaction it's read in.

## `concepts` — the canonical registry

`concept_id` (e.g. `AYU-HERB-000004`) is always freshly minted by
`services/concept_id.py`, **never** a source's own identifier — verified
by a real test (`test_concept_ids_never_reuse_source_ids`) that inspects
the minting function's own signature. `domain`/`category` are plain
strings (not a native Postgres ENUM) so a new category never requires a
schema migration — see `models/enums.py` for the Python-side controlled
vocabulary. `confidence` reflects the ingestion pipeline's confidence in
its own extraction (e.g. 1.0 for a clean JSON record, 0.4–0.8 for a thin
AyurWiki stub, 0.5 for an unverified biomedical correlation stub) — it is
NEVER a claim about the underlying medical/Ayurvedic knowledge's own
certainty.

## `concept_names` — every name a concept is known by

`name` preserves the original spelling verbatim; `normalized_name` is the
deterministic, non-destructive output of `normalization.normalize_name()`
— NFKC + punctuation normalization + casefold + whitespace collapse.
`name_tsv` (a `GENERATED ALWAYS AS ... STORED` tsvector column, `'simple'`
text search config deliberately — this corpus mixes English, Sanskrit
transliteration, and Devanagari, and English-specific stemming would
mangle the non-English majority) and a `pg_trgm` GIN index on
`normalized_name` back the search layer directly — see `docs/API.md`.

## `concept_relationships` — evidenced connections only

Every row requires a non-null `evidence` string citing exactly what in
the source justified it (a field name, a specific value) — this table is
never populated by string-similarity guessing. `EXACT_MATCH` between an
`AYURVEDA`-domain and `BIOMEDICAL`-domain concept is never auto-assigned
anywhere in this codebase (grep-verified: the only place `EXACT_MATCH`
appears in application code is `models/enums.py`'s own enum definition) —
cross-domain correlations from the Encyclopedia of Ayurvedic Pathology's
`correlation` field and NAMASTE's parenthetical gloss are stored as
`RELATED_TO` with `confidence=0.5`, explicitly marking them as
source-asserted and unverified against a real biomedical terminology.

## `deduplication_candidates` — the review queue, never an auto-merge

`status` starts `"pending"` and nothing in the ingestion or deduplication
pipeline ever changes it — only an explicit, separate human review action
(not yet built as its own service in Phase 1; `status` can be updated
directly via SQL/a future admin endpoint) can move it to
`"accepted"`/`"rejected"`. Verified by a real test
(`test_deduplication_never_merges_or_deletes_concepts`) that running the
full pipeline never changes the concept count.

## `id_counters`

Backs `services/concept_id.py`'s atomic, gap-tolerant ID minting — one row
per prefix (`AYU-HERB`, `BIO-DISEASE`, etc.), incremented via a single
`UPDATE ... RETURNING` so concurrent ingestion runs can't collide. A new
prefix needs a new row, not a schema migration.

## Why plain strings for domain/category/status/name_type/relationship_type

A native Postgres ENUM type requires an `ALTER TYPE ... ADD VALUE`
migration (and, on older Postgres versions, real operational care) every
time a new category is needed — e.g. adding `BOTANICAL_TERM` as a distinct
category from `HERB` later, or a new biomedical `LAB`/`DRUG` subtype.
`models/enums.py`'s Python `str` Enums give the same type-safety at the
application layer without that migration cost — a deliberate tradeoff,
not an oversight, given how early-stage and likely-to-evolve this
category list still is.
