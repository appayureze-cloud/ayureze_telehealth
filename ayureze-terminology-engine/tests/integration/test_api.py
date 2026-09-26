"""Real HTTP requests against the FastAPI app (spec section 21: "API
responses"), backed by a real Postgres database via dependency override —
no mocking of the database layer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database import get_db
from models import Concept, ConceptName, ConceptRelationship, Source, SourceRecord


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
