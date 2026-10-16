"""Real HTTP requests against the FastAPI app (spec section 21: "API
responses"), backed by a real Postgres database via dependency override —
no mocking of the database layer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database import get_db
from models import Concept, ConceptName, ConceptRelationship, DeduplicationCandidate, Source, SourceRecord


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db):
    source = Source(
        source_name="api_test_source", repository_url="https://example.test/repo",
        version_or_commit="v1", license="CC-BY-4.0", retrieved_at="2026-09-26",
        record_count=1, commercial_use_status="verified",
    )
    db.add(source)
    db.flush()

    concept = Concept(
        concept_id="TEST-API-HERB-1", domain="AYURVEDA", category="HERB", canonical_name="Tulsi",
        definition="A holy herb.", status="candidate", confidence=1.0,
    )
    db.add(concept)
    db.flush()

    db.add(ConceptName(concept_id=concept.concept_id, name="Tulsi", normalized_name="tulsi", language="sa", script="Latin", name_type="preferred"))
    record = SourceRecord(
        source_id=source.id, source_record_id="0", concept_id=concept.concept_id,
        original_payload={"name": "Tulsi"}, source_version="v1",
        source_url="https://example.test/repo", ingestion_timestamp="2026-09-26T00:00:00+00:00",
    )
    db.add(record)

    other = Concept(concept_id="TEST-API-HERB-2", domain="AYURVEDA", category="HERB", canonical_name="Amla", status="candidate", confidence=1.0)
    db.add(other)
    db.flush()
    db.add(ConceptRelationship(
        concept_id_a=concept.concept_id, concept_id_b=other.concept_id,
        relationship_type="RELATED_TO", evidence="test evidence", confidence=0.5,
    ))
    db.commit()
    return concept


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_search_endpoint_real_response(client, seeded):
    response = client.get("/v1/terminology/search", params={"q": "Tulsi"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Tulsi"
    assert any(m["concept_id"] == "TEST-API-HERB-1" for m in body["matches"])


def test_resolve_endpoint_matches_spec_shape(client, seeded):
    response = client.post("/v1/terminology/resolve", json={"text": "Tulsi"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Tulsi"
    assert body["matches"][0]["concept_id"] == "TEST-API-HERB-1"
    assert "match_type" in body["matches"][0]
    assert "confidence" in body["matches"][0]


def test_get_concept_endpoint(client, seeded):
    response = client.get("/v1/terminology/concepts/TEST-API-HERB-1")
    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Tulsi"


def test_get_concept_404_for_unknown_id(client, seeded):
    response = client.get("/v1/terminology/concepts/DOES-NOT-EXIST")
    assert response.status_code == 404


def test_get_concept_names_endpoint(client, seeded):
    response = client.get("/v1/terminology/concepts/TEST-API-HERB-1/names")
    assert response.status_code == 200
    names = response.json()
    assert any(n["name"] == "Tulsi" and n["name_type"] == "preferred" for n in names)


def test_get_concept_sources_endpoint(client, seeded):
    response = client.get("/v1/terminology/concepts/TEST-API-HERB-1/sources")
    assert response.status_code == 200
    sources = response.json()
    assert sources[0]["source_name"] == "api_test_source"


def test_get_concept_relationships_endpoint(client, seeded):
    response = client.get("/v1/terminology/concepts/TEST-API-HERB-1/relationships")
    assert response.status_code == 200
    rels = response.json()
    assert rels[0]["relationship_type"] == "RELATED_TO"
    assert rels[0]["concept_id_b"] == "TEST-API-HERB-2"


def test_list_sources_endpoint(client, seeded):
    response = client.get("/v1/sources")
    assert response.status_code == 200
    assert any(s["source_name"] == "api_test_source" for s in response.json())


def test_stats_endpoint(client, seeded):
    response = client.get("/v1/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_concepts"] >= 2
    assert "HERB" in body["concepts_by_category"]


def test_search_query_too_long_returns_422(client):
    response = client.get("/v1/terminology/search", params={"q": "a" * 300})
    assert response.status_code == 422


def test_resolve_with_empty_text_returns_422(client):
    response = client.post("/v1/terminology/resolve", json={"text": ""})
    assert response.status_code == 422


def test_search_sql_injection_attempt_is_treated_as_literal_text(client, seeded):
    response = client.get("/v1/terminology/search", params={"q": "Tulsi'; DROP TABLE concepts;--"})
    assert response.status_code == 200  # never a 500, never actually executes anything


# --- /v1/biomedical/{system}/search ---
#
# rxnorm/mesh's SUCCESS path genuinely calls live public APIs (verified
# manually with real queries — see docs/API.md's captured real responses,
# e.g. a real "ibuprofen" RxNorm lookup and a real "hypertension" MeSH
# lookup, both returned live 2026-09-26) — deliberately NOT re-verified
# over the network in this automated suite, to keep it fast and immune to
# network flakiness/rate limits. Everything below IS network-free and
# real: the routing/error-handling logic, and every gated adapter's
# fail-closed check (which happens before any network call is attempted).

def test_unknown_biomedical_system_returns_404(client):
    response = client.get("/v1/biomedical/fakesystem/search", params={"q": "test"})
    assert response.status_code == 404
    assert "fakesystem" in response.json()["detail"]


def test_snomed_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TERMINOLOGY_SNOMED_SERVER_URL", raising=False)
    response = client.get("/v1/biomedical/snomed/search", params={"q": "diabetes"})
    assert response.status_code == 503
    assert "SNOMED" in response.json()["detail"]


def test_icd11_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TERMINOLOGY_ICD11_CLIENT_ID", raising=False)
    monkeypatch.delenv("TERMINOLOGY_ICD11_CLIENT_SECRET", raising=False)
    response = client.get("/v1/biomedical/icd11/search", params={"q": "diabetes"})
    assert response.status_code == 503
    assert "ICD-11" in response.json()["detail"]


def test_loinc_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TERMINOLOGY_LOINC_USERNAME", raising=False)
    monkeypatch.delenv("TERMINOLOGY_LOINC_PASSWORD", raising=False)
    response = client.get("/v1/biomedical/loinc/search", params={"q": "diabetes"})
    assert response.status_code == 503
    assert "LOINC" in response.json()["detail"]


def test_atc_always_returns_503():
    response = TestClient(app).get("/v1/biomedical/atc/search", params={"q": "diabetes"})
    assert response.status_code == 503
    assert "WHO Collaborating Centre" in response.json()["detail"]


def test_biomedical_search_success_shape(client, monkeypatch):
    """A fake, in-process adapter proves the route correctly maps a
    BiomedicalLookupResult into the API's response schema — the real
    rxnorm/mesh network success path is verified manually (see note above
    this test block)."""
    import api.routes as routes_module
    from mappings.base import BiomedicalAdapter, BiomedicalLookupResult

    class _FakeAdapter(BiomedicalAdapter):
        def lookup(self, term):
            return [BiomedicalLookupResult(code="FAKE123", display=f"Fake result for {term}", source="FakeSource", source_url="https://example.test/FAKE123")]

    monkeypatch.setitem(routes_module._BIOMEDICAL_ADAPTERS, "rxnorm", _FakeAdapter)
    response = client.get("/v1/biomedical/rxnorm/search", params={"q": "aspirin"})
    assert response.status_code == 200
    body = response.json()
    assert body["system"] == "rxnorm"
    assert body["query"] == "aspirin"
    assert body["results"] == [{"code": "FAKE123", "display": "Fake result for aspirin", "source": "FakeSource", "source_url": "https://example.test/FAKE123"}]


def test_biomedical_search_query_too_long_returns_422(client):
    response = client.get("/v1/biomedical/rxnorm/search", params={"q": "a" * 300})
    assert response.status_code == 422


# --- /v1/deduplication/candidates ---

@pytest.fixture()
def pending_candidate(db, seeded):
    other = db.query(Concept).filter_by(concept_id="TEST-API-HERB-2").one()
    candidate = DeduplicationCandidate(candidate_a=seeded.concept_id, candidate_b=other.concept_id, similarity=0.9, reason="high_confidence_fuzzy_match", status="pending")
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def test_list_deduplication_candidates_defaults_to_pending(client, pending_candidate):
    response = client.get("/v1/deduplication/candidates")
    assert response.status_code == 200
    body = response.json()
    assert any(c["id"] == pending_candidate.id for c in body)
    row = next(c for c in body if c["id"] == pending_candidate.id)
    assert row["candidate_a_name"] == "Tulsi"
    assert row["candidate_b_name"] == "Amla"
    assert row["status"] == "pending"


def test_accept_deduplication_candidate_creates_relationship(client, pending_candidate, db):
    response = client.post(f"/v1/deduplication/candidates/{pending_candidate.id}/accept", json={"reviewed_by": "dr.sharma@example.test", "review_notes": "same plant"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["reviewed_by"] == "dr.sharma@example.test"

    rel = db.query(ConceptRelationship).filter_by(
        concept_id_a=pending_candidate.candidate_a, concept_id_b=pending_candidate.candidate_b, relationship_type="SYNONYM_OF",
    ).one_or_none()
    assert rel is not None


def test_reject_deduplication_candidate_creates_no_relationship(client, pending_candidate, db):
    response = client.post(f"/v1/deduplication/candidates/{pending_candidate.id}/reject", json={"reviewed_by": "dr.sharma@example.test"})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    rel = db.query(ConceptRelationship).filter_by(
        concept_id_a=pending_candidate.candidate_a, concept_id_b=pending_candidate.candidate_b, relationship_type="SYNONYM_OF",
    ).one_or_none()
    assert rel is None


def test_accept_unknown_candidate_returns_404(client):
    response = client.post("/v1/deduplication/candidates/999999999/accept", json={"reviewed_by": "someone"})
    assert response.status_code == 404


def test_accept_already_reviewed_candidate_returns_409(client, pending_candidate):
    first = client.post(f"/v1/deduplication/candidates/{pending_candidate.id}/accept", json={"reviewed_by": "someone"})
    assert first.status_code == 200
    second = client.post(f"/v1/deduplication/candidates/{pending_candidate.id}/reject", json={"reviewed_by": "someone else"})
    assert second.status_code == 409


def test_accept_with_blank_reviewed_by_returns_422(client, pending_candidate):
    response = client.post(f"/v1/deduplication/candidates/{pending_candidate.id}/accept", json={"reviewed_by": "   "})
    assert response.status_code == 422
