from app.pipeline import terminology


def test_extracts_dosage_frequency_duration():
    text = "Take 2 tablets twice daily for 7 days."
    analysis = terminology.analyze(text)
    kinds = {s.kind for s in analysis.protected_spans}
    assert "dosage" in kinds
    assert "frequency" in kinds
    assert "duration" in kinds

    numbers = terminology.extract_numbers(text)
    assert numbers == ["2", "7"]


def test_extracts_glossary_terms():
    text = "I recommend Ashwagandha and monitoring your blood pressure."
    analysis = terminology.analyze(text)
    terms = {s.text for s in analysis.protected_spans if s.kind == "term"}
    assert "ashwagandha" in terms
    assert "blood pressure" in terms


def test_bare_numbers_not_double_counted_with_dosage():
    text = "Take 500 mg twice daily."
    analysis = terminology.analyze(text)
    number_spans = [s for s in analysis.protected_spans if s.kind == "number"]
    dosage_spans = [s for s in analysis.protected_spans if s.kind == "dosage"]
    assert len(dosage_spans) == 1
    # 500 is already covered by the dosage span; must not also appear as a
    # standalone "number" span.
    assert not any("500" in s.text for s in number_spans)


def test_no_spans_for_plain_text():
    analysis = terminology.analyze("How are you feeling today?")
    assert analysis.protected_spans == []
