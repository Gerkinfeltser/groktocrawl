#!/usr/bin/env python3
"""Run the grounded answer & research evaluation harness (issue #570).

Deterministic, hermetic, Docker-free: routes the real answer/research pipeline
in-process against the search and LLM twins and grades citation grounding and
abstention. ``--record-baseline`` writes only to ``baselines/candidate/`` —
promoting to the pinned canonical baseline is a separate, separately authorized
source-control step after human review.

Usage examples:
    python3 scripts/run_answer_evals.py --selection narrow
    python3 scripts/run_answer_evals.py --selection broad --target answer --json
    python3 scripts/run_answer_evals.py --selection broad --dry-run
    python3 scripts/run_answer_evals.py --selection narrow --record-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from evals.answer_evals import harness, provenance
from evals.answer_evals.routing import SCRAPER_BASE_URL

DEFAULT_OUTPUT_DIR = Path("eval-out")


def _run_id() -> str:
    run = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{run}-{attempt}-{int(time.time())}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grounded answer & research evaluation harness (issue #570)."
    )
    parser.add_argument(
        "--selection",
        choices=["narrow", "broad"],
        default="broad",
        help="narrow runs the bounded pre-merge subset; broad runs the full suite.",
    )
    parser.add_argument(
        "--target",
        choices=["answer", "research"],
        default=None,
        help="Restrict to cases targeting the /v2/answer or research pipeline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the corpus (hashes, pins, negative ratio) without executing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full selection result as JSON on stdout.",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="Write the candidate baseline to baselines/candidate/ only (never canonical).",
    )
    parser.add_argument(
        "--scraper-url",
        default=SCRAPER_BASE_URL,
        help="Scraper endpoint for the in-process pipeline (Compose lane uses scraper-svc).",
    )
    parser.add_argument(
        "--http-smoke",
        metavar="BASE_URL",
        default=None,
        help="After the selection, run one HTTP /v2/answer smoke against BASE_URL.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for per-case artifacts and the provenance document.",
    )
    return parser


def _print_summary(result: dict) -> None:
    summary = result["summary"]
    print(f"selection={result['selection']} target={result.get('target') or 'all'}")
    print(
        f"cases: {summary['total']} total, {summary['passed']} passed, "
        f"{summary['failed']} failed"
    )
    neg = summary["negative_ratio"]
    print(
        f"negative/abstention: {neg['negative_or_abstention']}/{neg['total']} "
        f"({neg['ratio']:.1%})"
    )
    baseline = result["baseline"]
    print(
        f"baseline: {'MATCH' if baseline['match'] else 'MISMATCH'} "
        f"({baseline['baseline_selection']})"
    )
    if baseline["diff"]:
        for entry in baseline["diff"]:
            print(f"  diff: {entry}")
    if result.get("http_smoke"):
        smoke = result["http_smoke"]
        print(
            f"http smoke: {'OK' if smoke['smoke_ok'] else 'FAIL'} "
            f"(status={smoke['status']} citations={smoke['citation_count']})"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir = output_dir / args.selection
    run_id = _run_id()
    try:
        manifest, cases = harness.validate_corpus()
        harness.select_case_ids(args.selection, manifest, cases)
    except harness.CaseValidationError as exc:
        record = harness.validation_failure_record(exc, output_dir=output_dir)
        manifest = harness.load_manifest()
        prov = provenance.build_provenance(
            run_id=run_id,
            selection=args.selection,
            target=args.target,
            record_baseline=False,
            case_records=[record],
            commit_sha=provenance.get_commit_sha(),
            manifest=manifest,
        )
        prov_path = provenance.write_provenance(output_dir / "provenance.json", prov)
        print(f"validation failed for {record['case_id']}: {exc}")
        print(f"failure artifact: {record['artifact_path']}")
        print(f"provenance written to {prov_path}")
        return 1

    if args.dry_run:
        ratio = harness.negative_ratio_summary(cases)
        print(f"dry-run: selection={args.selection} target={args.target or 'all'}")
        print(
            f"dry-run: {len(cases)} cases, negative_or_abstention="
            f"{ratio['negative_or_abstention']} ({ratio['ratio']:.1%} >= "
            f"{(manifest.get('negative_ratio_rule') or {}).get('min_negative_or_abstention_fraction')})"
        )
        return 0

    result = asyncio.run(
        harness.run_selection(
            args.selection,
            target=args.target,
            scraper_url=args.scraper_url,
            output_dir=output_dir,
            run_id=run_id,
            manifest=manifest,
            cases=cases,
        )
    )

    prov = provenance.build_provenance(
        run_id=run_id,
        selection=args.selection,
        target=args.target,
        record_baseline=args.record_baseline,
        case_records=result["cases"],
        commit_sha=provenance.get_commit_sha(),
        manifest=manifest,
    )
    prov_path = provenance.write_provenance(output_dir / "provenance.json", prov)

    if args.record_baseline:
        candidate = harness.build_candidate_baseline(args.selection, result["cases"])
        candidate_dir = harness.CANDIDATE_DIR
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / f"{args.selection}.json"
        candidate_path.write_text(json.dumps(candidate, indent=2) + "\n")
        print(f"candidate baseline written to {candidate_path} (not canonical)")

    if args.http_smoke:
        smoke_path = output_dir / "http-smoke.json"
        smoke = asyncio.run(harness.http_smoke(args.http_smoke))
        smoke["artifact_path"] = str(smoke_path)
        smoke_path.write_text(json.dumps(smoke, indent=2, sort_keys=True) + "\n")
        result["http_smoke"] = smoke

    if args.json:
        payload = dict(result)
        payload["provenance_path"] = str(prov_path)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_summary(result)
        print(f"provenance written to {prov_path}")

    if not result["baseline"]["match"]:
        return 1
    if result.get("http_smoke") and not result["http_smoke"]["smoke_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
