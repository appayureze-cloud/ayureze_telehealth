#!/usr/bin/env python3
"""Runs every real ingester in dependency order (herb_database must run
before bhaishajya, since bhaishajya's HAS_INGREDIENT relationships look up
already-ingested herb concepts) and prints real, honest per-source stats —
not a claim of completeness, an actual count.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from ingestion.ayurwiki.ingest import ingest as ingest_ayurwiki  # noqa: E402
from ingestion.bhaishajya.ingest import ingest as ingest_bhaishajya  # noqa: E402
from ingestion.common import get_or_create_source  # noqa: E402
from ingestion.herb_database.ingest import ingest as ingest_herb_database  # noqa: E402
from ingestion.namaste.ingest import ingest as ingest_namaste  # noqa: E402
from ingestion.pathology.ingest import ingest as ingest_pathology  # noqa: E402
from ingestion.siddhanta.ingest import ingest as ingest_siddhanta  # noqa: E402

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "manifests" / "source_manifest.json"

INGESTERS = [
    ("herb_database", ingest_herb_database),
    ("bhaishajya", ingest_bhaishajya),  # depends on herb_database for HAS_INGREDIENT
    ("pathology", ingest_pathology),
    ("siddhanta", ingest_siddhanta),
    ("ayurwiki", ingest_ayurwiki),
    ("namaste", ingest_namaste),
]


def _register_all_manifest_sources(db) -> None:
    """Registers a Source row for EVERY approved source in the manifest —
    including the 6 adapter-only biomedical terminologies with
    record_count=0 that this codebase deliberately never bulk-ingests
    (spec section 18) — so GET /v1/sources gives a complete, honest
    picture of what's approved/disabled/pending, not just what happened
    to run an ingester."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    for entry in manifest["sources"]:
        get_or_create_source(db, entry)
    db.commit()


def main() -> None:
    db = SessionLocal()
    total_start = time.monotonic()
    try:
        _register_all_manifest_sources(db)
        for name, fn in INGESTERS:
            t0 = time.monotonic()
            stats = fn(db)
            elapsed = time.monotonic() - t0
            print(f"\n=== {name} ({elapsed:.2f}s) ===")
            print(f"  read: {stats.read_count}  imported: {stats.imported_count}  rejected: {stats.rejected_count}")
            print(f"  concepts_created: {stats.concepts_created}  names_created: {stats.names_created}")
            for reason in stats.rejected_reasons:
                print(f"  note: {reason}")
    finally:
        db.close()
    print(f"\nTotal ingestion time: {time.monotonic() - total_start:.2f}s")


if __name__ == "__main__":
    main()
