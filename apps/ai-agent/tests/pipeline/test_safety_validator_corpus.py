"""Synthetic medical-safety test corpus for the deterministic safety
validator (app/pipeline/safety.py + terminology.py + negation.py). All
data here is synthetic (no real patient data), covering the exact
categories the safety-validator hardening pass requires: numeric/unit/
frequency/duration preservation, negation, medicine/Ayurveda terminology
preservation vs. substitution, safe reformatting (false-positive
avoidance), English<->Tamil in both directions, and structured adversarial
mutation testing.

Organized as one assertion helper (`assert_rejected`/`assert_passed`) so
each test case states its expected outcome explicitly, matching the "must
be REJECT" / "must be PASS" table in this task's spec.
"""

from __future__ import annotations

from app.pipeline import negation, safety, terminology


def _validate(source: str, translated: str, source_lang: str = "en", target_lang: str = "en"):
    term = terminology.analyze(source)
    return safety.validate(source, translated, term, source_lang=source_lang, target_lang=target_lang)


def assert_rejected(source: str, translated: str, source_lang: str = "en", target_lang: str = "en") -> None:
    result = _validate(source, translated, source_lang, target_lang)
    assert not result.safe, (
        f"expected REJECT but got PASS for {source!r} -> {translated!r} (reason_codes={result.reason_codes})"
    )
    assert result.status == "rejected"
    assert result.reason_codes, "a rejected result must always carry at least one reason code"


def assert_passed(source: str, translated: str, source_lang: str = "en", target_lang: str = "en") -> None:
    result = _validate(source, translated, source_lang, target_lang)
    assert result.safe, (
        f"expected PASS but got REJECT for {source!r} -> {translated!r} (reason_codes={result.reason_codes}, "
        f"reasons={result.reasons})"
    )
    assert result.status == "safe"
    assert result.reason_codes == []


# ============================= Step 2: Numbers =============================


class TestNumericPreservation:
    def test_pass_unchanged_dosage_number(self):
        assert_passed("Take 10 mg twice daily.", "Take 10 mg twice daily.")

    def test_reject_altered_dosage_number(self):
        assert_rejected("Take 10 mg twice daily.", "Take 100 mg twice daily.")

    def test_pass_unchanged_volume_number(self):
        assert_passed("Take 5 ml.", "Take 5 ml.")

    def test_reject_altered_volume_number(self):
        assert_rejected("Take 5 ml.", "Take 50 ml.")

    def test_pass_unchanged_duration_number(self):
        assert_passed("Take it for 7 days.", "Take it for 7 days.")

    def test_reject_altered_duration_number(self):
        assert_rejected("Take it for 7 days.", "Take it for 70 days.")

    def test_pass_decimal_normalization_trailing_zeros(self):
        # 5, 5.0, 5.00 represent the same quantity.
        assert_passed("Take 5.0 ml.", "Take 5.00 ml.")

    def test_reject_dropped_number(self):
        assert_rejected("Take 2 tablets twice daily for 7 days.", "Take 2 tablets twice daily.")

    def test_pass_simple_fraction(self):
        assert_passed("Take 1/2 tablet.", "Take 1/2 tablet.")

    def test_reject_altered_fraction(self):
        assert_rejected("Take 1/2 tablet.", "Take 1/4 tablet.")

    def test_pass_unicode_fraction_matches_equivalent_ascii_fraction(self):
        assert_passed("Take ½ tablet.", "Take 1/2 tablet.")

    def test_pass_percentage_unchanged(self):
        assert_passed("Apply a 1% cream.", "Apply a 1% cream.")

    def test_reject_percentage_altered(self):
        assert_rejected("Apply a 1% cream.", "Apply a 10% cream.")

    def test_pass_range_unchanged_reformatted(self):
        assert_passed("Take 5-10 mg.", "Take 5 to 10 mg.")

    def test_reject_range_bound_altered(self):
        assert_rejected("Take 5-10 mg.", "Take 5-100 mg.")


# ============================== Step 3: Units ==============================


