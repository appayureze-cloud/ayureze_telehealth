from services.concept_id import next_concept_id, peek_next_value


def test_concept_ids_are_sequential_and_zero_padded(db):
    first = next_concept_id(db, "TEST-PREFIX")
    second = next_concept_id(db, "TEST-PREFIX")
    assert first == "TEST-PREFIX-000001"
    assert second == "TEST-PREFIX-000002"


def test_concept_ids_never_reuse_source_ids():
    # A concept_id is always minted fresh, never derived from a source's
    # own identifier (spec section 8) — this is enforced by next_concept_id's
    # own signature (it takes only a prefix, never a source value).
    import inspect

    sig = inspect.signature(next_concept_id)
    assert "source_record_id" not in sig.parameters
    assert "source_id" not in sig.parameters


def test_different_prefixes_have_independent_counters(db):
    a1 = next_concept_id(db, "TEST-A")
    b1 = next_concept_id(db, "TEST-B")
    a2 = next_concept_id(db, "TEST-A")
    assert a1 == "TEST-A-000001"
    assert b1 == "TEST-B-000001"
    assert a2 == "TEST-A-000002"


def test_peek_next_value_does_not_consume(db):
    next_concept_id(db, "TEST-PEEK")
    before = peek_next_value(db, "TEST-PEEK")
    after = peek_next_value(db, "TEST-PEEK")
    assert before == after
