# Data quality report

Real numbers from this build's own last full ingestion + deduplication
run (2026-09-26). Nothing here is estimated — every count is either a
direct SQL query result against the actual database or a stat object
`ingestion/common.py`'s `IngestionStats` recorded during that exact run.
Conflicts and quality issues are reported, never silently discarded (spec
section 22).

## Source record counts

| Source | Records in source | Imported | Rejected |
|---|---|---|---|
| herb_database | 360 | 360 | 0 |
| bhaishajya_kalpana_kosha | 176 | 176 | 0 |
| encyclopedia_of_ayurvedic_pathology | 203 | 203 | 0 |
| siddhanta_kosha | 162 | 162 | 0 |
| ayurwiki | 3,957 | 3,957 | 0 |
| namaste | 14 | 14 | 0 |
| **Total** | **4,872** | **4,872** | **0** |

Zero hard rejections — every real record that had the minimum required
field (a name) was imported. This does NOT mean zero quality issues; see
below for what "0 rejected" is hiding.

## Imported record counts by category

| Category | Count |
|---|---|
| HERB | 2,575 |
| MEDICINE_TERM | 1,536 |
| AYURVEDIC_CONCEPT | 206 |
| FORMULATION | 176 |
| PATHOLOGY_TERM | 203 |
| SIDDHANTA | 162 |
| DISEASE (unverified biomedical stubs) | 213 |
| NAMASTE_CODE | 14 |
| **Total concepts** | **5,085** |

## Merged concepts

**Zero** — this build's deduplication pipeline (spec section 13) never
auto-merges; it only ever populates the `deduplication_candidates` review
queue. No concept has been merged, deleted, or had its `concept_id`
retired in this phase.

## Duplicate candidates found (real deduplication run)

| Stage | Pairs found |
|---|---|
| exact_normalized_match | 51 |
| known_synonym_match | 210 |
| scientific_name_match | 2 |
| high_confidence_fuzzy_match | 539 |
| **Total** | **802** |