class TestUnitPreservation:
    def test_reject_mg_to_ml(self):
        assert_rejected("Take 10 mg twice daily.", "Take 10 ml twice daily.")

    def test_reject_ml_to_mg(self):
        assert_rejected("Take 5 ml twice daily.", "Take 5 mg twice daily.")

    def test_pass_ml_case_variant(self):
        assert_passed("Take 5 ml.", "Take 5 mL.")

    def test_pass_spelled_out_unit_variant(self):
        assert_passed("Take 10 milligrams.", "Take 10 mg.")

    def test_pass_temperature_unchanged(self):
        assert_passed("Temperature is 37°C.", "Temperature is 37°C.")

    def test_reject_temperature_scale_swap_same_number(self):
        # 37°C vs 37°F is a real, dangerous unit change even though the
        # digits are identical — never treat C and F as equivalent.
        assert_rejected("Temperature is 37°C.", "Temperature is 37°F.")

    def test_reject_mcg_to_mg(self):
        assert_rejected("Take 500 mcg daily.", "Take 500 mg daily.")

    def test_pass_tablet_abbreviation_variant(self):
        assert_passed("Take 2 tablets.", "Take 2 tabs.")

    def test_reject_g_to_mg(self):
        assert_rejected("Take 1 g daily.", "Take 1 mg daily.")


# ============================ Step 4: Frequency =============================


class TestFrequencyPreservation:
    def test_pass_twice_daily_unchanged(self):
        assert_passed("Take 2 tablets twice daily for 7 days.", "Take 2 tablets twice daily for 7 days.")

    def test_reject_twice_to_once_daily(self):
        assert_rejected("Take twice daily.", "Take once daily.")

    def test_reject_once_to_thrice_daily(self):
        assert_rejected("Take once daily.", "Take thrice daily.")

    def test_reject_every_6_to_every_8_hours(self):
        assert_rejected("Take every 6 hours.", "Take every 8 hours.")

    def test_pass_frequency_reformatted_equivalent(self):
        assert_passed("Take twice a day.", "Take twice daily.")

    def test_pass_three_times_a_day_equals_thrice_daily(self):
        assert_passed("Take three times a day.", "Take thrice daily.")

    def test_reject_daily_count_dropped(self):
        assert_rejected("Take 2 tablets twice daily.", "Take 2 tablets daily.")


# ============================= Step 5: Duration =============================


class TestDurationPreservation:
    def test_pass_duration_unchanged(self):
        assert_passed("Take it for 7 days.", "Take it for 7 days.")

    def test_reject_days_to_weeks(self):
        assert_rejected("Take it for 7 days.", "Take it for 7 weeks.")

    def test_reject_weeks_to_months(self):
        assert_rejected("Take it for 2 weeks.", "Take it for 2 months.")

    def test_reject_duration_value_and_unit_both_altered(self):
        assert_rejected("Take it for 7 days.", "Take it for 2 weeks.")


# ============================= Step 6: Negation ==============================


class TestNegation:
    def test_reject_negation_dropped(self):
        assert_rejected("Do not take this medicine.", "Take this medicine.")

    def test_pass_negation_preserved(self):
        assert_passed("Do not take this medicine.", "Do not take this medicine.")

    def test_reject_negation_added(self):
        assert_rejected("Take this medicine.", "Do not take this medicine.")

    def test_reject_contraction_negation_dropped(self):
        assert_rejected("Don't take on an empty stomach.", "Take on an empty stomach.")

    def test_reject_avoid_dropped(self):
        assert_rejected("Avoid alcohol with this medicine.", "Alcohol is fine with this medicine.")

    def test_pass_unrelated_sentence_no_negation_either_side(self):
        assert_passed("How are you feeling today?", "How are you feeling today?")

    def test_negation_module_does_not_search_source_language_words_in_target_text(self):
        # A Tamil translation containing no negation marker of its own
        # must not be judged using the English word "not" — has_negation
        # is called with the TEXT's own language, never the other side's.
        assert negation.has_negation("இந்த மருந்தை எடுத்துக் கொள்ளுங்கள்.", "ta") is False
        assert negation.has_negation("இந்த மருந்தை எடுக்க வேண்டாம்.", "ta") is True

    def test_negation_unknown_language_returns_none_not_false(self):
        # Malayalam has no negation table — must report "unknown", never
        # silently resolve to "no negation present".
        assert negation.has_negation("ഇത് കഴിക്കரുத்.", "ml") is None

    def test_tamil_negative_imperative_suffix_recognized(self):
        # Regression for a real false-negative found by this pass's own
        # real-model (NLLB-200) end-to-end test: "Do not take this
        # medicine at bedtime." was translated using the negative-
        # imperative verb suffix "-ாதீர்கள்" ("எடுக்காதீர்கள்") rather than
        # a standalone negation word — a standard Tamil grammatical
        # negation form the marker list previously missed entirely.
        assert negation.has_negation("இந்த மருந்தை எடுக்காதீர்கள்.", "ta") is True

    def test_pass_tamil_negative_imperative_suffix_preserves_negation(self):
        assert_passed(
            "Do not take this medicine.",
            "இந்த மருந்தை எடுக்காதீர்கள்.",
            target_lang="ta",
        )


# ================= Steps 7-8: Medicine / Ayurveda terminology =================


