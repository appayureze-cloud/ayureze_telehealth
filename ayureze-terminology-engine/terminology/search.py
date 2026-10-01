"""Search/resolution over concept_names (spec sections 14 + 16).

Ranking, exactly per spec, strongest evidence first — a concept is
returned once, under the STRONGEST match_type that actually applies to it
(never listed twice under a weaker one too):
  1. exact_preferred_name
  2. exact_synonym          (covers alias/abbreviation too — same
                              "exact string, non-preferred name" evidence)
  3. scientific_botanical_name
  4. transliteration
  5. prefix
  6. fuzzy                  (pg_trgm; confidence = the real similarity
                              score, never inflated)

Every query goes through a single parameterized SQL statement per stage
(spec section 23: parameterized queries, never string-built SQL) and
query length is capped by the caller (api/routes.py) before this module
ever sees it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from normalization import normalize_name

FUZZY_THRESHOLD = 0.3


@dataclass
class SearchMatch:
    concept_id: str
    canonical_name: str
    category: str
    domain: str
    match_type: str
    confidence: float
    matched_name: str


_STAGES: list[tuple[str, str, float]] = [
    # (match_type, name_type_filter_sql, base_confidence)
    ("exact_preferred_name", "n.name_type = 'preferred'", 1.0),
    ("exact_synonym", "n.name_type IN ('synonym', 'alias', 'abbreviation')", 0.9),
    ("scientific_botanical_name", "n.name_type IN ('scientific', 'botanical')", 0.9),
    ("transliteration", "n.name_type = 'transliteration'", 0.85),
]


def search_terms(db: Session, query: str, limit: int = 10) -> list[SearchMatch]:
    normalized_query = normalize_name(query)
    if not normalized_query:
        return []

    results: list[SearchMatch] = []
    seen_concept_ids: set[str] = set()

    for match_type, name_type_filter, confidence in _STAGES:
        rows = db.execute(text(f"""
            SELECT c.concept_id, c.canonical_name, c.category, c.domain, n.name
            FROM concept_names n
            JOIN concepts c ON c.concept_id = n.concept_id
            WHERE n.normalized_name = :q AND {name_type_filter}
            ORDER BY c.confidence DESC
        """), {"q": normalized_query}).fetchall()
        for concept_id, canonical_name, category, domain, matched_name in rows:
            if concept_id in seen_concept_ids:
                continue
            seen_concept_ids.add(concept_id)
            results.append(SearchMatch(concept_id, canonical_name, category, domain, match_type, confidence, matched_name))

    # Prefix stage.
    if len(normalized_query) >= 2:
        rows = db.execute(text("""
            SELECT c.concept_id, c.canonical_name, c.category, c.domain, n.name
            FROM concept_names n
            JOIN concepts c ON c.concept_id = n.concept_id
            WHERE n.normalized_name LIKE :prefix
            ORDER BY length(n.normalized_name) ASC, c.confidence DESC
            LIMIT :limit
        """), {"prefix": normalized_query + "%", "limit": limit * 3}).fetchall()
        for concept_id, canonical_name, category, domain, matched_name in rows:
            if concept_id in seen_concept_ids:
                continue
            seen_concept_ids.add(concept_id)
            results.append(SearchMatch(concept_id, canonical_name, category, domain, "prefix", 0.6, matched_name))

    # Fuzzy stage (pg_trgm) — last, weakest evidence; confidence is the
    # REAL similarity score, never a flat/inflated number.
    rows = db.execute(text("""
        SELECT c.concept_id, c.canonical_name, c.category, c.domain, n.name,
               similarity(n.normalized_name, :q) AS sim
        FROM concept_names n
        JOIN concepts c ON c.concept_id = n.concept_id
        WHERE n.normalized_name % :q
        ORDER BY sim DESC
        LIMIT :limit
    """), {"q": normalized_query, "limit": limit * 3}).fetchall()
    for concept_id, canonical_name, category, domain, matched_name, sim in rows:
        if concept_id in seen_concept_ids or sim < FUZZY_THRESHOLD:
            continue
        seen_concept_ids.add(concept_id)
        results.append(SearchMatch(concept_id, canonical_name, category, domain, "fuzzy", float(sim), matched_name))

    return results[:limit]
