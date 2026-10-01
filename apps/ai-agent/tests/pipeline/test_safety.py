from app.pipeline import safety, terminology


def test_safe_when_numbers_preserved():
    source = "Take 2 tablets twice daily for 7 days."
    translated = "2 மாத்திரைகளை தினமும் இருமுறை 7 நாட்களுக்கு எடுத்துக் கொள்ளுங்கள்."
    result = safety.validate(source, translated, terminology.analyze(source))
    assert result.safe
    assert result.reasons == []
    assert result.source_numbers == ["2", "7"]


def test_unsafe_when_a_number_is_dropped():
    source = "Take 2 tablets twice daily for 7 days."
    translated = "2 மாத்திரைகளை தினமும் இருமுறை எடுத்துக் கொள்ளுங்கள்."  # "7 days" missing
    result = safety.validate(source, translated, terminology.analyze(source))
    assert not result.safe
    assert any("mismatch" in r or "missing" in r for r in result.reasons)


def test_unsafe_when_a_number_is_altered():
    source = "Take 2 tablets twice daily for 7 days."
    translated = "3 மாத்திரைகளை தினமும் இருமுறை 7 நாட்களுக்கு எடுத்துக் கொள்ளுங்கள்."  # 2 -> 3
    result = safety.validate(source, translated, terminology.analyze(source))
    assert not result.safe


def test_unsafe_when_translation_is_empty_but_source_is_not():
    result = safety.validate("Take your medicine.", "", terminology.analyze("Take your medicine."))
    assert not result.safe


def test_safe_for_plain_text_with_no_numbers():
    source = "How are you feeling today?"
    translated = "இன்று உங்களுக்கு எப்படி இருக்கிறது?"
    result = safety.validate(source, translated, terminology.analyze(source))
    assert result.safe
