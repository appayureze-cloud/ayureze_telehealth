"""TTSRouter (build spec section 3): routes a target language to the
language registry's configured TTS provider, falling back once, and
FAILING CLOSED — never generating speech with an unapproved/uncertified
model (build spec: "Do not generate fallback speech using an uncertified
model.").
"""

from __future__ import annotations

from dataclasses import dataclass

from .language_registry import LanguageRegistry
from .tts import StreamingTTSProvider


class TTSRoutingError(RuntimeError):
    """No certified/available TTS route exists. Fail closed — callers
    must never substitute an unapproved model or silently skip audio
    generation without surfacing this."""


@dataclass
class TTSRouteRecord:
    provider_id: str
    model_version: str
    lang: str
    route: str  # "primary" | "fallback"


def _is_available(provider: StreamingTTSProvider) -> bool:
    try:
        return provider.health().healthy
    except Exception:  # noqa: BLE001
        return False


def _metadata_version(provider: StreamingTTSProvider) -> str:
    try:
        return provider.metadata().version
    except Exception:  # noqa: BLE001
        return "unknown"


class TTSRouter:
    def __init__(
        self,
        registry: LanguageRegistry,
        providers: dict[str, StreamingTTSProvider],
        source_target_lookup: dict[str, tuple[str, str]] | None = None,
        allow_uncertified: bool = False,
    ):
        """`source_target_lookup` maps a bare target language code (e.g.
        "ta") to the (source, target) pair the language registry indexes
        by, since the registry is keyed by full pairs but a TTS decision
        is naturally keyed by output language alone. Defaults to treating
        the target language as if paired from English, matching this
        build's current en-> everything routing (streaming.py's
        target_language_for)."""
        self._registry = registry
        self._providers = providers
        self._source_target_lookup = source_target_lookup or {}
        self._allow_uncertified = allow_uncertified

    def route_for_language(self, target_lang: str, source_lang: str = "en") -> tuple[StreamingTTSProvider, TTSRouteRecord]:
        source, target = self._source_target_lookup.get(target_lang, (source_lang, target_lang))
        cfg = self._registry.get(source, target)
        if cfg is None:
            raise TTSRoutingError(f"no language registry entry for {source}->{target}")

        if not cfg.certification.is_certified and not self._allow_uncertified:
            raise TTSRoutingError(
                f"{source}->{target} is not certified for production (status={cfg.certification.status}) "
                "— failing closed rather than generating speech with an unapproved model"
            )

        if cfg.tts_primary:
            primary = self._providers.get(cfg.tts_primary)
            if primary is not None and _is_available(primary):
                return primary, TTSRouteRecord(
                    provider_id=cfg.tts_primary, model_version=_metadata_version(primary), lang=target, route="primary",
                )

        if cfg.tts_fallback:
            fallback = self._providers.get(cfg.tts_fallback)
            if fallback is not None and _is_available(fallback):
                return fallback, TTSRouteRecord(
                    provider_id=cfg.tts_fallback, model_version=_metadata_version(fallback), lang=target, route="fallback",
                )

        raise TTSRoutingError(
            f"no available TTS provider for {source}->{target} "
            f"(tried primary={cfg.tts_primary!r}, fallback={cfg.tts_fallback!r})"
        )