class TestProtectedTerminology:
    def test_pass_medicine_name_preserved(self):
        assert_passed("Take Paracetamol for fever.", "Take Paracetamol for fever.")

    def test_reject_medicine_substituted_same_dosage(self):
        assert_rejected("Take 500 mg Paracetamol.", "Take 500 mg Ibuprofen.")

    def test_reject_ashwagandha_substituted(self):
        assert_rejected("Take Ashwagandha daily.", "Take an unrelated supplement daily.")

    def test_pass_ashwagandha_transliterated_to_tamil(self):
        assert_passed("Take Ashwagandha daily.", "தினமும் அஸ்வகந்தா சாப்பிடுங்கள்.", target_lang="ta")

    def test_reject_ashwagandha_semantically_substituted_in_tamil(self):
        # Correct transliteration replaced by a DIFFERENT drug's Tamil
        # name — semantic substitution, not transliteration.
        assert_rejected(
            "Take Ashwagandha daily.", "தினமும் பாராஸிட்டமால் சாப்பிடுங்கள்.", target_lang="ta"
        )

    def test_pass_all_representative_ayurveda_terms_transliterated(self):
        cases = [
            ("This balances your Dosha.", "இது உங்கள் தோஷத்தை சமன் செய்கிறது."),
            ("This balances your Vata.", "இது உங்கள் வாதத்தை சமன் செய்கிறது."),
            ("This balances your Pitta.", "இது உங்கள் பித்தத்தை சமன் செய்கிறது."),
            ("This balances your Kapha.", "இது உங்கள் கபத்தை சமன் செய்கிறது."),
            ("This improves your Agni.", "இது உங்கள் அக்னியை மேம்படுத்துகிறது."),
            ("This reduces Ama in the body.", "இது உடலில் ஆமத்தை குறைக்கிறது."),
            ("This matches your Prakriti.", "இது உங்கள் பிரகிருதிக்கு பொருந்துகிறது."),
            ("We recommend Panchakarma.", "நாங்கள் பஞ்சகர்மாவை பரிந்துரைக்கிறோம்."),
            ("This is a Rasayana treatment.", "இது ஒரு ரசாயன சிகிச்சை."),
        ]
        for source, translated in cases:
            assert_passed(source, translated, target_lang="ta")

    def test_reject_dosha_substituted_with_different_dosha(self):
        assert_rejected("This balances your Vata dosha.", "இது உங்கள் பித்த தோஷத்தை சமன் செய்கிறது.", target_lang="ta")

    def test_pass_anatomical_terms_preserved_tamil(self):
        assert_passed("This protects your kidney.", "இது உங்கள் சிறுநீரகத்தை பாதுகாக்கிறது.", target_lang="ta")
        assert_passed("This protects your liver.", "இது உங்கள் கல்லீரலை பாதுகாக்கிறது.", target_lang="ta")
        assert_passed("Monitor your blood pressure.", "உங்கள் இரத்த அழுத்தத்தை கண்காணிக்கவும்.", target_lang="ta")


# ===================== Step 13: Tamil-source test cases =====================


class TestTamilSourceBothDirections:
    """Tamil -> English direction — the reverse of the EN->TA cases above.
    Confirms detect_protected_terms/term_preserved work symmetrically."""

    def test_pass_tamil_dosage_to_english(self):
        assert_passed(
            "10 மி.கி தினமும் இருமுறை எடுத்துக் கொள்ளுங்கள்.",
            "Take 10 mg twice daily.",
            source_lang="ta", target_lang="en",
        )

    def test_reject_tamil_dosage_unit_changed_in_english(self):
        assert_rejected(
            "10 மி.கி தினமும் இருமுறை எடுத்துக் கொள்ளுங்கள்.",
            "Take 10 ml twice daily.",
            source_lang="ta", target_lang="en",
        )

    def test_pass_tamil_ashwagandha_to_english(self):
        assert_passed(
            "தினமும் அஸ்வகந்தா சாப்பிடுங்கள்.",
            "Take Ashwagandha daily.",
            source_lang="ta", target_lang="en",
        )

    def test_reject_tamil_negation_dropped_in_english(self):
        assert_rejected(
            "இந்த மருந்தை எடுக்க வேண்டாம்.",
            "Take this medicine.",
            source_lang="ta", target_lang="en",
        )

    def test_pass_tamil_negation_preserved_in_english(self):
        assert_passed(
            "இந்த மருந்தை எடுக்க வேண்டாம்.",
            "Do not take this medicine.",
            source_lang="ta", target_lang="en",
        )

    def test_reject_tamil_duration_unit_changed_in_english(self):
        assert_rejected(
            "7 நாட்களுர்க்கு எடுத்துக் கொள்ளுங்கள்.",
            "Take it for 7 weeks.",
            source_lang="ta", target_lang="en",
        )

    def test_pass_tamil_duration_unchanged_in_english(self):
        assert_passed(
            "7 நாட்களுர்க்கு எடுத்துக் கொள்ளுங்கள்.",
            "Take it for 7 days.",
            source_lang="ta", target_lang="en",
        )


