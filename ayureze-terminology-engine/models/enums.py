"""Every controlled vocabulary this schema uses. Plain Python str enums
stored as VARCHAR (not native Postgres ENUM types) deliberately — adding a
new category/relationship type later is an application-level change, not
a schema migration that locks table rows. Validation still happens at the
Pydantic/SQLAlchemy layer.
"""

from __future__ import annotations

from enum import Enum


class Domain(str, Enum):
    AYURVEDA = "AYURVEDA"
    BIOMEDICAL = "BIOMEDICAL"
    INTEROP = "INTEROP"  # NAMASTE-derived concepts, pending their own mapping


class Category(str, Enum):
    # Ayurvedic domain types (spec section 17) — extract only what exists
    # in a source; do not invent categories a source doesn't support.
    HERB = "HERB"
    FORMULATION = "FORMULATION"
    AYURVEDIC_CONCEPT = "AYURVEDIC_CONCEPT"
    PATHOLOGY_TERM = "PATHOLOGY_TERM"
    SIDDHANTA = "SIDDHANTA"
    BOTANICAL_TERM = "BOTANICAL_TERM"
    MEDICINE_TERM = "MEDICINE_TERM"
    # Biomedical domain types (spec section 18) — populated only via the
    # adapter architecture, never bulk-copied into this table.
    DRUG = "DRUG"
    LAB = "LAB"
    DISEASE = "DISEASE"
    # Interoperability (NAMASTE) — a distinct category so it is never
    # confused with a directly-sourced Ayurveda or biomedical concept
    # (spec section 19: "Do not treat the FHIR service itself as the
    # canonical medical truth").
    NAMASTE_CODE = "NAMASTE_CODE"


class ConceptStatus(str, Enum):
    ACTIVE = "active"
    CANDIDATE = "candidate"  # created but not yet reviewed/deduplicated
    DEPRECATED = "deprecated"  # superseded by a merge decision
    REJECTED = "rejected"  # a deduplication candidate rejected as a merge, but the concept itself stands


class NameType(str, Enum):
    PREFERRED = "preferred"
    SYNONYM = "synonym"
    ALIAS = "alias"
    SCIENTIFIC = "scientific"
    BOTANICAL = "botanical"
    TRANSLITERATION = "transliteration"
    ABBREVIATION = "abbreviation"


class RelationshipType(str, Enum):
    # Within-registry relationships.
    SYNONYM_OF = "SYNONYM_OF"
    ALIAS_OF = "ALIAS_OF"
    HAS_INGREDIENT = "HAS_INGREDIENT"
    PART_OF = "PART_OF"
    RELATED_TO = "RELATED_TO"
    BROADER_THAN = "BROADER_THAN"
    NARROWER_THAN = "NARROWER_THAN"
    # Cross-system mappings (spec section 11) — NEVER auto-assigned
    # EXACT_MATCH between an Ayurvedic and a biomedical concept; only
    # created when a source explicitly states the correspondence (e.g. the
    # Encyclopedia of Ayurvedic Pathology's own "correlation" field, or
    # NAMASTE's own tm2_code/icd_biomedicine_code fields).
    EXACT_MATCH = "EXACT_MATCH"
    CLOSE_MATCH = "CLOSE_MATCH"
    NO_ESTABLISHED_EQUIVALENCE = "NO_ESTABLISHED_EQUIVALENCE"


class DeduplicationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DeduplicationReason(str, Enum):
    EXACT_NORMALIZED_MATCH = "exact_normalized_match"
    KNOWN_SYNONYM_MATCH = "known_synonym_match"
    SCIENTIFIC_NAME_MATCH = "scientific_name_match"
    HIGH_CONFIDENCE_FUZZY_MATCH = "high_confidence_fuzzy_match"


class MatchType(str, Enum):
    """Search result classification (spec section 14) — ranked in this
    exact order; a search response must never claim a stronger match type
    than what actually matched."""

    EXACT_PREFERRED_NAME = "exact_preferred_name"
    EXACT_SYNONYM = "exact_synonym"
    SCIENTIFIC_BOTANICAL_NAME = "scientific_botanical_name"
    TRANSLITERATION = "transliteration"
    PREFIX = "prefix"
    FUZZY = "fuzzy"


class CommercialUseStatus(str, Enum):
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"
