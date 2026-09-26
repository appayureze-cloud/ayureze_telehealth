"""LOINC adapter — via Regenstrief's FHIR terminology server
(https://fhir.loinc.org), which requires HTTP Basic Auth with a free
loinc.org account (verified 2026-09-26, see docs/LICENSE_MATRIX.md: the
click-through LOINC License must be accepted before pulling content, even
though it is free). Not configured in this environment — raises
AdapterNotConfiguredError rather than faking a response.
"""

from __future__ import annotations

import os

import httpx

from .base import AdapterNotConfiguredError, BiomedicalAdapter, BiomedicalLookupResult

_BASE_URL = "https://fhir.loinc.org"


class LoincAdapter(BiomedicalAdapter):
    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self._username = username or os.environ.get("TERMINOLOGY_LOINC_USERNAME")
        self._password = password or os.environ.get("TERMINOLOGY_LOINC_PASSWORD")

    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        if not self._username or not self._password:
            raise AdapterNotConfiguredError(
                "LOINC adapter requires TERMINOLOGY_LOINC_USERNAME/TERMINOLOGY_LOINC_PASSWORD "
                "(a free loinc.org account with the click-through license accepted) — not "
                "configured in this environment."
            )
        response = httpx.get(
            f"{_BASE_URL}/CodeSystem/$lookup",
            params={"system": "http://loinc.org", "code": term},
            auth=(self._username, self._password),
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        display = next((p["valueString"] for p in payload.get("parameter", []) if p.get("name") == "display"), term)
        return [BiomedicalLookupResult(code=term, display=display, source="LOINC", source_url=f"{_BASE_URL}/CodeSystem/$lookup?code={term}")]