The `scientific_name_match` stage has 2 real examples, confirmed by
directly inspecting their names: **Kutaj / Indrayava** and **Shigru /
Shigru Patra** each share an identical botanical name (Kutaj/Indrayava are
both *Holarrhena antidysenterica*) but NO overlapping synonym — their
Sanskrit synonym lists are genuinely different words (e.g. Kutaj's
"Kalinga" vs. Indrayava's "Kalingaka" — close but not identical after
normalization, so they correctly do NOT trigger the exact-match synonym
stage). This is exactly the case this stage exists for: real botanical-
name-only duplicates that a synonym-based check alone would miss. Most
other botanical-name duplicates in this dataset (e.g. Giloy/Amrita, below)
also happen to share an exact synonym and so are caught by the earlier,
broader `known_synonym_match` stage instead — each pair is recorded once,
under the strongest evidence that first applies (see
`deduplication/pipeline.py`'s own docstring). Both stages are directly
exercised in `tests/integration/test_deduplication.py`.

### A real, notable finding: Giloy and Amrita

`AYU-HERB-000004` ("Giloy") and `AYU-HERB-000078` ("Amrita") are BOTH
*Tinospora cordifolia* and share the Sanskrit synonyms "Guduchi",
"Madhuparni", and "Chinnaruha" — a genuinely high-confidence real-world
duplicate present in the herb_database source itself, not manufactured
for this report. Giloy's synonym set additionally overlaps with **two
more** distinct herb concepts (`AYU-HERB-000073`, `AYU-HERB-000110`,
`AYU-HERB-000082`) via shared folk names — flagged in
`deduplication_candidates`, genuinely unresolved, and exactly the kind of
case a domain expert (not an algorithm) should adjudicate: is this the
same plant catalogued twice under different names, or do multiple
distinct plants legitimately share a folk name in classical Ayurvedic
nomenclature? This build does not guess.

A **third**, independent occurrence of the same plant
(`AYU-HERB-002372`, "Tinospora cordifolia - Heart-leaved moonseed, ಅಮರ,
Giloe, ...") was also ingested from AyurWiki — a real example of
**cross-source**, not just within-source, duplication.

## Unresolved conflicts

- **107 ingredient references** in the Bhaishajya Kalpana Kosha data
  (`main_ingredients[]`) had no exact-normalized-name match against any
  existing HERB or FORMULATION concept — the formulation source's own
  ingredient phrasing doesn't always match another entry's canonical
  spelling one-to-one. These are preserved as `alias`-type names on the
  formulation's own concept rather than silently dropped, but no
  `HAS_INGREDIENT` relationship could be created for them. (466 ingredient
  references WERE successfully resolved and linked — some to HERB
  concepts, some to other FORMULATION concepts for real pharmacological
  reasons, e.g. a rasayana genuinely listing "Loha Bhasma" iron-ash as an
  ingredient; see `docs/INGESTION.md`'s idempotency section for the full
  investigation of this.)
- **22 of 162** Siddhanta Kosha records' `name` field didn't match the
  expected `"Latin (Devanagari)"` format — used verbatim as a single name
  rather than split, and counted, not silently mishandled.
- **213 unverified BIO-DISEASE stub concepts** were created purely from
  Ayurveda/interop sources' own claimed biomedical correlates (the
  pathology source's `correlation` field, NAMASTE's parenthetical
  gloss) — these are NOT verified against any real biomedical
  terminology (ICD-11, SNOMED). They are linked via `RELATED_TO`
  (never `EXACT_MATCH`), confidence 0.5, with evidence citing exactly
  which source field asserted the correlation.

## Missing fields / malformed records

- **AyurWiki: 11 of 3,957** imported articles are "thin stubs" — fewer
  than 40 characters of real body content after stripping frontmatter,
  markdown headers, and empty comma-placeholder lines (e.g. `## Uses\n,
  , , .`). These were still imported (a stub page is still real evidence
  that the term exists and what AyurWiki categorizes it as), but marked
  with a lower `confidence` (0.4 vs. 0.8 for a properly-populated
  article) precisely so a consumer of this data can distinguish "we have
  a real definition" from "we only confirmed this term exists."
  Un-scientifically-verified, but honestly: given how many AyurWiki
  articles read as auto-generated stub templates (empty "Uses"/"Parts
  Used"/"Chemical Composition" sections across many herb pages beyond
  just these 11 flagged ones — the 40-character threshold is
  deliberately lenient, counting reference-list boilerplate as "content"
  in borderline cases), the REAL proportion of low-informational-value
  AyurWiki articles is almost certainly higher than 11/3,957 suggests.
  This is flagged honestly as a real limitation of the automated
  thin-stub heuristic, not resolved by manual review in this phase.
- **herb_database**: every one of the 360 records had all fields
  populated in the fields this ingester uses (`name`, `botanical_name`,
  `english_name`, `preview`, `sanskrit_synonyms`) — no missing-field
  issues found for this source.
- **No stable source identifier exists** in 5 of 6 sources
  (herb_database, bhaishajya, pathology, siddhanta, ayurwiki all lack a
  numeric/code ID field) — this build uses the array index or file path
  as `source_record_id`, which means re-ingestion is NOT currently
  idempotent (see `docs/INGESTION.md`'s "known limitation").

## Unknown licenses

**namaste**: no LICENSE file exists in the approved repository —
`commercial_use_status: "unknown"`, honestly, not guessed. See
`docs/LICENSE_MATRIX.md`.

## License conflicts between sources

**AyurWiki (CC-BY-SA-4.0, ShareAlike) vs. the other four Ayurveda sources
(plain CC-BY-4.0)** — a real, unresolved compliance question about
whether combining ShareAlike-licensed concepts into an otherwise
proprietary canonical database creates a ShareAlike obligation on the
combined output. See `docs/LICENSE_MATRIX.md`'s prominent flag; this
report does not attempt to resolve it, only surfaces it clearly.

## Unresolved concepts

All 5,085 concepts have `status = "candidate"` — none has been reviewed
and promoted to `"active"`, and none is `"certified"` for any downstream
medical/clinical use. This is Phase 1 infrastructure output, not a
clinically-validated terminology service.
