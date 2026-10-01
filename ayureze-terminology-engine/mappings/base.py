"""Adapter architecture for biomedical terminologies (spec section 18):
each adapter calls out to an external, separately-licensed service for a
live lookup — none of them store, cache, or bulk-copy the underlying
terminology content into this codebase's own PostgreSQL database. This
mirrors the real-world "Medical Terminologies MCP" precedent (see
docs/LICENSE_MATRIX.md): MIT-licensed integration CODE is completely
separate from, and does not grant any rights to, the terminology CONTENT
it looks up.

Every adapter raises AdapterNotConfiguredError when it can't be used —
missing credentials, a policy-level disable (SNOMED CT), or a source that
has no live API at all (ATC) — never by silently returning empty/fake
results. Callers (mappings/router.py, once written) must treat this
exactly like ModelNotAvailableError elsewhere in the AyurEze ecosystem:
"this adapter is unavailable," never "fall back to guessing."
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class AdapterNotConfiguredError(RuntimeError):
    """Raised by lookup() when the adapter cannot be used in this
    environment — missing credentials, a licensing prerequisite not met,
    or (ATC) no live API existing at all. Never caught and papered over
    with fabricated data."""


@dataclass
class BiomedicalLookupResult:
    code: str
    display: str
    source: str
    source_url: str


class BiomedicalAdapter(ABC):
    @abstractmethod
    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        """Live lookup only — must raise AdapterNotConfiguredError instead
        of returning results if prerequisites (credentials, a licensed
        terminology server, etc.) aren't met."""
