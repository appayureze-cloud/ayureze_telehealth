#!/usr/bin/env python3
"""Real search latency benchmark against the actual ingested database
(spec section 24) — measures actual wall-clock time per query, p50/p95/p99,
never claims a number it didn't measure.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from terminology.search import search_terms  # noqa: E402

QUERIES = {
    "exact_preferred": ["Tulsi", "Ashwagandha", "Giloy", "Amla", "Shatavari", "Brahmi", "Triphala Churna", "Amavata", "Jwara", "Ama"],
    "exact_synonym": ["Guduchi", "Amrita", "Bhuteshta", "Surasa", "Kundalini"],
    "scientific_name": ["Ocimum sanctum", "Tinospora cordifolia", "Emblica officinalis", "Withania somnifera"],
    "prefix": ["Tul", "Ashwa", "Amav", "Bra", "Shat"],
    "fuzzy_misspelled": ["Tulsy", "Ashwagandhaa", "Giloi", "Amlaa", "Shatawari"],
    "no_match": ["zzznonexistent1", "qqqfaketermxyz", "notarealherb999"],
}


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * p
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def main() -> None:
    db = SessionLocal()
    all_latencies_ms: list[float] = []
    print(f"{'category':20s} {'n':>4s} {'min':>8s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s}  (all in ms)")
    try:
        for category, queries in QUERIES.items():
            latencies = []
            for q in queries:
                for _ in range(20):  # 20 reps per query to get a stable distribution
                    t0 = time.perf_counter()
                    search_terms(db, q, limit=10)
                    latencies.append((time.perf_counter() - t0) * 1000)
            all_latencies_ms.extend(latencies)
            p50, p95, p99 = percentile(latencies, 0.50), percentile(latencies, 0.95), percentile(latencies, 0.99)
            print(f"{category:20s} {len(latencies):4d} {min(latencies):8.2f} {p50:8.2f} {p95:8.2f} {p99:8.2f} {max(latencies):8.2f}")

        p50, p95, p99 = percentile(all_latencies_ms, 0.50), percentile(all_latencies_ms, 0.95), percentile(all_latencies_ms, 0.99)
        print(f"\n{'OVERALL':20s} {len(all_latencies_ms):4d} {min(all_latencies_ms):8.2f} {p50:8.2f} {p95:8.2f} {p99:8.2f} {max(all_latencies_ms):8.2f}")
        print(f"\np95 = {p95:.2f}ms — target is < 100ms — {'PASS' if p95 < 100 else 'FAIL'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
