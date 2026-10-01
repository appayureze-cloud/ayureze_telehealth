from app.pipeline.stability_filter import TranscriptStabilityFilter


def test_matches_build_spec_worked_example():
    f = TranscriptStabilityFilter()

    u1 = f.update("I have had")
    assert u1.newly_committed_text == ""  # nothing stable yet — no previous hypothesis to compare against

    u2 = f.update("I have had stomach")
    assert u2.newly_committed_text == "I have had"
    assert u2.stable_prefix == "I have had"
    assert u2.unstable_suffix == "stomach"

    u3 = f.update("I have had stomach pain")
    assert u3.newly_committed_text == "stomach"
    assert u3.stable_prefix == "I have had stomach"
    assert u3.unstable_suffix == "pain"


def test_never_sends_duplicate_text_downstream():
    f = TranscriptStabilityFilter()
    seen = []
    for hyp in ["I", "I have", "I have a", "I have a stomach", "I have a stomach pain"]:
        u = f.update(hyp)
        if u.newly_committed_text:
            seen.append(u.newly_committed_text)

    # concatenating everything ever emitted must reconstruct the final
    # stable prefix exactly once, with no repeats — the last word ("pain")
    # never stabilized since no update arrived after it.
    assert " ".join(seen) == "I have a stomach"


def test_revision_increments_when_earlier_word_changes():
    f = TranscriptStabilityFilter()
    f.update("I have had")
    u = f.update("I had had")  # ASR revises "have" -> "had": common prefix is just "I"
    assert u.revision_count == 1
    assert u.stable_prefix == "I"


def test_pure_extension_is_not_a_revision():
    f = TranscriptStabilityFilter()
    f.update("I have")
    u = f.update("I have had")
    assert u.revision_count == 0


def test_finalize_flushes_remaining_unstable_tail():
    f = TranscriptStabilityFilter()
    f.update("I have had stomach")
    f.update("I have had stomach pain")  # commits "stomach"; "pain" still unstable
    remaining = f.finalize("I have had stomach pain for three days")
    assert remaining == "pain for three days"


def test_reset_clears_state_between_utterances():
    f = TranscriptStabilityFilter()
    f.update("hello")
    f.update("hello world")
    f.reset()
    u = f.update("hello world")  # fresh utterance — no memory of the prior one
    assert u.newly_committed_text == ""


def test_empty_hypothesis_is_handled():
    f = TranscriptStabilityFilter()
    u = f.update("")
    assert u.newly_committed_text == ""
    assert u.stable_prefix == ""
