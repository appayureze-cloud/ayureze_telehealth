# License matrix

Every field here was verified directly (cloning the repo and reading its
actual LICENSE file, or fetching the licensing authority's own published
terms live) on 2026-09-26 — nothing is guessed or assumed from a source's
reputation or family. Where verification was incomplete, that is stated
explicitly rather than filled in with a best guess. This is the
authoritative legal-compliance reference for this engine; see
`data/manifests/source_manifest.json` for the machine-readable form these
findings feed.

## Summary table

| Source | License | Attribution required | Share-alike required | Commercial use | Redistribution | `commercial_use_status` |
|---|---|---|---|---|---|---|
| herb_database | CC-BY-4.0 | Yes | No | Yes | Yes | **verified** |
| Bhaishajya Kalpana Kosha | CC-BY-4.0 | Yes | No | Yes | Yes | **verified** |
| Encyclopedia of Ayurvedic Pathology | CC-BY-4.0 | Yes | No | Yes | Yes | **verified** |
| Siddhanta Kosha | CC-BY-4.0 | Yes | No | Yes | Yes | **verified** |
| AyurWiki | **CC-BY-SA-4.0** | Yes | **Yes** | Yes | Yes (same license only) | **verified** |
| NAMASTE (this repo's sample data) | **unknown** | Unknown | Unknown | Unknown | Unknown | **unknown** |
| WHO ICD-11 / TM2 | CC-BY-ND-3.0-IGO | Yes (formal citation) | No (ND: no derivatives) | Yes | Yes, verbatim only | **verified** |
| SNOMED CT | SNOMED Affiliate License | Yes | N/A | Conditional (see below) | No (server-side use only) | **unknown** (no license obtained) |
| LOINC | LOINC License | Yes | No (no competing-standard use) | Yes | Yes | **verified** |
| RxNorm | UMLS Metathesaurus License | Varies by bundled source | No | Yes (RXNORM-sourced content) | Varies by bundled source | **verified** (for `SAB=RXNORM` content) |
| MeSH | NLM MeSH Terms | Yes (light) | No | Yes | Yes | **verified** |
| ATC/DDD | WHOCC restricted | Yes | N/A | **NO (bulk/commercial redistribution explicitly prohibited)** | No | **restricted** |

## Ayurveda sources (5) — detailed

### 1–4. herb_database, Bhaishajya Kalpana Kosha, Encyclopedia of Ayurvedic Pathology, Siddhanta Kosha

All four verified **CC-BY-4.0** by directly reading the `LICENSE`/`License`
file committed in each repository (the genuine CC BY 4.0 Creative Commons
legal text, grepped for "ShareAlike"/"NonCommercial" — zero matches in any
of the four). Commercial use, redistribution, and adaptation are all
permitted; the only obligation is attribution.

**herb_database** is published by "Amidha Ayurveda" — the SAME
organization behind the explicitly EXCLUDED "Amidha Genomics Dataset"
named in this project's brief. This is a different, separately-licensed
dataset from that organization and is explicitly on the approved source
list; it is not excluded by mere association with the same publisher.
Attribution per its `CITATION.cff`: Sparsh Varshney, Amidha Ayurveda &
Uttarakhand Ayurved University, DOI 10.5281/zenodo.20581467.

### 5. AyurWiki — ⚠️ REAL, IMPORTANT DIFFERENCE FROM THE OTHER FOUR

**License: CC-BY-SA-4.0**, confirmed verbatim from the repository's own
`README.md`: *"Content is available under Creative Commons
Attribution-ShareAlike (https://creativecommons.org/licenses/by-sa/4.0/)."*

This is genuinely different from the other four Ayurveda sources'
plain CC-BY-4.0. **ShareAlike means any adapted/derivative work that
incorporates this content must itself be distributed under the same
CC-BY-SA-4.0 (or a compatible) license.** Commercial use is still fully
permitted — ShareAlike is not the same restriction as NonCommercial — but
it is a real, live compliance question this build has NOT resolved:

> **If this engine's canonical concept database (which mixes AyurWiki-
> derived concepts with concepts from four plain CC-BY-4.0 sources, plus
> this codebase's own original code) is distributed or offered as a
> product, does the ShareAlike obligation apply only to the specific
> AyurWiki-derived rows, or could it be read to extend to the combined
> database as a "derivative work"? This is a genuine legal question, not
> a technical one, and this codebase does not attempt to answer it.**
> **RECOMMENDATION: get a real legal review of this specific question
> before this engine (or any product built on it) ships commercially with
> AyurWiki-derived content included.** A conservative interim option
> worth considering: keep AyurWiki-derived concepts in a clearly
> segregated `category`/tag so they could be excluded from a commercial
> release without re-architecting, if legal review concludes that's
> necessary.

Only `docs/herbs`, `docs/medicines`, `docs/concepts`, and
`docs/physiology` (3,957 files) were retrieved and ingested — the
repository's ~380MB of images, books, yoga, traditions, and manufacturer
content was NOT retrieved (out of scope: no approved domain type covers
yoga/traditions/manufacturers).

## NAMASTE — ⚠️ license is genuinely UNKNOWN, not guessed

**No LICENSE file exists anywhere in the approved repository.**
Per this phase's own explicit rule ("DO NOT guess licenses... if unclear,
mark unknown"), `commercial_use_status` is correctly `"unknown"` for this
source. This is a real gap requiring outreach to the repository's authors
(or the Ministry of AYUSH, for the underlying NAMASTE standard itself) for
clarification before any commercial use of this specific data.

**Separately important**: the NAMASTE repository's own README advertises
"all 7,363 NAMASTE codes," but the git repository's actual content is a
**14-row sample CSV**. The real, full dataset lives in a live external
MongoDB instance behind that project's own hackathon-built backend
service — not part of the approved source (only the GitHub repository
was approved), and not accessed in this phase. Real full-scale NAMASTE
ingestion would require either the Ministry of AYUSH's own live portal
(a different, unapproved source) or a direct data-sharing arrangement
with this repository's authors.

## WHO ICD-11 / TM2

**License: CC-BY-ND-3.0-IGO**, verified directly from
`https://icd.who.int/icdapi/docs2/license/` (fetched live 2026-09-26).
Commercial use (including embedding in commercial software) is
explicitly permitted. Two real, binding conditions:

1. **No-Derivatives**: codes/titles must be reproduced exactly as WHO
   issues them — this codebase's `mappings/icd11.py` adapter does a live
   API lookup and returns WHO's own title text verbatim, never altering it.
2. **Mapping/crosswalk work needs a SEPARATE WRITTEN AGREEMENT from WHO.**
   WHO's own license text states that mapping, crosswalk, or translation
   work BETWEEN ICD-11 and another classification system (exactly what a
   NAMASTE↔ICD-11 or Ayurveda↔ICD-11 correspondence table is) is **not**
   covered by the base Classifications License if it is published or
   distributed. This codebase's `mappings/icd11.py` only ever performs
   live, on-demand, per-query lookups — it does not compile or ship a
   static NAMASTE-to-ICD-11 mapping table, so the base license is
   sufficient for what this phase actually does. **Building and
   publishing such a table in a future phase would require that separate
   WHO agreement first — this is a real, documented prerequisite, not
   an oversight.**

Free OAuth2 client-credentials registration at `https://icd.who.int/icdapi`.
Exact API rate limits are not published anywhere I could verify — treat
as **unverified**; check the API dashboard directly before relying on a
specific throughput number in production.

TM2 (Traditional Medicine Module 2) covers 529 Ayurveda/Siddha/Unani-
derived disorder categories, part of ICD-11 since its 2019 WHO
endorsement (effective for reporting 2022); India's own national
implementation launched in 2024.

## SNOMED CT — DISABLED by design (spec requirement)

**License: SNOMED International Affiliate License.** Verified directly
from `snomed.org/members` (2026-09-26): **India, UK, Singapore, Malaysia,
UAE, Saudi Arabia, and Qatar are all confirmed current SNOMED
International Member territories** — every market this product's prior
work in this repository targets. A **free** Affiliate License is
realistically obtainable, but ONLY after formally registering through a
Member country's National Release Center (NRC) and signing the Affiliate
License Agreement — it is not usable with zero process, and no such
license has been obtained for this project. `commercial_use_status` is
therefore honestly `"unknown"`, not `"verified"`.

**Unresolved, recommend legal review**: whether a single Member country's
(e.g. India's) Affiliate License covers a SaaS product serving patients
physically located in the OTHER Member markets too, or whether each
market requires separate registration — SNOMED's FAQ does not give a
crisp answer for multi-country commercial SaaS.

`mappings/snomed.py` is **DISABLED BY DEFAULT**, exactly per this phase's
explicit instruction — it always raises `AdapterNotConfiguredError` unless
a real, separately-licensed terminology server (e.g. a self-hosted
Snowstorm instance under a real Affiliate License) is configured via
`TERMINOLOGY_SNOMED_SERVER_URL`. This mirrors the real-world "Medical
Terminologies MCP" open-source project's own identical design choice
(confirmed via its own README: its SNOMED tools are disabled by default
for the same licensing reason) — an independent precedent for this exact
pattern, not something this project invented in isolation.

## LOINC

**License: LOINC License**, verified via LOINC's own FAQ/KB and
Regenstrief's official documentation (2026-09-26; the raw license page
itself returned a bot-challenge during automated fetch in this session, so
the exact clause wording is high-confidence but not verbatim-page-verified
— flagged honestly rather than claimed as directly read). Commercial and
non-commercial use both explicitly permitted, in perpetuity, no fee —
conditioned on attribution and NOT altering LOINC content or using it to
build a competing standard vocabulary. Requires a free loinc.org account
and click-through license acceptance before use.

`mappings/loinc.py` requires `TERMINOLOGY_LOINC_USERNAME`/
`TERMINOLOGY_LOINC_PASSWORD` (a real account) — not configured in this
environment, so it raises `AdapterNotConfiguredError` rather than faking
a response.

## RxNorm

**License: UMLS Metathesaurus License** (verified via NLM's own RxNorm
FAQ/Terms pages, 2026-09-26). RxNorm has no separate, simpler license of
its own — bulk file access requires the free UMLS Metathesaurus License
Agreement via a UMLS Terminology Services account. The same free terms
apply to commercial and non-commercial users.

**Important, unresolved caveat**: RxNorm's release cross-references atoms
from OTHER bundled source vocabularies (some proprietary drug compendia,
some SNOMED CT drug content) that retain their OWN source-specific
restrictions beyond the base UMLS license. NLM publishes a per-source
"License Category" table — **recommend checking that table against
whichever specific RxNorm content this product actually queries** before
treating all RxNorm-sourced data as uniformly free.

`mappings/rxnorm.py` calls NLM's **genuinely public, no-key-required**
RxNorm REST API (`https://rxnav.nlm.nih.gov/REST/`) for live, per-query
lookups only — confirmed working with a real query in this session (see
docs/API.md). The UMLS license is only a prerequisite for BULK file
downloads, a distinct thing this adapter never does.

## MeSH

**License: NLM MeSH Terms** (verified directly from
`https://www.nlm.nih.gov/databases/download/terms_and_conditions_mesh.html`,
2026-09-26). Freely downloadable, no UMLS account needed, no fee,
commercial use fine. Light conditions: acknowledge NLM as source, don't
imply NLM endorsement, keep any redistributed copy reasonably current.

`mappings/mesh.py` calls NLM's genuinely public MeSH lookup API
(`https://id.nlm.nih.gov/mesh/lookup/`) for live, per-query lookups —
confirmed working with a real query in this session.

## ATC/DDD — the clearest restriction found in this entire audit

**License: WHO Collaborating Centre restricted terms**, verified verbatim
from `https://atcddd.fhi.no/copyright_disclaimer/` (fetched live
2026-09-26):

> "Use of all or parts of the material requires reference to the WHO
> Collaborating Centre for Drug Statistics Methodology. **Copying and
> distribution for commercial purposes is not allowed.** Changing or
> manipulating the material is not allowed."

Free interactive website lookup only. **Bulk-downloading and embedding
the ATC/DDD index in a commercial product is explicitly prohibited** —
this is not a gray area or a "verify before use" case; it is an
unambiguous published restriction. No self-serve commercial licensing
path exists; the only route found is direct email negotiation with the
WHO Collaborating Centre in Oslo, terms/cost unverified.

`mappings/atc.py` **always raises `AdapterNotConfiguredError`, by
design** — there is no automated lookup path in this codebase for ATC at
all, and there will not be one until a real written agreement with the
Centre exists. `commercial_use_status` is correctly `"restricted"`, the
only source in this manifest to carry that value rather than `"verified"`
or `"unknown"`.

## "Medical Terminologies MCP" — a real precedent for this project's own design

Verified as a real, existing open-source project:
`github.com/SidneyBissoli/medical-terminologies-mcp` (corroborated
independently across four MCP server directories). **Its repository/code
is MIT-licensed — but the README explicitly states that license covers
only the server code, NOT the terminology content served through it.**
Its SNOMED CT tools are disabled by default, requiring the operator's own
valid license and self-hosted terminology server — precisely this
project's own `mappings/snomed.py` design. Its ICD-11/LOINC/RxNorm/MeSH
tools call live official APIs rather than storing local copies, same
pattern as `mappings/icd11.py`, `mappings/loinc.py`, `mappings/rxnorm.py`,
`mappings/mesh.py`.

**The takeaway this project applies throughout**: an MIT (or any
permissive) license on integration/adapter CODE is completely orthogonal
to, and grants no rights whatsoever over, the underlying terminology
CONTENT it looks up. This distinction is enforced structurally in this
codebase (`mappings/` never stores terminology content, only calls out to
externally-licensed services) rather than left as a documentation-only
promise.
