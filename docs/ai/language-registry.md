# Language registry

`app/pipeline/language_registry.py`'s `LanguageRegistry` is the single
source of truth for which translation/TTS provider a `(source, target)`
language pair routes to, and whether that pair is production-ready.

## Schema

```python
LanguagePairConfig(
    source: str, target: str,
    translation_primary: str,       # a provider_id, resolved by TranslationRouter's provider map
    translation_fallback: str | None,
    tts_primary: str | None,
    tts_fallback: str | None,
    certification: Certification(
        status: str,                # "uncertified" | "testing" | "certified"
        medical_terms: bool, dosage: bool, negation: bool, latency: bool,
    ),
    license: LicenseStatus(verified: bool, notes: str),
)
```

`Certification.is_certified` requires `status == "certified"` AND all
four flags true. `LanguageRegistry.is_production_ready(source, target)`
additionally requires `license.verified` — certification and licensing are
independent gates, deliberately (see `docs/MODEL_LICENSE_MATRIX.md`'s
headline finding: a pair can be fully certified and still not
production-ready on licensing grounds alone).

## This build's default registry — real, evidenced state, not aspiration

| Pair | Translation / TTS primary | Certification | License verified | `is_production_ready()` | Why |
|---|---|---|---|---|---|
| en → ta | `madlad400-3b` / `qwen3-tts` | ⚠️ testing (0/4 flags) | ✅ **True** | ❌ **False** | **Switched this pass** from NLLB-200/MMS-TTS (CC-BY-NC-4.0) to MADLAD-400/Qwen3-TTS (Apache-2.0), no fallback to the old models. Licensing is resolved; certification was correctly RESET (not carried over) since the prior safety-corpus/live-integration/latency evidence was measured against NLLB/MMS-TTS's actual output, not MADLAD/Qwen3-TTS's. Also currently unavailable in this sandbox (no GPU) — see `docs/MODEL_LICENSE_MATRIX.md`. |
| ta → en | `madlad400-3b` / `qwen3-tts` | ⚠️ testing | ✅ True | ❌ False | Same as en → ta. |
| en → ml | `madlad400-3b` / `qwen3-tts` | ⚠️ testing (0/4 flags) | ✅ True | ❌ False | Same model switch as en → ta. Was already `testing` before the switch (safety validator's negation/terminology tables are English/Tamil-only — a separate, still-open blocker for this pair specifically). |
| de → en | `opus-mt-de-en` / — | ❌ uncertified | ✅ True | ❌ False | The build spec's own worked example of a "certified specialist" route (OPUS-MT). License verified for `opus-mt-de-en` specifically; certification blocked on regression testing against the safety corpus, not done this pass. |
| ja → en | `madlad400-3b` / — | ❌ uncertified | ✅ True | ❌ False | The build spec's own worked example of "no certified specialist → MADLAD-400." Routes DIRECTLY to `madlad400-3b` as primary (no fallback configured) — MADLAD-400 itself is not yet certified either. |

Every row above reflects real evidence (or its real absence) — none is
aspirational. Registering a new pair or promoting one to `certified` is a
`LanguageRegistry.register()` call once the real regression evidence
exists; the registry itself enforces nothing more or less than what's been
demonstrated. **No pair in this registry is currently `certified`** —
en↔ta held that status against NLLB-200/MMS-TTS specifically, and it was
correctly given up (not transferred) when those models were removed from
production routing — see `docs/MODEL_LICENSE_MATRIX.md`.

## Router fail-closed behavior

Both `TranslationRouter.route()` and `TTSRouter.route_for_language()`
raise (`RoutingError` / `TTSRoutingError`) rather than silently degrading
when:

- the pair has no registry entry at all,
- the pair is registered but not `is_certified` (unless a caller
  explicitly passes `allow_uncertified=True` — e.g. a controlled internal
  benchmark run, never production traffic),
- neither the primary nor fallback provider is available (unloaded,
  unhealthy, or `ModelNotAvailableError` at construction).

See `tests/pipeline/test_translation_router.py` and
`test_tts_router.py` for the real, passing tests of every one of these
fail-closed paths.
