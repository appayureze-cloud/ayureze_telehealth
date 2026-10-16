"""RxNorm adapter — via NLM's public RxNorm REST API
(https://rxnav.nlm.nih.gov/REST/), which is genuinely open for interactive
lookups with NO API key/account required (verified 2026-09-26 — the
UMLS Metathesaurus License is only needed to bulk-download the full
RxNorm release files, a distinct thing from querying this public REST
API). This adapter performs a LIVE lookup only, every call — it never
caches or stores RxNorm content locally, so it needs no local license
gate of its own; the underlying content's license (free, UMLS-covered per
docs/LICENSE_MATRIX.md) applies to the WHOLE FILES a bulk download would
carry, most of which this adapter never touches.
"""

from __future__ import annotations

import httpx

from .base import BiomedicalAdapter, BiomedicalLookupResult

_BASE_URL = "https://rxnav.nlm.nih.gov/REST"


class RxNormAdapter(BiomedicalAdapter):
    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        response = httpx.get(f"{_BASE_URL}/drugs.json", params={"name": term}, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        results: list[BiomedicalLookupResult] = []
        for group in payload.get("drugGroup", {}).get("conceptGroup") or []:
            for concept in group.get("conceptProperties") or []:
                results.append(BiomedicalLookupResult(
                    code=concept["rxcui"], display=concept["name"], source="RxNorm",
                    source_url=f"https://rxnav.nlm.nih.gov/REST/rxcui/{concept['rxcui']}",
                ))
        return results
