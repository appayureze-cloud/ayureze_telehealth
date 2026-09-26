"""SNOMED CT adapter — DELIBERATELY DISABLED by default (spec section 18:
"SNOMED CT must remain disabled unless valid licensing and an appropriate
terminology server are configured").

Real licensing situation (verified 2026-09-26, see docs/LICENSE_MATRIX.md):
India, UK, Singapore, Malaysia, UAE, Saudi Arabia, and Qatar are all
confirmed current SNOMED International Member territories, so a FREE
Affiliate License is realistically obtainable — but only after formally
registering through a Member country's National Release Center and
signing the Affiliate License Agreement. This adapter does not, and must
not, assume that has happened.

This class never talks to SNOMED content directly — it calls out to an
externally-hosted, separately-licensed terminology server (e.g. a
self-hosted Snowstorm instance, the standard reference implementation)
that the OPERATOR is responsible for licensing and configuring. No
terminology server URL configured = always raises, by design, matching
this project's own "Medical Terminologies MCP" precedent research finding
(that project disables its SNOMED tools by default for the identical
reason).
"""

from __future__ import annotations

import os

import httpx

from .base import AdapterNotConfiguredError, BiomedicalAdapter, BiomedicalLookupResult


class SnomedAdapter(BiomedicalAdapter):
    def __init__(self, terminology_server_url: str | None = None) -> None:
        self._server_url = terminology_server_url or os.environ.get("TERMINOLOGY_SNOMED_SERVER_URL")

    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        if not self._server_url:
            raise AdapterNotConfiguredError(
                "SNOMED CT is disabled: no TERMINOLOGY_SNOMED_SERVER_URL configured. This is "
                "intentional, not a bug — see mappings/snomed.py's docstring and "
                "docs/LICENSE_MATRIX.md. Obtain a free SNOMED International Affiliate License via "
                "a Member country's National Release Center, stand up a licensed terminology server "
                "(e.g. Snowstorm), and set TERMINOLOGY_SNOMED_SERVER_URL before enabling this adapter."
            )
        response = httpx.get(f"{self._server_url}/browser/MAIN/concepts", params={"term": term}, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        return [
            BiomedicalLookupResult(code=item["conceptId"], display=item["fsn"]["term"], source="SNOMED CT", source_url=self._server_url)
            for item in payload.get("items", [])
        ]
