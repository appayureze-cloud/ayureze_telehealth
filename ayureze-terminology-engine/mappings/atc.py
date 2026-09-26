"""ATC/DDD adapter — DELIBERATELY NEVER FUNCTIONAL as an automated lookup.

Verified verbatim from the WHO Collaborating Centre for Drug Statistics
Methodology's own disclaimer (https://atcddd.fhi.no/copyright_disclaimer/,
fetched live 2026-09-26): "Copying and distribution for commercial
purposes is not allowed. Changing or manipulating the material is not
allowed." No public REST API exists for programmatic ATC lookups — the
Centre only offers an interactive website search. Building an automated
scraper against that website would be exactly the kind of unauthorized
"copying...for commercial purposes" this disclaimer prohibits, not a gray
area — so this adapter always raises, and always will, until a real
written agreement with the WHO Collaborating Centre exists (see
docs/LICENSE_MATRIX.md's "atc" entry for what that would require).
"""

from __future__ import annotations

from .base import AdapterNotConfiguredError, BiomedicalAdapter, BiomedicalLookupResult


class AtcAdapter(BiomedicalAdapter):
    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        raise AdapterNotConfiguredError(
            "ATC/DDD has no automated lookup path in this codebase, by design: the WHO "
            "Collaborating Centre's own terms explicitly prohibit commercial copying/distribution "
            "and publish no public API — see docs/LICENSE_MATRIX.md's 'atc' entry. A real written "
            "agreement with the Centre (contact atcddd.fhi.no) would be required before this "
            "adapter could ever be implemented; look up terms manually at https://atcddd.fhi.no/ "
            "in the meantime."
        )
