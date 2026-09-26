"""MeSH adapter — via NLM's public MeSH lookup API
(https://id.nlm.nih.gov/mesh/lookup/), genuinely free/no-key (verified
2026-09-26, see docs/LICENSE_MATRIX.md). Live lookup only, same pattern as
rxnorm.py — no local copy of MeSH content.
"""

from __future__ import annotations

import httpx

from .base import BiomedicalAdapter, BiomedicalLookupResult

_BASE_URL = "https://id.nlm.nih.gov/mesh/lookup/term"


class MeshAdapter(BiomedicalAdapter):
    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        response = httpx.get(_BASE_URL, params={"label": term, "match": "contains", "limit": 10}, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        return [
            BiomedicalLookupResult(code=item["resource"].rsplit("/", 1)[-1], display=item["label"], source="MeSH", source_url=item["resource"])
            for item in payload
        ]
