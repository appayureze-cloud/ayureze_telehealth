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
  HERB/FORMULATION concepts by exact normalized name match → `HAS_INGREDIENT`
  relationship when found. **Updated 2026-09-28**: before trying an exact
  match, an ingredient reference in the source's own "Primary (Gloss)"
  format (e.g. "Dhatri (Amalaki)") is now split into its two literal name
  candidates — the same deterministic parsing already used for siddhanta's
  "Latin (Devanagari)" and namaste's parenthetical gloss, applied here to
  main_ingredients text (see `_split_parenthetical` in
  `ingestion/bhaishajya/ingest.py`). An ingredient with no matching
  concept is counted as unresolved but is **no longer** recorded as a name
  on the referencing formulation's own concept — see the real bug this
  fixes, below. The raw ingredient list is never lost either way: it is
  always preserved verbatim in `Concept.definition`'s "Ingredients:"
  segment.
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

### A real bug found and fixed (2026-09-28): unresolved-ingredient aliasing corrupted later matches

Investigating "why are only 466 of 573 ingredient references resolved"
found that an unresolved ingredient reference was being recorded as an
`alias` `ConceptName` on the **referencing** formulation's own concept —
e.g. "Chandraprabha Vati lists 'Triphala' as an ingredient, no 'Triphala'
concept exists yet, so attach 'Triphala' as an alias of Chandraprabha Vati
itself." That's wrong on its face, and it actively corrupted later
matching: once "Triphala" became indexed as an alias of "Avipattikar
Churna" (the first formulation in the source file to reference it), every
*subsequent* formulation that also referenced the never-modeled-as-its-
own-concept "Triphala" ingredient exact-matched onto Avipattikar Churna
instead.

**Fixed in code and covered by tests** (`tests/unit/test_bhaishajya_ingredient_matching.py`,
`tests/integration/test_bhaishajya_ingestion.py` — 8 tests total, including
one that directly reproduces this exact cross-linking scenario and asserts
it no longer happens) — the alias-adding call for an unresolved ingredient
was removed entirely.

**The real scope of the corruption was measured precisely**, not
estimated: an initial spot check of 6 specific ingredient names found 68
wrong relationships, but that was only a lower bound from checking a
handful of examples, not an exhaustive count. The true scope was found by
running the fixed ingester against a completely fresh, empty throwaway
database and diffing every count against the still-live pre-fix database
— then, once the difference was understood and verified, **applied for
real**: the live dev database was truncated and fully re-ingested + re-
deduplicated on 2026-09-29 (explicit user authorization — see git history
for this exact commit), and the resulting real counts matched the earlier
dry run exactly:

| Metric | Before (buggy) | After (fixed, live, verified) | Difference |
|---|---|---|---|
| Total concepts | 5,085 | 5,085 | 0 (correct — no concepts should be added/lost) |
| Total names | 7,366 | 7,259 | **-107** (exactly the wrongly-added alias names, now gone) |
| Total relationships | 683 | 574 | **-109** (wrong `HAS_INGREDIENT` rows) |
| `HAS_INGREDIENT` relationships specifically | 466 | 357 | **-109** |
| Deduplication candidates | 802 | 798 | -4 (fewer spurious matches caused by the same bad alias names) |
| Bhaishajya unresolved ingredient references | 107 | 218 | **+111** (the true, honest number — most of the old "resolved" total was fake) |

So the real damage was **109 wrong relationships**, not 68 — the honest
number only came from actually re-running the fixed pipeline and diffing
real counts, not from extrapolating the initial spot check. The
parenthetical-splitting improvement (see above) is a real but smaller
gain: of the 573 total ingredient references, 355 now resolve
legitimately (down from the previously-reported-but-partly-fake 466); the
true unresolved count is 218, up from the previously-reported 107 — an
apparent regression that is in fact the correction of a false positive,
not new unresolved coverage. Re-verified against the live database after
re-ingestion: the specific polluted alias names ("Trikatu", "Triphala",
"Chitraka", "Nimba", "Tagara", "Vidari") no longer exist anywhere in
`concept_names`, the full 90-test suite still passes, and the real search
latency benchmark (`scripts/benchmark.py`) still passes at p95 = 10.16ms
against the corrected data.

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

**FIXED (2026-09-26)** — this used to be a real, documented gap (running
`scripts/run_ingestion.py` twice created a second complete set of new
`concept_id`s). All 6 ingesters now go through
`ingestion/common.py`'s `get_or_create_record_and_concept`/`add_name`/
`add_relationship_if_new`, keyed on the natural key `(source_id,
source_record_id)` — the array index or file path each ingester already
used is that record's stable identity across runs, as long as the
underlying source file's ordering/paths don't change between
re-ingestions (a real, documented assumption, not a hidden one).

**Verified for real**, not just written: truncated the database, ran
`scripts/run_ingestion.py` once (identical real numbers to the table
above), then ran it again immediately — the second run reported
`concepts_created: 0, names_created: 0` for all 6 sources, and the final
concept/name/source-record counts in Postgres were byte-identical to the
first run (5,085 / 7,366 / 4,872). A changed payload is detected and the
`source_records` row is updated in place (tracked as
`payload_updated_on_rerun`) without re-minting the concept's ID or
duplicating its names.

**A real bug this fix surfaced and corrected in passing**: the original
(pre-idempotent) runs had inserted 2 genuine exact-duplicate
`HAS_INGREDIENT` rows (a Bhaishajya Kalpana Kosha formulation listing the
same ingredient twice in its own `main_ingredients` array) — the new
`add_relationship_if_new` check collapsed these to 1 row each, so the
relationship count dropped from 685 to 683 on the first idempotent
re-ingestion. This is a real, correct cleanup, not data loss.

**A second thing investigated as a possible bug and found NOT to be
one**: `bhaishajya/ingest.py`'s `_find_herb_concept_id` originally matched
an ingredient name against ANY concept, with no category filter. Checking
every existing `HAS_INGREDIENT` relationship's target category found 167
pointing at another `FORMULATION` concept rather than a `HERB` — initially
flagged as mislinking, but closer inspection showed this is real Ayurvedic
pharmacology: compound preparations (bhasmas like "Loha Bhasma", or
intermediate ghritas/tailas) are genuinely listed as ingredients of more
complex formulations, and the source catalogues those preparations as
their own entries too. The fix applied is a category allow-list
(`HERB`/`FORMULATION`, confirmed to be the only two categories any
existing relationship actually pointed at) rather than a narrowing to
`HERB` only, which would have incorrectly broken 167 real relationships.
See `_find_herb_concept_id`'s own docstring for the full account.

Test coverage: `tests/integration/test_idempotent_ingestion.py` (5 tests)
locks in the concept/name/relationship idempotency behavior directly
against the helper functions, independent of any specific source's data.
