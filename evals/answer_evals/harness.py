"""Runner and validation for the grounded-answer eval harness (issue #570).

``run_case`` validates the case (content hash, fixture version pins, no-retry
rule), routes it through the real answer/research pipeline in-process, asserts
the fixture scenarios were actually used, applies the deterministic graders, and
emits a complete case result record (case id, expected constraints, observed
outcome, per-grader verdicts, artifact path). ``run_selection`` runs a bounded
selection (narrow for pre-merge, broad for nightly) and compares candidate
outcomes against the pinned baseline — never replacing it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from llm_svc.app import (
    FIXTURE_VERSION as LLM_FIXTURE_VERSION,
)
from llm_svc.app import (
    SCENARIOS as LLM_SCENARIOS,
)
from llm_svc.app import (
    SCHEMA_VERSION as LLM_SCHEMA_VERSION,
)
from slopsearx_fixture.app import (
    FIXTURE_VERSION as SEARCH_FIXTURE_VERSION,
)
from slopsearx_fixture.app import (
    SCENARIOS as SEARCH_SCENARIOS,
)
from slopsearx_fixture.app import (
    SCHEMA_VERSION as SEARCH_SCHEMA_VERSION,
)

from .grading import GRADER_VERSIONS, GRADERS, applicable_graders
from .routing import (
    FIXTURE_MODEL,
    LLM_BASE_URL,
    SCRAPER_BASE_URL,
    build_runtime,
    run_pipeline,
    scenario_usage,
    validate_endpoint_allowlist,
)

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
BASELINES_DIR = EVALS_DIR / "baselines"
CANDIDATE_DIR = BASELINES_DIR / "candidate"

DEFAULT_SELECTION_DEADLINE_SECONDS = 900


class CaseValidationError(ValueError):
    """Raised when a case file fails corpus-level validation."""

    def __init__(
        self,
        message: str,
        *,
        case_id: str = "__corpus__",
        case_path: str = "",
        expected: dict | None = None,
        observed: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.case_id = case_id
        self.case_path = case_path
        self.expected = expected or {"valid": True}
        self.observed = observed or {"validation_errors": [message]}


def canonical_case_hash(case: dict) -> str:
    """SHA-256 over the canonical JSON with ``content_hash`` omitted.

    Private harness-injected keys (e.g. ``_path``) are excluded so the stored
    ``content_hash`` remains stable regardless of how the corpus is loaded.
    """
    body = {
        key: value
        for key, value in case.items()
        if key != "content_hash" and not key.startswith("_")
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_hash(case: dict) -> str:
    """Stable canonical hash of the request + fixture pin dimensions."""
    body = {
        "target": case.get("target"),
        "query": case.get("query"),
        "num_sources": case.get("num_sources"),
        "retrieval_mode": case.get("retrieval_mode"),
        "citation_style": case.get("citation_style"),
        "search_fixture": case.get("search_fixture"),
        "llm_fixture": case.get("llm_fixture"),
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest() -> dict:
    return json.loads((EVALS_DIR / "manifest.json").read_text())


def load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text())
        case["_path"] = str(path.relative_to(EVALS_DIR))
        cases.append(case)
    return cases


def validate_case(case: dict, manifest: dict | None = None) -> list[str]:
    """Return a list of validation errors for *case* (empty when valid)."""
    manifest = manifest or load_manifest()
    errors: list[str] = []

    if not isinstance(case.get("id"), str) or not case["id"]:
        errors.append("case id must be a non-empty string")

    if case.get("content_hash") != canonical_case_hash(case):
        errors.append(
            f"content hash mismatch: expected {canonical_case_hash(case)}, "
            f"stored {case.get('content_hash')}"
        )
    if case.get("suite_version") != manifest.get("suite_version"):
        errors.append(
            f"suite_version mismatch: {case.get('suite_version')} != {manifest.get('suite_version')}"
        )
    if case.get("max_retries", 0) != 0:
        errors.append(f"max_retries must be 0, got {case.get('max_retries')}")
    if case.get("target") not in {"answer", "research"}:
        errors.append(f"unknown target {case.get('target')!r}")
    if case.get("kind") not in {"positive", "negative", "boundary"}:
        errors.append(f"unknown kind {case.get('kind')!r}")

    search = case.get("search_fixture") or {}
    if search.get("service") != "slopsearx-fixture":
        errors.append(f"unknown search fixture service {search.get('service')!r}")
    if search.get("scenario") not in SEARCH_SCENARIOS:
        errors.append(f"unknown search scenario {search.get('scenario')!r}")
    if search.get("scenario_version") != SEARCH_SCHEMA_VERSION:
        errors.append(
            f"search scenario_version mismatch: {search.get('scenario_version')}"
        )
    if search.get("fixture_version") != SEARCH_FIXTURE_VERSION:
        errors.append(
            f"search fixture_version mismatch: {search.get('fixture_version')}"
        )

    llm = case.get("llm_fixture") or {}
    if llm.get("service") != "llm-svc":
        errors.append(f"unknown llm fixture service {llm.get('service')!r}")
    if llm.get("scenario") not in LLM_SCENARIOS:
        errors.append(f"unknown llm scenario {llm.get('scenario')!r}")
    if llm.get("scenario_version") != LLM_SCHEMA_VERSION:
        errors.append(f"llm scenario_version mismatch: {llm.get('scenario_version')}")
    if llm.get("fixture_version") != LLM_FIXTURE_VERSION:
        errors.append(f"llm fixture_version mismatch: {llm.get('fixture_version')}")

    expected = case.get("expected") or {}
    if "protocol" not in expected:
        errors.append("expected.protocol missing")
    if expected.get("abstain_qualifier") not in (None, "insufficient", "contradictory"):
        errors.append(
            f"unknown abstain_qualifier {expected.get('abstain_qualifier')!r}"
        )

    return errors


def validate_corpus(cases: list[dict] | None = None) -> tuple[dict, list[dict]]:
    """Load and validate the corpus, enforcing the negative-case ratio."""
    manifest = load_manifest()
    cases = load_cases() if cases is None else cases
    for case in cases:
        errors = validate_case(case, manifest)
        if errors:
            raise CaseValidationError(
                f"case {case.get('id')} invalid: {'; '.join(errors)}",
                case_id=str(case.get("id") or "__unknown__"),
                case_path=str(case.get("_path") or ""),
                expected={"valid_case": True},
                observed={"validation_errors": errors},
            )
    if not cases:
        raise CaseValidationError("corpus is empty")
    ids = [str(case["id"]) for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise CaseValidationError(
            f"duplicate case ids: {duplicates}",
            expected={"unique_case_ids": True},
            observed={"duplicate_case_ids": duplicates},
        )
    min_ratio = float(
        (manifest.get("negative_ratio_rule") or {}).get(
            "min_negative_or_abstention_fraction", 0.20
        )
    )
    negative_or_abstention = [
        case
        for case in cases
        if case.get("kind") == "negative"
        or (case.get("expected") or {}).get("abstain_expected")
    ]
    ratio = len(negative_or_abstention) / len(cases)
    if ratio < min_ratio:
        raise CaseValidationError(
            f"negative/abstention ratio {ratio:.2%} below required {min_ratio:.2%} "
            f"({len(negative_or_abstention)}/{len(cases)})"
        )
    return manifest, cases


def select_case_ids(selection: str, manifest: dict, cases: list[dict]) -> list[str]:
    if selection == "narrow":
        ids = list(manifest.get("selections", {}).get("narrow", []))
    elif selection == "broad":
        ids = [case["id"] for case in cases]
    else:
        raise CaseValidationError(f"unknown selection {selection!r}")
    valid = {case["id"] for case in cases}
    missing = [case_id for case_id in ids if case_id not in valid]
    if missing:
        raise CaseValidationError(f"selection references unknown cases: {missing}")
    return ids


def negative_ratio_summary(cases: list[dict]) -> dict:
    negative = [c for c in cases if c.get("kind") == "negative"]
    abstain = [c for c in cases if (c.get("expected") or {}).get("abstain_expected")]
    union = {c["id"] for c in [*negative, *abstain]}
    return {
        "total": len(cases),
        "negative": len(negative),
        "abstain": len(abstain),
        "negative_or_abstention": len(union),
        "ratio": len(union) / len(cases) if cases else 0.0,
    }


async def _run_case_pipeline(
    case: dict, run_id: str, *, scraper_url: str
) -> tuple[dict, Any, dict]:
    runtime = build_runtime(case, run_id, scraper_url=scraper_url)
    observed = await asyncio.wait_for(
        run_pipeline(case, runtime),
        timeout=float(case.get("timeout_seconds") or 60),
    )
    usage = await scenario_usage(runtime)
    return observed, runtime, usage


async def run_case(
    case: dict,
    run_id: str,
    *,
    scraper_url: str = SCRAPER_BASE_URL,
    output_dir: Path | None = None,
    manifest: dict | None = None,
) -> dict:
    """Validate, route, grade, and record one eval case."""
    manifest = manifest or load_manifest()
    errors = validate_case(case, manifest)
    if errors:
        return validation_failure_record(
            CaseValidationError(
                f"case {case.get('id')} invalid: {'; '.join(errors)}",
                case_id=str(case.get("id") or "__unknown__"),
                case_path=str(case.get("_path") or ""),
                expected={"valid_case": True},
                observed={"validation_errors": errors},
            ),
            output_dir=output_dir,
        )

    started = time.monotonic()
    result: dict[str, Any] = {
        "case_id": case.get("id"),
        "case_path": case.get("_path", ""),
        "request_hash": request_hash(case),
        "expected": _expected_constraints(case),
        "outcome": "fail",
        "error": None,
        "timeout": False,
        "verdicts": [],
        "latency_ms": 0,
    }

    try:
        observed, _runtime, usage = await _run_case_pipeline(
            case, run_id, scraper_url=scraper_url
        )
    except TimeoutError:
        result["timeout"] = True
        result["error"] = f"case timed out after {case.get('timeout_seconds')}s"
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result["observed"] = {
            "protocol": {"status": None, "success": False},
            "answer": "",
            "sources": [],
            "citations": [],
            "error": result["error"],
        }
        result["fixture"] = _fixture_pins(case)
        return _finalize_result(result, output_dir=output_dir)
    except Exception as exc:
        result["error"] = f"transport failure: {type(exc).__name__}"
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result["observed"] = {
            "protocol": {"status": None, "success": False},
            "answer": "",
            "sources": [],
            "citations": [],
            "error": result["error"],
        }
        result["fixture"] = _fixture_pins(case)
        return _finalize_result(result, output_dir=output_dir)

    latency = int((time.monotonic() - started) * 1000)
    result["latency_ms"] = latency
    result["observed"] = observed
    result["fixture"] = _fixture_pins(case)
    result["scenario_use"] = usage

    scenario_ok = usage["search_observed_scenarios"] == [
        case["search_fixture"]["scenario"]
    ]
    llm_observed = usage["llm_observed_scenarios"]
    # The pipeline may legitimately short-circuit before synthesis (e.g. an
    # empty-search abstention never calls the LLM). When the LLM IS exercised,
    # every call must hit the case's scenario — a default-scenario leak fails.
    if llm_observed and llm_observed != [case["llm_fixture"]["scenario"]]:
        scenario_ok = False
    if not scenario_ok:
        result["error"] = (
            f"scenario-use assertion failed: search={usage['search_observed_scenarios']} "
            f"llm={llm_observed}"
        )

    verdicts = []
    for grader_id in applicable_graders(case):
        try:
            verdict = GRADERS[grader_id](observed, case)
        except Exception as exc:  # defensive: grader failures must preserve artifacts
            verdict = {
                "pass": False,
                "message": f"grader {grader_id} raised {type(exc).__name__}",
                "detail": {"error_type": type(exc).__name__},
            }
            result["error"] = f"grader failure: {grader_id} ({type(exc).__name__})"
        verdicts.append(
            {
                "grader": grader_id,
                "version": GRADER_VERSIONS[grader_id],
                **verdict,
            }
        )
    result["verdicts"] = verdicts
    result["graders"] = [
        {"id": grader_id, "version": GRADER_VERSIONS[grader_id]}
        for grader_id in applicable_graders(case)
    ]
    all_pass = all(v["pass"] for v in verdicts)
    result["outcome"] = "pass" if (all_pass and scenario_ok) else "fail"

    return _finalize_result(result, output_dir=output_dir)


def _expected_constraints(case: dict) -> dict:
    expected = case.get("expected") or {}
    return {
        "protocol": expected.get("protocol"),
        "required_claims": expected.get("required_claims", []),
        "prohibited_claims": expected.get("prohibited_claims", []),
        "allowable_source_urls": expected.get("allowable_source_urls", []),
        "citations": [
            {
                "claim_id": c.get("claim_id"),
                "citation_index": c.get("citation_index"),
                "source_url": c.get("source_url"),
            }
            for c in expected.get("citations", [])
        ],
        "abstain_expected": expected.get("abstain_expected", False),
        "abstain_qualifier": expected.get("abstain_qualifier"),
    }


def _fixture_pins(case: dict) -> dict:
    return {
        "search_fixture": case.get("search_fixture"),
        "llm_fixture": case.get("llm_fixture"),
        "model": FIXTURE_MODEL,
        "llm_base_url_host": _host_of(LLM_BASE_URL),
    }


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


def _finalize_result(result: dict, *, output_dir: Path | None) -> dict:
    artifact_path = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / f"{result['case_id']}.json"
        result["artifact_path"] = str(artifact_path)
        artifact_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    else:
        result["artifact_path"] = None
    return result


def validation_failure_record(
    error: CaseValidationError, *, output_dir: Path | None
) -> dict:
    """Create a complete, persisted record for corpus/case validation failure."""
    return _finalize_result(
        {
            "case_id": error.case_id,
            "case_path": error.case_path,
            "request_hash": None,
            "expected": error.expected,
            "observed": error.observed,
            "fixture": {},
            "outcome": "fail",
            "error": str(error),
            "timeout": False,
            "verdicts": [],
            "graders": [],
            "latency_ms": 0,
        },
        output_dir=output_dir,
    )


async def run_selection(
    selection: str,
    *,
    target: str | None = None,
    scraper_url: str = SCRAPER_BASE_URL,
    output_dir: Path | None = None,
    run_id: str | None = None,
    manifest: dict | None = None,
    cases: list[dict] | None = None,
) -> dict:
    """Run a selection and compare outcomes against the pinned baseline.

    Returns a selection result with per-case records, a summary, and the
    baseline comparison diff. Never writes or replaces the pinned baseline.
    """
    manifest = manifest or load_manifest()
    cases = load_cases() if cases is None else cases
    validate_corpus(cases)
    case_ids = select_case_ids(selection, manifest, cases)
    if target is not None:
        case_ids = [
            case_id
            for case_id in case_ids
            if next(c for c in cases if c["id"] == case_id)["target"] == target
        ]
    run_id = run_id or f"eval-{int(time.time())}"
    deadline = float(
        (manifest.get("case_rules") or {}).get(
            "overall_selection_deadline_seconds", DEFAULT_SELECTION_DEADLINE_SECONDS
        )
    )

    case_records: list[dict] = []
    started = time.monotonic()
    for case_id in case_ids:
        if time.monotonic() - started > deadline:
            case = next(c for c in cases if c["id"] == case_id)
            case_records.append(
                _finalize_result(
                    {
                        "case_id": case_id,
                        "case_path": case.get("_path", ""),
                        "request_hash": request_hash(case),
                        "expected": _expected_constraints(case),
                        "observed": {
                            "protocol": {"status": None, "success": False},
                            "error": "selection deadline exceeded",
                        },
                        "fixture": _fixture_pins(case),
                        "outcome": "fail",
                        "error": "selection deadline exceeded",
                        "verdicts": [],
                        "graders": [],
                        "latency_ms": 0,
                        "timeout": True,
                    },
                    output_dir=output_dir,
                )
            )
            continue
        case = next(c for c in cases if c["id"] == case_id)
        record = await run_case(
            case,
            run_id,
            scraper_url=scraper_url,
            output_dir=output_dir,
            manifest=manifest,
        )
        case_records.append(record)

    passed = sum(1 for r in case_records if r["outcome"] == "pass")
    failed = len(case_records) - passed
    baseline = load_baseline(selection)
    if baseline.get("suite_version") != manifest.get("suite_version"):
        comparison = {
            "match": False,
            "diff": [
                {
                    "case_id": "__baseline__",
                    "reason": "suite version mismatch",
                    "expected": manifest.get("suite_version"),
                    "observed": baseline.get("suite_version"),
                }
            ],
        }
    else:
        comparison = compare_to_baseline(case_records, baseline)
    baseline_artifact_path = None
    if comparison["diff"] and output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        baseline_artifact = output_dir / "baseline-mismatch.json"
        payload = {
            "case_id": "__baseline__",
            "expected_constraint": {
                "selection": selection,
                "suite_version": baseline.get("suite_version"),
            },
            "observed_outcome": {"diff": comparison["diff"]},
            "artifact_path": str(baseline_artifact),
        }
        baseline_artifact.write_text(json.dumps(payload, indent=2, sort_keys=True))
        baseline_artifact_path = str(baseline_artifact)

    return {
        "suite_version": manifest["suite_version"],
        "selection": selection,
        "target": target,
        "run_id": run_id,
        "summary": {
            "total": len(case_records),
            "passed": passed,
            "failed": failed,
            "negative_ratio": negative_ratio_summary(cases),
        },
        "cases": case_records,
        "baseline": {
            "baseline_selection": baseline.get("selection"),
            "baseline_suite_version": baseline.get("suite_version"),
            "match": comparison["match"],
            "diff": comparison["diff"],
            "artifact_path": baseline_artifact_path,
        },
    }


def load_baseline(selection: str) -> dict:
    path = BASELINES_DIR / f"{selection}.json"
    if not path.exists():
        return {"selection": selection, "suite_version": None, "cases": []}
    return json.loads(path.read_text())


def compare_to_baseline(case_records: list[dict], baseline: dict) -> dict:
    """Compare candidate outcomes to the pinned baseline, excluding volatiles."""
    baseline_cases = {entry["case_id"]: entry for entry in baseline.get("cases", [])}
    diff: list[dict] = []
    for record in case_records:
        entry = baseline_cases.get(record["case_id"])
        if entry is None:
            diff.append(
                {"case_id": record["case_id"], "reason": "missing from baseline"}
            )
            continue
        if entry.get("outcome") != record["outcome"]:
            diff.append(
                {
                    "case_id": record["case_id"],
                    "reason": "outcome mismatch",
                    "expected": entry.get("outcome"),
                    "observed": record["outcome"],
                }
            )
            continue
        expected_graders = entry.get("graders") or {}
        observed_verdicts = {
            v["grader"]: bool(v["pass"]) for v in record.get("verdicts", [])
        }
        for grader_id, expected_pass in expected_graders.items():
            if observed_verdicts.get(grader_id) != expected_pass:
                diff.append(
                    {
                        "case_id": record["case_id"],
                        "reason": "grader verdict mismatch",
                        "grader": grader_id,
                        "expected": expected_pass,
                        "observed": observed_verdicts.get(grader_id),
                    }
                )
    return {"match": not diff, "diff": diff}


def build_candidate_baseline(selection: str, case_records: list[dict]) -> dict:
    """Assemble a candidate baseline (written only to ``baselines/candidate/``)."""
    entries = []
    for record in case_records:
        entries.append(
            {
                "case_id": record["case_id"],
                "outcome": record["outcome"],
                "graders": {
                    v["grader"]: bool(v["pass"]) for v in record.get("verdicts", [])
                },
            }
        )
    return {
        "suite_version": load_manifest()["suite_version"],
        "selection": selection,
        "recorded_at": datetime.now(UTC).isoformat(),
        "cases": entries,
    }


async def http_smoke(
    base_url: str,
    *,
    query: str = "What does the Fixture Site charge for the Pro plan?",
    timeout: float = 120.0,
) -> dict:
    """A bounded HTTP ``/v2/answer`` smoke against the real fixture stack.

    Runs one default-scenario grounding case over the real route in the Compose
    lane. The endpoint host must be on the eval allowlist (no live egress).
    """
    validate_endpoint_allowlist([base_url])
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/v2/answer",
            json={
                "query": query,
                "num_sources": 3,
                "stream": False,
            },
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        ok = (
            response.status_code == 200
            and payload.get("success") is True
            and bool(payload.get("answer"))
            and isinstance(payload.get("citations"), list)
        )
        return {
            "status": response.status_code,
            "success": payload.get("success"),
            "answer_present": bool(payload.get("answer")),
            "citation_count": len(payload.get("citations") or []),
            "smoke_ok": ok,
            "detail": {
                "host": _host_of(base_url),
                "error": payload.get("error"),
            },
        }
