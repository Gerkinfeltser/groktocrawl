#!/usr/bin/env python3
"""Deterministic old-vs-new comparison for ``hybrid_vector`` retrieval.

Simulates the pre-#532 sequential web-first merge against the #532 concurrent
blend in-process (stdlib-only, no Docker) so the comparison is runnable and
reproducible anywhere. It measures the four dimensions called out by the issue:

- **latency** — old sums the web + vector discovery delays; new takes the max
  (the two branches run concurrently).
- **source diversity** — how many Qdrant-only candidates survive into the final
  candidate set.
- **citation validity** — fraction of returned URLs that are well-formed
  ``http(s)`` URLs (a proxy for citable sources).
- **answer quality** — recall@k against a fixed "golden" relevant-URL set
  (a proxy; real answer quality needs an LLM-judge harness).

Usage::

    python scripts/benchmark_hybrid_retrieval.py --runs 5
    python scripts/benchmark_hybrid_retrieval.py --runs 5 --json

This is NOT a CI gate and NOT a live-stack benchmark. The delays and result
sets are deterministic fixtures, and the metrics are structural proxies, not
end-user quality measurements.
"""

from __future__ import annotations

import argparse
import json
import sys
from statistics import mean
from urllib.parse import urlparse

# ── Deterministic fixtures ───────────────────────────────────────
# web_urls and vector_urls intentionally overlap so both the dedup path and the
# vector-only path are exercised. ``golden_urls`` is the set a perfect ranking
# would surface first.
WEB_URLS = [f"https://web{i}.example/page" for i in range(6)]
VECTOR_URLS = [
    "https://web0.example/page",  # overlap
    "https://web1.example/page",  # overlap
    "https://vec0.example/page",  # vector-only
    "https://vec1.example/page",  # vector-only
]
GOLDEN_URLS = {"https://web0.example/page", "https://vec0.example/page"}

WEB_DELAY = 0.150  # seconds, simulated SlopSearX latency
VECTOR_DELAY = 0.080  # seconds, simulated Qdrant latency
LIMIT = 5


def _normalize(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return url
    display_host = f"[{host}]" if ":" in host else host
    port = parsed.port
    default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port is not None and not default:
        display_host = f"{display_host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    out = f"{scheme}://{display_host}{path}"
    if parsed.query:
        out += f"?{parsed.query}"
    return out


def _old_merge(web: list[str], vector: list[str], limit: int) -> list[str]:
    """Pre-#532 behaviour: web first, then vector, dedup by raw URL, truncate."""
    seen: set[str] = set()
    merged: list[str] = []
    for url in [*web, *vector]:
        if url not in seen:
            seen.add(url)
            merged.append(url)
    return merged[:limit]


def _new_merge(web: list[str], vector: list[str], limit: int) -> list[str]:
    """#532 behaviour: normalise, dedup, floor guarantee, round-robin interleave."""
    by_norm: dict[str, str] = {}
    web_order: list[str] = []
    vector_order: list[str] = []
    for url in web:
        norm = _normalize(url)
        if norm in by_norm:
            continue
        by_norm[norm] = url
        web_order.append(norm)
    for url in vector:
        norm = _normalize(url)
        if norm not in by_norm:
            by_norm[norm] = url
        vector_order.append(norm)

    floor_web = max(0, limit - len(vector_order))
    floor_vector = max(0, limit - len(web_order))

    result: list[str] = []
    seen: set[str] = set()

    def take(order: list[str], count: int) -> None:
        taken = 0
        for norm in order:
            if taken >= count or len(result) >= limit:
                return
            if norm in seen:
                continue
            result.append(by_norm[norm])
            seen.add(norm)
            taken += 1

    take(web_order, floor_web)
    take(vector_order, floor_vector)

    wi = vi = 0
    while len(result) < limit and (wi < len(web_order) or vi < len(vector_order)):
        while wi < len(web_order) and web_order[wi] in seen:
            wi += 1
        while vi < len(vector_order) and vector_order[vi] in seen:
            vi += 1
        advanced = False
        if wi < len(web_order):
            result.append(by_norm[web_order[wi]])
            seen.add(web_order[wi])
            wi += 1
            advanced = True
        if len(result) < limit and vi < len(vector_order):
            result.append(by_norm[vector_order[vi]])
            seen.add(vector_order[vi])
            vi += 1
            advanced = True
        if not advanced:
            break
    return result


def _metrics(urls: list[str]) -> dict:
    vector_only = [u for u in urls if "vec" in urlparse(u).hostname]
    valid = sum(1 for u in urls if urlparse(u).scheme in ("http", "https"))
    recall = len(set(urls) & GOLDEN_URLS) / len(GOLDEN_URLS)
    return {
        "vector_only_candidates": len(vector_only),
        "citation_validity": valid / len(urls) if urls else 0.0,
        "answer_quality_recall_at_k": recall,
    }


def run_once(run_index: int) -> dict:
    """Run one simulated comparison of the old and new strategies."""
    # Jitter the simulated delays so latency percentiles are meaningful.
    web_delay = WEB_DELAY + (run_index % 3) * 0.01
    vector_delay = VECTOR_DELAY + (run_index % 2) * 0.01

    old_latency = web_delay + vector_delay
    new_latency = max(web_delay, vector_delay)

    old_urls = _old_merge(WEB_URLS, VECTOR_URLS, LIMIT)
    new_urls = _new_merge(WEB_URLS, VECTOR_URLS, LIMIT)

    return {
        "run": run_index,
        "old": {
            "latency_s": round(old_latency, 4),
            "urls": old_urls,
            **_metrics(old_urls),
        },
        "new": {
            "latency_s": round(new_latency, 4),
            "urls": new_urls,
            **_metrics(new_urls),
        },
    }


def _summarize(runs: list[dict]) -> dict:
    def agg(key: str) -> dict:
        old_samples = [r["old"][key] for r in runs]
        new_samples = [r["new"][key] for r in runs]
        return {
            "old_mean": round(mean(old_samples), 4),
            "new_mean": round(mean(new_samples), 4),
        }

    return {
        "runs": len(runs),
        "latency_s": agg("latency_s"),
        "vector_only_candidates": agg("vector_only_candidates"),
        "citation_validity": agg("citation_validity"),
        "answer_quality_recall_at_k": agg("answer_quality_recall_at_k"),
        "caveat": (
            "Deterministic in-process simulation with structural proxies; "
            "no universal quality claim should be drawn from a single run. "
            "Real latency/diversity/citation/quality numbers require the live "
            "Docker stack and an LLM-judge harness (documented follow-up)."
        ),
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="runs per strategy")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the summary as JSON to stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.runs < 1:
        print("error: --runs must be >= 1", file=sys.stderr)
        return 2

    runs = [run_once(i) for i in range(args.runs)]
    summary = _summarize(runs)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print("old-vs-new hybrid_vector retrieval (simulated, stdlib-only)")
    print(f"runs={summary['runs']} limit={LIMIT}\n")
    header = f"{'metric':<28} {'old (mean)':>14} {'new (mean)':>14}"
    print(header)
    print("-" * len(header))
    for key, label in (
        ("latency_s", "latency (s)"),
        ("vector_only_candidates", "vector-only candidates"),
        ("citation_validity", "citation validity"),
        ("answer_quality_recall_at_k", "answer quality (recall@k)"),
    ):
        print(
            f"{label:<28} {summary[key]['old_mean']:>14.4f} "
            f"{summary[key]['new_mean']:>14.4f}"
        )
    print("\n" + summary["caveat"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
