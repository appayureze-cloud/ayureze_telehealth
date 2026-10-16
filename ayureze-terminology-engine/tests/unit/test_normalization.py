from normalization import normalize_name


def test_case_normalization():
    assert normalize_name("Guduchi") == normalize_name("guduchi") == normalize_name("GUDUCHI")


def test_whitespace_normalization():
    assert normalize_name("  Tulsi   leaf  ") == normalize_name("Tulsi leaf")


def test_punctuation_normalization():
    assert normalize_name("Kamadugha Rasa (with Mukta)") == normalize_name("Kamadugha Rasa with Mukta")


def test_curly_quotes_normalized_like_straight_quotes():
    assert normalize_name("Doctor’s herb") == normalize_name("Doctor's herb")


def test_never_mutates_original_semantics_devanagari_preserved():
    # Devanagari script must pass through unchanged (no case folding
    # applies to it, no transliteration is performed) — normalization
    # must never silently convert scripts.
    result = normalize_name("आमवात")
    assert "आमवात" in result or result == "आमवात"


def test_empty_and_whitespace_only_input():
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


def test_normalization_is_deterministic():
    value = "Some Compound-Name, With Punctuation!"
    assert normalize_name(value) == normalize_name(value)


def test_different_words_never_normalize_to_the_same_value():
    # Normalization must not accidentally imply semantic equivalence
    # (spec: "Normalization must never automatically imply semantic
    # equivalence") — verified from the other direction: two genuinely
    # different words don't collide.
    assert normalize_name("Tulsi") != normalize_name("Amla")
