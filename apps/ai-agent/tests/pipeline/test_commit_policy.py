from app.pipeline.commit_policy import CommitPolicy, CommitTrigger


def test_punctuation_triggers_immediate_commit():
    p = CommitPolicy()
    d1 = p.accept_stable_text("Take two tablets")
    assert d1.should_commit is False
    d2 = p.accept_stable_text("daily.")
    assert d2.should_commit is True
    assert d2.trigger == CommitTrigger.PUNCTUATION
    assert d2.text == "Take two tablets daily."


def test_five_word_by_word_updates_do_not_each_commit():
    """The build spec's explicit anti-example: 'I' / 'I have' / 'I have a'
    / 'I have a stomach' / 'I have a stomach pain' must not create five
    translation requests."""
    p = CommitPolicy(min_stable_revisions=10, max_buffer_ms=999_999)  # disable the other two triggers for this test
    commits = []
    for word in ["I", "have", "a", "stomach", "pain"]:
        d = p.accept_stable_text(word)
        if d.should_commit:
            commits.append(d.text)
    assert commits == []  # no punctuation, no stability run long enough, no timeout


def test_stable_token_sequence_trigger_fires_after_min_revisions():
    p = CommitPolicy(min_stable_revisions=2)
    d1 = p.accept_stable_text("Take two tablets")
    assert d1.should_commit is False
    d2 = p.accept_stable_text("twice daily")
    assert d2.should_commit is True
    assert d2.trigger == CommitTrigger.STABLE_TOKEN_SEQUENCE
    assert d2.text == "Take two tablets twice daily"


def test_phrase_boundary_comma_triggers_with_enough_words():
    p = CommitPolicy(min_stable_revisions=10)
    d = p.accept_stable_text("Take two tablets,")
    assert d.should_commit is True
    assert d.trigger == CommitTrigger.PHRASE_BOUNDARY


def test_phrase_boundary_does_not_fire_on_a_lone_early_comma():
    p = CommitPolicy(min_stable_revisions=10)
    d = p.accept_stable_text("Well,")
    assert d.should_commit is False  # only 1 word — below _MIN_WORDS_FOR_WEAK_TRIGGER


def test_max_duration_triggers_even_without_punctuation_or_stability():
    p = CommitPolicy(max_buffer_ms=100, min_stable_revisions=999)
    t0 = 1000.0
    d1 = p.accept_stable_text("um", now=t0)
    assert d1.should_commit is False
    d2 = p.accept_stable_text("well", now=t0 + 0.2)  # 200ms later, past the 100ms cap
    assert d2.should_commit is True
    assert d2.trigger == CommitTrigger.MAX_DURATION


def test_silence_triggers_commit_of_buffered_text():
    p = CommitPolicy()
    p.accept_stable_text("Take two tablets")
    d = p.notify_silence(600)  # above the 500ms default threshold
    assert d.should_commit is True
    assert d.trigger == CommitTrigger.SILENCE
    assert d.text == "Take two tablets"


def test_silence_below_threshold_does_not_commit():
    p = CommitPolicy()
    p.accept_stable_text("Take two tablets")
    d = p.notify_silence(100)
    assert d.should_commit is False


def test_silence_with_empty_buffer_does_not_commit():
    p = CommitPolicy()
    d = p.notify_silence(1000)
    assert d.should_commit is False


def test_end_of_utterance_always_flushes_remaining_buffer():
    p = CommitPolicy(min_stable_revisions=999, max_buffer_ms=999_999)
    p.accept_stable_text("Take two")
    d = p.notify_end_of_utterance()
    assert d.should_commit is True
    assert d.trigger == CommitTrigger.END_OF_UTTERANCE
    assert d.text == "Take two"


def test_end_of_utterance_with_nothing_buffered_is_a_no_op():
    p = CommitPolicy()
    d = p.notify_end_of_utterance()
    assert d.should_commit is False


def test_buffer_resets_after_a_commit():
    p = CommitPolicy()
    d1 = p.accept_stable_text("First sentence.")
    assert d1.should_commit is True
    assert d1.text == "First sentence."

    # A fresh phrase after a commit must never carry over the previous
    # sentence's text.
    d2 = p.accept_stable_text("Second")
    assert d2.should_commit is False
    d3 = p.accept_stable_text("sentence.")
    assert d3.should_commit is True
    assert d3.text == "Second sentence."
