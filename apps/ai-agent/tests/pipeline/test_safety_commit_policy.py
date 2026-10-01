from app.pipeline.safety_commit_policy import SafetyCommitPolicy, SafetyDecision


def test_bare_dosage_number_waits_for_more_context():
    """Build spec's own example: 'Take 5' must never reach TTS."""
    p = SafetyCommitPolicy()
    result = p.evaluate("Take 5", "5 எடு", source_lang="en", target_lang="ta")
    assert result.decision == SafetyDecision.WAIT_FOR_MORE_CONTEXT
    assert result.safety_check is None


def test_dangling_connective_waits_for_more_context():
    """Build spec's own example: 'Take 5 mg twice daily for' — a duration
    is clearly still coming."""
    p = SafetyCommitPolicy()
    result = p.evaluate("Take 5 mg twice daily for", "ignored", source_lang="en", target_lang="ta")
    assert result.decision == SafetyDecision.WAIT_FOR_MORE_CONTEXT


def test_complete_matching_instruction_is_safe_to_speak():
    """Build spec's own example: a complete, correctly-translated
    instruction runs the real safety validator and passes."""
    p = SafetyCommitPolicy()
    result = p.evaluate(
        "Take 5 mg twice daily for 7 days.",
        "தினமும் இருமுறை 7 நாட்களுக்கு 5 மி.கி எடுக்கவும்.",
        source_lang="en", target_lang="ta",
    )
    assert result.decision == SafetyDecision.SAFE_TO_SPEAK
    assert result.safety_check is not None
    assert result.safety_check.safe is True


def test_dosage_mutation_is_blocked_not_waited():
    """Build spec's own example: source said 5 mg, translation says 50 mg
    — this is complete and must be BLOCKED, not treated as incomplete."""
    p = SafetyCommitPolicy()
    result = p.evaluate(
        "Take 5 mg twice daily for 7 days.",
        "தினமும் இருமுறை 7 நாட்களுக்கு 50 மி.கி எடுக்கவும்.",
        source_lang="en", target_lang="ta",
    )
    assert result.decision == SafetyDecision.BLOCKED
    assert result.safety_check is not None
    assert result.safety_check.safe is False


def test_empty_text_waits():
    p = SafetyCommitPolicy()
    result = p.evaluate("", "", source_lang="en", target_lang="ta")
    assert result.decision == SafetyDecision.WAIT_FOR_MORE_CONTEXT


def test_non_english_source_skips_the_incompleteness_heuristic_but_still_validates():
    """The dangling-connective/bare-number heuristic is English-only
    (documented limitation) — a Tamil source phrase goes straight to the
    real safety validator rather than being guessed at."""
    p = SafetyCommitPolicy()
    result = p.evaluate("5", "5", source_lang="ta", target_lang="en")
    assert result.decision in (SafetyDecision.SAFE_TO_SPEAK, SafetyDecision.BLOCKED)
    assert result.safety_check is not None


def test_never_guesses_never_returns_safe_for_an_empty_translation_of_real_content():
    p = SafetyCommitPolicy()
    result = p.evaluate("Take 5 mg twice daily for 7 days.", "", source_lang="en", target_lang="ta")
    assert result.decision == SafetyDecision.BLOCKED
