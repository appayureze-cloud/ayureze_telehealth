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

| Pair | Translation primary / fallback | TTS primary / fallback | Certification | License verified | `is_production_ready()` | Why |
|---|---|---|---|---|---|---|
| en → ta | `opus-mt-en-ta` / `madlad400-3b` | `None` / `qwen3-tts` | ⚠️ testing (0/4 flags) | ✅ **True** | ❌ **False** | Switched from NLLB-200/MMS-TTS (CC-BY-NC-4.0) to a CPU-feasible commercial primary (OPUS-MT) with the GPU-only commercial option (MADLAD-400/Qwen3-TTS) kept as fallback — both selectable via `app/config.py`, neither removed from the codebase. Licensing is resolved; certification was correctly RESET (not carried over) since the prior safety-corpus/live-integration/latency evidence was measured against NLLB's actual output, not OPUS-MT's. |
| ta → en | `opus-mt-ta-en` / `madlad400-3b` | `None` / `qwen3-tts` | ⚠️ testing | ✅ True | ❌ False | Same as en → ta. |
| en → ml | `opus-mt-en-ml` / `madlad400-3b` | `None` / `qwen3-tts` | ⚠️ testing (0/4 flags) | ✅ True | ❌ False | Same routing as en → ta (same `opus-mt-en-dra` checkpoint, different target tag). Was already `testing` before any model switch (safety validator's negation/terminology tables are English/Tamil-only — a separate, still-open blocker for this pair specifically). |
| de → en | `opus-mt-de-en` / `madlad400-3b` | `None` / — | ❌ uncertified | ✅ True | ❌ False | The build spec's own worked example of a "certified specialist" route. License verified for `opus-mt-de-en` specifically; certification blocked on regression testing against the safety corpus, not done this pass. |
| ja → en | `madlad400-3b` / — | `None` / — | ❌ uncertified | ✅ True | ❌ False | The build spec's own worked example of "no certified specialist → MADLAD-400." Routes DIRECTLY to `madlad400-3b` as primary (no fallback configured) — MADLAD-400 itself is not yet certified either. |

Every row above reflects real evidence (or its real absence) — none is
aspirational. Registering a new pair or promoting one to `certified` is a
`LanguageRegistry.register()` call once the real regression evidence
exists; the registry itself enforces nothing more or less than what's been
demonstrated. **No pair in this registry is currently `certified`** —
en↔ta held that status against NLLB-200/MMS-TTS specifically, and it was
correctly given up (not transferred) when those models stopped being the
default production route — see `docs/MODEL_LICENSE_MATRIX.md`.

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
