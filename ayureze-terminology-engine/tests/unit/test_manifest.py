"""License manifest validation (spec section 21: "license manifest
validation") — enforces the manifest's own rules on itself: every source
must have every required field, and commercial_use_status must be
"unknown" whenever the notes don't demonstrate real verification (spec
section 6: "DO NOT guess licenses").
"""

import json
from pathlib import Path

import pytest

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "manifests" / "source_manifest.json"

REQUIRED_FIELDS = {
    "source_name", "repository_url", "version_or_commit", "license", "retrieved_at",
    "record_count", "files", "schema_summary", "commercial_use_status", "notes",
}

APPROVED_SOURCE_NAMES = {
    "herb_database", "bhaishajya_kalpana_kosha", "encyclopedia_of_ayurvedic_pathology",
    "siddhanta_kosha", "ayurwiki", "namaste",
    "who_icd11_tm2", "snomed_ct", "loinc", "rxnorm", "mesh", "atc",
}

EXCLUDED_SOURCE_NAMES = {"aditya_bavadekar_gist", "ayuunity", "amidha_genomics_dataset"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_is_valid_json(manifest):
    assert "sources" in manifest
    assert isinstance(manifest["sources"], list)


def test_every_source_has_all_required_fields(manifest):
    for entry in manifest["sources"]:
        missing = REQUIRED_FIELDS - set(entry.keys())
        assert not missing, f"{entry.get('source_name')} missing fields: {missing}"


def test_commercial_use_status_is_one_of_the_three_allowed_values(manifest):
    for entry in manifest["sources"]:
        assert entry["commercial_use_status"] in {"verified", "unknown", "restricted"}


def test_namaste_license_is_honestly_unknown_not_guessed(manifest):
    namaste = next(s for s in manifest["sources"] if s["source_name"] == "namaste")
    assert namaste["license"] == "unknown"
    assert namaste["commercial_use_status"] == "unknown"


def test_ayurwiki_is_flagged_as_sharealike_not_plain_cc_by(manifest):
    ayurwiki = next(s for s in manifest["sources"] if s["source_name"] == "ayurwiki")
    assert ayurwiki["license"] == "CC-BY-SA-4.0"
    assert "sharealike" in ayurwiki["notes"].lower() or "share-alike" in ayurwiki["notes"].lower() or "share alike" in ayurwiki["notes"].lower()


def test_atc_is_flagged_restricted_not_verified(manifest):
    atc = next(s for s in manifest["sources"] if s["source_name"] == "atc")
    assert atc["commercial_use_status"] == "restricted"


def test_no_excluded_source_present(manifest):
    names = {s["source_name"] for s in manifest["sources"]}
    assert not (names & EXCLUDED_SOURCE_NAMES)


def test_all_approved_sources_are_present(manifest):
    names = {s["source_name"] for s in manifest["sources"]}
    assert APPROVED_SOURCE_NAMES <= names


def test_record_count_is_zero_for_adapter_only_sources_never_bulk_copied(manifest):
    adapter_only = {"who_icd11_tm2", "snomed_ct", "loinc", "rxnorm", "mesh", "atc"}
    for entry in manifest["sources"]:
        if entry["source_name"] in adapter_only:
            assert entry["record_count"] == 0, f"{entry['source_name']} should have record_count=0 (adapter architecture, not bulk-copied)"
