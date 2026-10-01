"""TranslationRouter (build spec section 10): routes a (source_lang,
target_lang, text) request to the language registry's configured provider
for that pair, falling back once if the primary is unavailable, and
failing closed — never silently degrading to an unapproved model — if
neither the pair is certified nor the caller explicitly opted in.

Records model_id/model_version/source_lang/target_lang/route/latency/
success for observability; NEVER the transcript text itself (build spec:
"Do not log: raw medical transcript...").
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .language_registry import LanguageRegistry
from .model_lifecycle import ModelNotAvailableError
from .translation import TranslationProvider


class RoutingError(RuntimeError):
    """No certified/available route exists for this pair. Fail closed —
    callers must never catch this and substitute a plaintext pass-through
    or an unapproved model."""


@dataclass
class RouteRecord:
    provider_id: str
    model_version: str
    source_lang: str
    target_lang: str
    route: str  # "primary" | "fallback"
    latency_ms: float
    success: bool


def _is_available(provider: TranslationProvider) -> bool:
    """Legacy providers (existing NLLBTranslationProvider) have no
    health()/ModelLifecycle at all — treated as always-available once
    constructed, matching their pre-existing behavior. New
    ModelLifecycle-based providers report real load-state health."""
    health_fn = getattr(provider, "health", None)
    if health_fn is None:
        return True
    try:
        return health_fn().healthy
    except Exception:  # noqa: BLE001 - a broken health check means "not available"
        return False


def _metadata_version(provider: TranslationProvider) -> str:
    metadata_fn = getattr(provider, "metadata", None)
    if metadata_fn is None:
        return "unknown"
    try:
        return metadata_fn().version
    except Exception:  # noqa: BLE001
        return "unknown"


class TranslationRouter:
    def __init__(
        self,
        registry: LanguageRegistry,
        providers: dict[str, TranslationProvider],
        allow_uncertified: bool = False,
    ):
        self._registry = registry
        self._providers = providers
        self._allow_uncertified = allow_uncertified

    def route(self, source_lang: str, target_lang: str, text: str) -> tuple[str, RouteRecord]:
        cfg = self._registry.get(source_lang, target_lang)
        if cfg is None:
            raise RoutingError(f"no language registry entry for {source_lang}->{target_lang}")

        if not cfg.certification.is_certified and not self._allow_uncertified:
            raise RoutingError(
                f"{source_lang}->{target_lang} is not certified for production "
                f"(status={cfg.certification.status}) — failing closed rather than silently "
                "using an unapproved model"
            )

        chosen_id, route_kind = self._select_provider_id(cfg)
        provider = self._providers.get(chosen_id) if chosen_id else None
        if provider is None:
            raise RoutingError(
                f"no available translation provider for {source_lang}->{target_lang} "
                f"(tried primary={cfg.translation_primary!r}, fallback={cfg.translation_fallback!r})"
            )

        t0 = time.monotonic()
        result = provider.translate(text, source_lang, target_lang)
        return result, RouteRecord(
            provider_id=chosen_id,
            model_version=_metadata_version(provider),
            source_lang=source_lang,
            target_lang=target_lang,
            route=route_kind,
            latency_ms=(time.monotonic() - t0) * 1000,
            success=True,
        )

    def _select_provider_id(self, cfg) -> tuple[str | None, str]:
        primary = self._providers.get(cfg.translation_primary)
        if primary is not None and _is_available(primary):
            return cfg.translation_primary, "primary"

        if cfg.translation_fallback:
            fallback = self._providers.get(cfg.translation_fallback)
            if fallback is not None and _is_available(fallback):
                return cfg.translation_fallback, "fallback"

        return None, "none"


def load_if_needed(provider: TranslationProvider) -> bool:
    """Best-effort load() for a ModelLifecycle-based provider that hasn't
    been loaded yet. Returns True if the provider is ready to use
    afterward, False if it's genuinely unavailable (ModelNotAvailableError)
    — callers (e.g. the router's caller, before route()) use this to decide
    whether to even register a provider under a given id."""
    load_fn = getattr(provider, "load", None)
    if load_fn is None:
        return True
    try:
        load_fn()
        return True
    except ModelNotAvailableError:
        return False
