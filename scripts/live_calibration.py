#!/usr/bin/env python3
"""Run bounded, read-only provider calibration against source-owned twins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_CALLS = 6
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 0
MAX_TOKENS = 128
MAX_TOTAL_TOKENS = 512
COST_CEILING_USD = 1.0
RESULTS = frozenset({"match", "provider_drift"})
FAILURE_SOURCES = frozenset(
    {"authentication", "quota", "twin", "infrastructure", "harness"}
)
RequestFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, Any]]


def corpus_digest(corpus: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in paths:
        if path.is_file():
            digest.update(str(path.relative_to(root.parent)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def shape_fingerprint(value: Any) -> str:
    """Fingerprint recursive JSON types and object keys, never response values."""
    if isinstance(value, dict):
        children = ",".join(
            f"{key}:{shape_fingerprint(value[key])}" for key in sorted(value)
        )
        return "{" + children + "}"
    if isinstance(value, list):
        return "[" + ",".join(sorted({shape_fingerprint(item) for item in value})) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def schema_fingerprint(value: Any) -> str:
    return hashlib.sha256(shape_fingerprint(value).encode()).hexdigest()


def normalize_search_response(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("search response is not an object")
    web = body.get("web")
    container: dict[str, Any] = web if isinstance(web, dict) else body
    results = container.get("results")
    if not isinstance(results, list):
        raise ValueError("search results are not a list")
    normalized = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("search result is not an object")
        description = result.get("description", result.get("content"))
        if not isinstance(result.get("url"), str) or not isinstance(
            result.get("title"), str
        ):
            raise ValueError("search result identity is invalid")
        if description is not None and not isinstance(description, str):
            raise ValueError("search result description is invalid")
        normalized.append(
            {"url": result["url"], "title": result["title"], "description": description}
        )
    return {"result_count": len(normalized), "results": normalized}


def normalize_llm_response(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
        raise ValueError("llm response contract is invalid")
    choices = []
    for choice in body["choices"]:
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("llm choice contract is invalid")
        content = choice["message"].get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("llm content contract is invalid")
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise ValueError("llm finish reason contract is invalid")
        choices.append(
            {
                "message": {"content": content},
                "finish_reason": finish_reason,
            }
        )
    model = body.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("llm model contract is invalid")
    return {"model": model, "choices": choices}


def latency_band(seconds: float) -> str:
    if seconds < 1:
        return "fast"
    if seconds < 5:
        return "normal"
    return "slow"


def classify_failure(status: int | None, *, twin: bool = False) -> str:
    if twin:
        return "twin"
    if status in {401, 403}:
        return "authentication"
    if status in {402, 409, 429}:
        return "quota"
    if status is None or (500 <= status < 600):
        return "infrastructure"
    return "harness"


def classify_observation(
    provider_status: int | None,
    twin_status: int | None,
    provider_shape: str | None = None,
    twin_shape: str | None = None,
    *,
    harness_error: bool = False,
) -> str:
    if harness_error:
        return "harness"
    if provider_status is None:
        return "infrastructure"
    if provider_status in {401, 403}:
        return "authentication"
    if provider_status in {402, 409, 429}:
        return "quota"
    if provider_status >= 500:
        return "infrastructure"
    if provider_status >= 400:
        return "harness"
    if twin_status is None or twin_status >= 400:
        return "twin"
    if provider_status != twin_status or provider_shape != twin_shape:
        return "provider_drift"
    return "match"


def _request(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = response.read().decode(errors="replace")
        return response.status, json.loads(body)


def _validate_corpus(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise ValueError("corpus must contain a string id")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) * 2 > MAX_CALLS:
        raise ValueError("corpus must contain 1-3 cases")
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "kind", "input"}:
            raise ValueError("each case must contain only id, kind, and input")
        if not isinstance(case["id"], str) or not isinstance(case["kind"], str):
            raise ValueError("case id and kind must be strings")
        if (
            case["kind"] not in {"search", "llm"}
            or not isinstance(case["input"], str)
            or not case["input"]
        ):
            raise ValueError("case kind/input is invalid")
    llm_calls = sum(1 for case in cases if case["kind"] == "llm") * 2
    if llm_calls * MAX_TOKENS > MAX_TOTAL_TOKENS:
        raise ValueError("calibration corpus exceeds total token bound")
    return raw["id"], cases


def _config() -> dict[str, Any]:
    values: dict[str, Any] = {
        "brave_key": os.getenv("BRAVE_API_KEY"),
        "llm_key": os.getenv("LLM_API_KEY"),
        "llm_base": os.getenv("LLM_BASE_URL"),
        "llm_model": os.getenv("LLM_MODEL"),
        "brave_cost": os.getenv("BRAVE_COST_PER_CALL_USD"),
        "llm_cost": os.getenv("LLM_COST_PER_1K_TOKENS_USD"),
        "provider_search": os.getenv("CALIBRATION_PROVIDER_SEARCH_URL"),
        "twin_search": os.getenv("CALIBRATION_TWIN_SEARCH_URL"),
        "provider_llm": os.getenv("CALIBRATION_PROVIDER_URL"),
        "twin_llm": os.getenv("CALIBRATION_TWIN_LLM_URL"),
    }
    required = [key for key, value in values.items() if not value]
    if required:
        raise ValueError("missing calibration configuration: " + ",".join(required))
    try:
        values["brave_cost"] = float(values["brave_cost"])
        values["llm_cost"] = float(values["llm_cost"])
    except (TypeError, ValueError) as exc:
        raise ValueError("cost variables must be numeric") from exc
    if values["brave_cost"] < 0 or values["llm_cost"] < 0:
        raise ValueError("cost variables must be non-negative")
    for key in (
        "llm_base",
        "provider_search",
        "twin_search",
        "provider_llm",
        "twin_llm",
    ):
        if not urllib.parse.urlparse(values[key]).scheme:
            raise ValueError(f"{key} must be an absolute URL")
    provider_llm = values["provider_llm"].rstrip("/")
    if not provider_llm.endswith("/chat/completions"):
        provider_llm += "/chat/completions"
    values["provider_llm"] = provider_llm
    return values


def _write_artifact(output: Path, artifact: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "calibration.json").write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )


def run(
    output: Path,
    corpus_path: Path,
    *,
    provider_url: str | None = None,
    twin_url: str | None = None,
    request_fn: RequestFn | None = None,
) -> int:
    started = datetime.now(UTC).isoformat()
    output.mkdir(parents=True, exist_ok=True)
    before = {
        str(path): _tree_digest(Path(path))
        for path in ("llm-svc", "slopsearx-fixture", "provenance")
        if Path(path).exists()
    }
    artifact: dict[str, Any] = {
        "schema_version": "live-calibration-v2",
        "started_at": started,
        "limits": {
            "max_calls": MAX_CALLS,
            "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "max_retries": MAX_RETRIES,
            "max_tokens": MAX_TOKENS,
            "max_total_tokens": MAX_TOTAL_TOKENS,
        },
        "records": [],
        "calls": 0,
        "fixture_tree_digest_before": before,
    }
    failure_source: str | None = None
    try:
        corpus_id, cases = _validate_corpus(json.loads(corpus_path.read_text()))
        config = _config()
        estimate = sum(
            config["brave_cost"]
            if case["kind"] == "search"
            else config["llm_cost"] * MAX_TOKENS / 1000
            for case in cases
        )
        if estimate > COST_CEILING_USD:
            raise ValueError("configured worst-case estimate exceeds $1")
        config["provider_llm"] = provider_url or config["provider_llm"]
        config["twin_llm"] = twin_url or config["twin_llm"]
        artifact["corpus"] = {"id": corpus_id, "digest": corpus_digest(cases)}
        artifact["bounds"] = {
            "estimated_max_cost_usd": estimate,
            "estimated_live_provider_cost_usd": estimate,
            "cost_ceiling_usd": COST_CEILING_USD,
            "expected_calls": len(cases) * 2,
        }
        artifact["identity"] = {
            "requested": {
                "provider": "brave-search-api+llm",
                "model": config["llm_model"],
            },
            "observed": {
                "search_provider": "unavailable",
                "llm_provider": "unavailable",
                "model": "unavailable",
            },
        }
        call = request_fn or _request
        for case in cases:
            record: dict[str, Any] = {"case_id": case["id"], "kind": case["kind"]}
            observations: dict[
                str, tuple[int | None, str | None, str | None, bool]
            ] = {}
            for target, url in zip(
                ("provider", "twin"),
                (
                    (config["provider_search"], config["twin_search"])
                    if case["kind"] == "search"
                    else (config["provider_llm"], config["twin_llm"])
                ),
                strict=True,
            ):
                artifact["calls"] += 1
                if artifact["calls"] > MAX_CALLS:
                    raise ValueError("outbound call bound exceeded")
                headers = {"Accept": "application/json"}
                if case["kind"] == "search":
                    if target == "provider":
                        headers["X-Subscription-Token"] = config["brave_key"]
                    endpoint = (
                        url
                        + ("&" if "?" in url else "?")
                        + urllib.parse.urlencode({"q": case["input"], "count": 3})
                    )
                    method, payload = "GET", None
                else:
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {config['llm_key']}",
                        }
                    )
                    endpoint = url
                    payload = {
                        "model": config["llm_model"],
                        "messages": [{"role": "user", "content": case["input"]}],
                        "max_tokens": MAX_TOKENS,
                    }
                    method = "POST"
                started_call = time.monotonic()
                try:
                    status, body = call(endpoint, method, headers, payload)
                    elapsed = time.monotonic() - started_call
                    if status >= 400:
                        observations[target] = (status, None, None, False)
                        record[f"{target}_status"] = status
                        record[f"{target}_fingerprint"] = "unavailable"
                        record[f"{target}_latency_band"] = latency_band(elapsed)
                        record[f"{target}_finished_at"] = datetime.now(UTC).isoformat()
                        continue
                    normalized = (
                        normalize_search_response(body)
                        if case["kind"] == "search"
                        else normalize_llm_response(body)
                    )
                    fingerprint = schema_fingerprint(normalized)
                    model = normalized.get("model") if case["kind"] == "llm" else None
                    observations[target] = (status, fingerprint, model, False)
                    record[f"{target}_status"] = status
                    record[f"{target}_fingerprint"] = fingerprint
                    record[f"{target}_latency_band"] = latency_band(elapsed)
                    record[f"{target}_finished_at"] = datetime.now(UTC).isoformat()
                    if target == "provider":
                        if case["kind"] == "search":
                            artifact["identity"]["observed"]["search_provider"] = (
                                "brave-search-api"
                            )
                        else:
                            artifact["identity"]["observed"]["llm_provider"] = (
                                body.get("provider", "unavailable")
                                if isinstance(body, dict)
                                else "unavailable"
                            )
                            artifact["identity"]["observed"]["model"] = (
                                model or "unavailable"
                            )
                except urllib.error.HTTPError as exc:
                    observations[target] = (exc.code, None, None, False)
                    record[f"{target}_status"] = exc.code
                    record[f"{target}_fingerprint"] = "unavailable"
                    elapsed = time.monotonic() - started_call
                    record[f"{target}_latency_band"] = latency_band(elapsed)
                    record[f"{target}_finished_at"] = datetime.now(UTC).isoformat()
                except (OSError, TimeoutError):
                    observations[target] = (None, None, None, True)
                    record[f"{target}_status"] = None
                    record[f"{target}_fingerprint"] = "unavailable"
                    elapsed = time.monotonic() - started_call
                    record[f"{target}_latency_band"] = latency_band(elapsed)
                    record[f"{target}_finished_at"] = datetime.now(UTC).isoformat()
                except (ValueError, json.JSONDecodeError):
                    observations[target] = (200, None, None, True)
                    record[f"{target}_status"] = 200
                    record[f"{target}_fingerprint"] = "unavailable"
                    elapsed = time.monotonic() - started_call
                    record[f"{target}_latency_band"] = latency_band(elapsed)
                    record[f"{target}_finished_at"] = datetime.now(UTC).isoformat()
            provider, twin = observations["provider"], observations["twin"]
            if provider[3]:
                classification = "harness" if provider[0] == 200 else "infrastructure"
                failure_source = classification
            elif twin[3]:
                classification = "twin"
                failure_source = classification
            else:
                classification = classify_observation(
                    provider[0], twin[0], provider[1], twin[1]
                )
                if classification != "match" and classification != "provider_drift":
                    failure_source = classification
                elif classification == "provider_drift" and failure_source is None:
                    failure_source = "provider_drift"
            record["result"] = classification
            record["classification"] = classification
            artifact["records"].append(record)
    except (OSError, ValueError, json.JSONDecodeError):
        failure_source = "harness"
    after = {
        str(path): _tree_digest(Path(path))
        for path in ("llm-svc", "slopsearx-fixture", "provenance")
        if Path(path).exists()
    }
    if after != before:
        failure_source = "harness"
    artifact["fixture_tree_digest_after"] = after
    artifact["finished_at"] = datetime.now(UTC).isoformat()
    if failure_source in {
        "authentication",
        "quota",
        "twin",
        "infrastructure",
        "harness",
    }:
        artifact["outcome"] = "failure"
        artifact["failure_source"] = failure_source
    elif failure_source == "provider_drift":
        artifact["outcome"] = "advisory_success"
        artifact["failure_source"] = "provider_drift"
    else:
        artifact["outcome"] = "success"
        artifact["failure_source"] = "none"
    _write_artifact(output, artifact)
    return 0 if artifact["outcome"] != "failure" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--corpus", type=Path, default=Path("provenance/live-calibration-corpus.json")
    )
    args = parser.parse_args()
    return run(args.output, args.corpus)


if __name__ == "__main__":
    raise SystemExit(main())