# =================== Steps 14-15: Adversarial + false-positive ===================


class TestAdversarialMutations:
    """Every critical mutation of a valid medical sentence must be
    rejected — more valuable than happy-path tests alone, per this task's
    explicit instruction."""

    BASE_SOURCE = "Take 10 mg twice daily for 7 days. Do not take on an empty stomach."
    BASE_TRANSLATION = "Take 10 mg twice daily for 7 days. Do not take on an empty stomach."

    def test_baseline_unmutated_passes(self):
        assert_passed(self.BASE_SOURCE, self.BASE_TRANSLATION)

    def test_mutation_number_changed_is_rejected(self):
        assert_rejected(self.BASE_SOURCE, self.BASE_TRANSLATION.replace("10 mg", "100 mg"))

    def test_mutation_unit_changed_is_rejected(self):
        assert_rejected(self.BASE_SOURCE, self.BASE_TRANSLATION.replace("10 mg", "10 ml"))

    def test_mutation_frequency_changed_is_rejected(self):
        assert_rejected(self.BASE_SOURCE, self.BASE_TRANSLATION.replace("twice daily", "once daily"))

    def test_mutation_duration_changed_is_rejected(self):
        assert_rejected(self.BASE_SOURCE, self.BASE_TRANSLATION.replace("7 days", "7 weeks"))

    def test_mutation_negation_removed_is_rejected(self):
        assert_rejected(self.BASE_SOURCE, self.BASE_TRANSLATION.replace("Do not take", "Take"))

    def test_mutation_food_constraint_removed_is_rejected(self):
        assert_rejected(
            self.BASE_SOURCE, self.BASE_TRANSLATION.replace(" Do not take on an empty stomach.", "")
        )

    def test_mutation_medicine_substituted_is_rejected(self):
        assert_rejected("Take Metformin 500 mg daily.", "Take Insulin 500 mg daily.")


class TestFalsePositiveAvoidance:
    """The validator must not be so strict that ordinary, meaning-
    preserving translation/reformatting gets rejected — every case here
    represents a real, legitimate transformation NLLB or a human
    reviewer might produce."""

    def test_unit_case_and_spelling_variants_all_pass(self):
        assert_passed("Take 5 mL.", "Take 5 ml.")
        assert_passed("Take 10 milligrams.", "Take 10 mg.")
        assert_passed("Take 10 mg.", "Take 10 milligrams.")

    def test_frequency_phrasing_variants_all_pass(self):
        assert_passed("Take twice a day.", "Take twice daily.")
        assert_passed("Take once per day.", "Take once daily.")
        assert_passed("Take three times a day.", "Take thrice daily.")

    def test_decimal_formatting_variants_pass(self):
        assert_passed("Take 5.0 ml.", "Take 5 ml.")
        assert_passed("Take 5 ml.", "Take 5.00 ml.")

    def test_number_reordering_across_languages_passes(self):
        # Simulated reordering: the same two protected numbers, different
        # surface order — legitimate across languages with different
        # word order, must not be treated as a mismatch.
        assert_passed("Take 2 tablets for 7 days.", "For 7 days, take 2 tablets.")

    def test_plain_conversational_text_with_no_protected_entities_passes(self):
        assert_passed("How are you feeling today?", "இன்று உங்களுக்கு எப்படி இருக்கிறது?", target_lang="ta")
        assert_passed("Thank you, doctor.", "நன்றி, டாக்டர்.", target_lang="ta")

    def test_range_reformatting_passes(self):
        assert_passed("Take 5-10 mg.", "Take 5 to 10 mg.")


# ========================= Step 10: Fail-closed structure =========================


class TestFailClosedStructuredError:
    def test_rejected_result_produces_structured_error(self):
        result = _validate("Do not take this medicine.", "Take this medicine.")
        error = result.to_structured_error()
        assert error["status"] == "rejected"
        assert error["reason"] == "negation_mismatch"
        assert "negation_mismatch" in error["reason_codes"]

    def test_safe_result_status_is_safe(self):
        result = _validate("Take your medicine.", "Take your medicine.")
        assert result.status == "safe"

    def test_empty_translation_of_nonempty_source_is_rejected(self):
        assert_rejected("Take your medicine.", "")
