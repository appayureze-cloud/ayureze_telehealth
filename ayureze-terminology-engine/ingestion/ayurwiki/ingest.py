"""Ingests data/raw/ayurwiki/docs/{herbs,medicines,concepts,physiology} —
3957 real MkDocs Markdown files, CC-BY-SA-4.0 (see the prominent
ShareAlike flag in docs/LICENSE_MATRIX.md — this source's content carries
a real, different obligation from the other four CC-BY-4.0 Ayurveda
sources).

REAL, HONEST DATA QUALITY FINDING (verified by inspecting many files
directly, not assumed): a large fraction of these articles are stub pages
— section headers present with empty/near-empty bodies (e.g. "## Uses\n,
, , ." — literal empty comma-separated placeholders). This ingester does
NOT pretend these are complete: `content_chars` is tracked per record and
any record with fewer than MIN_CONTENT_CHARS of real body text after
stripping frontmatter/headers/boilerplate is counted as a "thin stub" in
IngestionStats, not silently treated as equivalent to a well-populated
article. See docs/DATA_QUALITY_REPORT.md.

Directory -> category mapping (spec section 17's approved domain types):
  docs/herbs      -> HERB (prefix AYU-HERB, continuing herb_database's
                     sequence — same domain type, same ID space)
  docs/medicines  -> MEDICINE_TERM (prefix AYU-MEDICINE — spec lists
                     MEDICINE_TERM as distinct from FORMULATION, which is
                     reserved for the structured Bhaishajya Kalpana Kosha
                     data)
  docs/concepts   -> AYURVEDIC_CONCEPT (prefix AYU-CONCEPT)
  docs/physiology -> AYURVEDIC_CONCEPT (same prefix — no separate
                     "physiology" domain type exists in the approved list;
                     doshas/dhatus/agni are conceptually AYURVEDIC_CONCEPT)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from ingestion.common import IngestionStats, add_name, create_concept, create_source_record, get_or_create_source, link_source_record_to_concept

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "ayurwiki" / "docs"
MANIFEST_SOURCE_NAME = "ayurwiki"
REPO_URL = "https://github.com/hpnadig/ayurwiki"

_FRONTMATTER_RE = re.compile(r"^---\n(?P<yaml>.*?)\n---\n(?P<body>.*)$", re.DOTALL)
_HEADER_RE = re.compile(r"^#+\s*.*$", re.MULTILINE)
_TOC_RE = re.compile(r"^\[TOC\]\s*$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MIN_CONTENT_CHARS = 40

_DIRECTORY_MAP = {
    "herbs": ("HERB", "AYU-HERB"),
    "medicines": ("MEDICINE_TERM", "AYU-MEDICINE"),
    "concepts": ("AYURVEDIC_CONCEPT", "AYU-CONCEPT"),
    "physiology": ("AYURVEDIC_CONCEPT", "AYU-CONCEPT"),
}


def load_manifest_entry() -> dict:
    manifest = json.loads((Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json").read_text())
    return next(s for s in manifest["sources"] if s["source_name"] == MANIFEST_SOURCE_NAME)


def _parse_markdown(raw_text: str) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        return {}, raw_text
    try:
        frontmatter = yaml.safe_load(match.group("yaml")) or {}
    except yaml.YAMLError:
        frontmatter = {}
    return frontmatter, match.group("body")


def _clean_body(body: str) -> str:
    body = _TOC_RE.sub("", body)
    body = _HEADER_RE.sub("", body)
    body = _LINK_RE.sub(r"\1", body)
    lines = [line.strip() for line in body.splitlines()]
    # Drop lines that are just empty-placeholder commas/whitespace, e.g. ", , , ."
    lines = [line for line in lines if line and not re.fullmatch(r"[,\.\s]*", line)]
    return "\n".join(lines).strip()


def ingest(db: Session) -> IngestionStats:
    stats = IngestionStats(source_name=MANIFEST_SOURCE_NAME)
    source = get_or_create_source(db, load_manifest_entry())
    thin_stub_count = 0

    for directory, (category, prefix) in _DIRECTORY_MAP.items():
        dir_path = RAW_DIR / directory
        if not dir_path.is_dir():
            continue
        for file_path in sorted(dir_path.rglob("*.md")):
            stats.read_count += 1
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
            frontmatter, body = _parse_markdown(raw_text)

            title = str(frontmatter.get("title") or "").strip() or file_path.stem.replace("_", " ")
            if not title:
                stats.reject(f"{directory}/{file_path.name}: no usable title (frontmatter and filename both empty)")
                continue

            cleaned_body = _clean_body(body)
            if len(cleaned_body) < _MIN_CONTENT_CHARS:
                thin_stub_count += 1

            relative_path = f"{directory}/{file_path.relative_to(dir_path)}"
            source_record = create_source_record(
                db, source, source_record_id=relative_path,
                original_payload={"title": title, "categories": frontmatter.get("categories"), "date": str(frontmatter.get("date") or ""), "body": raw_text},
                source_url=f"{REPO_URL}/blob/main/docs/{relative_path}",
            )

            definition = cleaned_body[:2000] if cleaned_body else None
            concept = create_concept(
                db, prefix=prefix, domain="AYURVEDA", category=category,
                canonical_name=title, definition=definition,
                confidence=0.4 if len(cleaned_body) < _MIN_CONTENT_CHARS else 0.8,
            )
            link_source_record_to_concept(db, source_record, concept)
            stats.concepts_created += 1

            if add_name(db, concept, title, language="en", name_type="preferred", source_record=source_record, script="Latin"):
                stats.names_created += 1

            stats.imported_count += 1

    db.commit()
    stats.rejected_reasons.append(
        f"informational: {thin_stub_count} of {stats.imported_count} imported articles are thin stubs "
        f"(< {_MIN_CONTENT_CHARS} chars of real body content after cleanup) — see docs/DATA_QUALITY_REPORT.md"
    )
    return stats


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = ingest(db)
        print(result)
    finally:
        db.close()
