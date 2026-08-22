"""Deterministic, stdlib-only graders for the grounded-answer eval harness.

Each grader returns a structured verdict: ``{"pass": bool, "message": str,
"detail": dict}``. Graders are deliberately mechanical — there is no
keyword-as-grounding proxy: citation support binds a claim to an exact citation
index, an exact source URL, and an evidence span inside that source's pinned
content.

The ``result`` operand is the harness-normalized observed outcome::

    {
        "protocol": {"status": int, "success": bool},
        "answer": str,
        "sources": [{"url": str, "title": str, "relevance": str}],
        "citations": [{"index": int, "url": str}],
        "error": str | None,
    }
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Stable identities for provenance (issue #570).
GRADER_VERSIONS: dict[str, str] = {
    "check_protocol": "v1",
    "check_sources_present": "v1",
    "check_citation_shape": "v1",
    "check_citation_support": "v1",
    "check_required_claims": "v1",
    "check_prohibited_claims": "v1",
    "check_abstention": "v1",
    "check_citation_integrity": "v1",
}

_MARKER = re.compile(r"\[(\d+)\]")

INSUFFICIENT_PHRASES = (
    "unable to find",
    "no relevant web pages",
    "insufficient",
    "not enough",
    "cannot answer",
    "could not find",
)

CONTRADICTORY_PHRASES = (
    "contradict",
    "conflict",
    "conflicting",
    "inconsistent",
    "disagree",
    "conflicting sources",
    "cannot provide a confident answer",
    "cannot give a confident",
)


def normalize(text: str) -> str:
    """Lowercase and collapse all whitespace for deterministic matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _verdict(passed: bool, message: str, detail: dict | None = None) -> dict:
    return {"pass": passed, "message": message, "detail": detail or {}}


def check_protocol(result: dict, case: dict) -> dict:
    """The pipeline returned the per-case expected HTTP protocol outcome."""
    observed = result.get("protocol") or {}
    status = observed.get("status")
    success = observed.get("success")
    expected = (case.get("expected") or {}).get("protocol") or {}
    exp_status = expected.get("status")
    exp_success = expected.get("success", True)

    if isinstance(exp_status, str) and exp_status == "5xx":
        status_ok = isinstance(status, int) and 500 <= status < 600
    else:
        status_ok = status == exp_status
    success_ok = success is exp_success
    passed = status_ok and success_ok
    return _verdict(
        passed,
        (
            f"protocol {'matches' if passed else 'mismatch'}: "
            f"observed status={status} success={success}, "
            f"expected status={exp_status} success={exp_success}"
        ),
        {
            "observed_status": status,
            "observed_success": success,
            "expected_status": exp_status,
            "expected_success": exp_success,
        },
    )


def check_sources_present(result: dict, case: dict) -> dict:
    """Sources are non-empty, unique, and within ``allowable_source_urls``."""
    sources = result.get("sources") or []
    allowable = set((case.get("expected") or {}).get("allowable_source_urls") or [])
    if not sources:
        return _verdict(False, "no sources returned", {"source_count": 0})
    urls = [s.get("url", "") for s in sources]
    duplicates = sorted({u for u in urls if urls.count(u) > 1})
    if duplicates:
        return _verdict(
            False, f"duplicate source URLs: {duplicates}", {"duplicates": duplicates}
        )
    disallowed = sorted({u for u in urls if u not in allowable})
    if disallowed:
        return _verdict(
            False,
            f"sources outside allowlist: {disallowed}",
            {"disallowed": disallowed},
        )
    return _verdict(
        True, f"{len(sources)} allowed, unique sources", {"source_count": len(sources)}
    )


def check_citation_shape(result: dict, case: dict) -> dict:
    """Every citation index is in range and maps to the indexed source."""
    sources = result.get("sources") or []
    citations = result.get("citations") or []
    style = case.get("citation_style") or "inline"
    answer = result.get("answer") or ""
    if citations is None:
        return _verdict(False, "citations list missing")
    if not citations:
        return _verdict(True, "no citations to shape-check")
    for citation in citations:
        index = citation.get("index")
        url = citation.get("url", "")
        if not isinstance(index, int) or not (1 <= index <= len(sources)):
            return _verdict(
                False,
                f"citation index {index} out of range for {len(sources)} sources",
                {"index": index, "source_count": len(sources)},
            )
        source_url = sources[index - 1].get("url", "")
        if url != source_url:
            return _verdict(
                False,
                f"citation index {index} url {url} != source {source_url}",
                {"index": index, "url": url, "source_url": source_url},
            )
        if style == "compact":
            marker = f"[{index}]({url})"
            if marker not in answer:
                return _verdict(
                    False,
                    f"compact marker {marker} absent from answer",
                    {"index": index, "url": url},
                )

    return _verdict(True, f"{len(citations)} citations shape-checked")


def check_citation_support(result: dict, case: dict) -> dict:
    """Each declared claim is bound to its exact source and pinned content.

    PASS requires, per declared ``expected.citations[].{claim_id, answer_span,
    evidence_span, source_url, citation_index}``:

    (a) the claim's citation index resolves to the exact ``source_url``,
    (b) the normalized ``answer_span`` appears in the answer, and
    (c) the normalized ``evidence_span`` appears in that source's pinned
        content (``case["source_content"][source_url]``).

    A deliberately mis-cited negative case must fail here.
    """
    expected_citations = (case.get("expected") or {}).get("citations") or []
    if not expected_citations:
        return _verdict(True, "no declared citations to support-check")
    result_citations = result.get("citations") or []
    result_by_index = {c.get("index"): c.get("url", "") for c in result_citations}
    sources = result.get("sources") or []
    answer = normalize(result.get("answer") or "")
    pinned = case.get("source_content") or {}
    failures: list[dict] = []

    for claim in expected_citations:
        claim_id = claim.get("claim_id", "")
        index = claim.get("citation_index")
        source_url = claim.get("source_url", "")
        answer_span = normalize(claim.get("answer_span", ""))
        evidence_span = normalize(claim.get("evidence_span", ""))

        resolved = result_by_index.get(index)
        index_ok = resolved == source_url
        if not index_ok:
            failures.append(
                {
                    "claim_id": claim_id,
                    "criterion": "citation_index_to_source_url",
                    "index": index,
                    "resolved_url": resolved,
                    "source_url": source_url,
                }
            )

        answer_ok = bool(answer_span) and answer_span in answer
        if not answer_ok:
            failures.append(
                {
                    "claim_id": claim_id,
                    "criterion": "answer_span_present",
                    "answer_span": claim.get("answer_span"),
                }
            )

        pinned_content = pinned.get(source_url)
        evidence_ok = (
            bool(evidence_span)
            and pinned_content is not None
            and evidence_span in normalize(pinned_content)
        )
        if not evidence_ok:
            failures.append(
                {
                    "claim_id": claim_id,
                    "criterion": "evidence_span_in_pinned_content",
                    "evidence_span": claim.get("evidence_span"),
                    "source_url": source_url,
                    "pinned": pinned_content is not None,
                }
            )
        if index_ok and answer_ok and evidence_ok:
            # Ensure the resolved URL is actually among the returned sources.
            if source_url not in {s.get("url", "") for s in sources}:
                failures.append(
                    {
                        "claim_id": claim_id,
                        "criterion": "source_returned",
                        "source_url": source_url,
                    }
                )

    if failures:
        return _verdict(
            False,
            f"{len(failures)} citation-support failure(s)",
            {"failures": failures},
        )
    return _verdict(
        True, f"{len(expected_citations)} claim(s) supported by pinned content"
    )


def check_required_claims(result: dict, case: dict) -> dict:
    answer = normalize(result.get("answer") or "")
    required = (case.get("expected") or {}).get("required_claims") or []
    missing = [claim for claim in required if normalize(claim) not in answer]
    if missing:
        return _verdict(
            False, f"missing required claims: {missing}", {"missing": missing}
        )
    return _verdict(True, f"{len(required)} required claim(s) present")


def check_prohibited_claims(result: dict, case: dict) -> dict:
    answer = normalize(result.get("answer") or "")
    prohibited = (case.get("expected") or {}).get("prohibited_claims") or []
    found = [claim for claim in prohibited if normalize(claim) in answer]
    if found:
        return _verdict(False, f"prohibited claims present: {found}", {"found": found})
    return _verdict(True, f"{len(prohibited)} prohibited claim(s) absent")


def check_abstention(result: dict, case: dict) -> dict:
    expected = (case.get("expected") or {}).get("abstain_expected", False)
    qualifier = (case.get("expected") or {}).get("abstain_qualifier")
    answer = normalize(result.get("answer") or "")
    empty = not answer

    def _contains(phrases: tuple[str, ...]) -> bool:
        return any(phrase in answer for phrase in phrases)

    if expected:
        if qualifier == "insufficient":
            ok = empty or _contains(INSUFFICIENT_PHRASES)
            label = "insufficient-evidence abstention"
        elif qualifier == "contradictory":
            ok = _contains(CONTRADICTORY_PHRASES)
            label = "contradictory-evidence qualification/abstention"
        else:
            ok = (
                empty
                or _contains(INSUFFICIENT_PHRASES)
                or _contains(CONTRADICTORY_PHRASES)
            )
            label = "abstention"
        return _verdict(
            ok,
            f"{label} {'detected' if ok else 'not detected'}",
            {"empty": empty, "qualifier": qualifier},
        )

    if empty:
        return _verdict(
            False, "abstention not expected but answer is empty", {"empty": True}
        )
    if _contains(INSUFFICIENT_PHRASES) or _contains(CONTRADICTORY_PHRASES):
        return _verdict(
            False,
            "abstention not expected but answer contains an abstention phrase",
            {"empty": False},
        )
    return _verdict(True, "answer present and not an abstention")


def check_citation_integrity(result: dict, case: dict) -> dict:
    """No ``[N]`` marker in the answer is out of range or unmapped to a source."""
    sources = result.get("sources") or []
    citations = result.get("citations") or []
    citation_indices = {c.get("index") for c in citations}
    answer = result.get("answer") or ""
    bad: list[dict] = []
    for match in _MARKER.finditer(answer):
        index = int(match.group(1))
        if not (1 <= index <= len(sources)):
            bad.append(
                {"index": index, "reason": "out_of_range", "source_count": len(sources)}
            )
            continue
        if index not in citation_indices:
            bad.append({"index": index, "reason": "no_citation_returned"})
    if bad:
        return _verdict(
            False, f"{len(bad)} integrity violation(s)", {"violations": bad}
        )
    return _verdict(True, "all citation markers resolve")


GRADERS: dict[str, Callable[[dict, dict], dict]] = {
    "check_protocol": check_protocol,
    "check_sources_present": check_sources_present,
    "check_citation_shape": check_citation_shape,
    "check_citation_support": check_citation_support,
    "check_required_claims": check_required_claims,
    "check_prohibited_claims": check_prohibited_claims,
    "check_abstention": check_abstention,
    "check_citation_integrity": check_citation_integrity,
}


def applicable_graders(case: dict) -> list[str]:
    """Return the ordered grader ids that apply to *case*.

    For a non-200 expected protocol only ``check_protocol`` applies (a
    provider-failure outcome has no answer/sources to grade). For an
    abstention case the citation/source graders would vacuously fail on the
    intentionally empty result, so they are excluded; required/prohibited
    claim lists are empty for abstention cases and pass trivially.
    """
    expected = case.get("expected") or {}
    protocol = expected.get("protocol") or {}
    if protocol.get("status") not in (200, "2xx"):
        return ["check_protocol"]
    if expected.get("abstain_expected"):
        return [
            "check_protocol",
            "check_abstention",
            "check_required_claims",
            "check_prohibited_claims",
        ]
    return [
        "check_protocol",
        "check_sources_present",
        "check_citation_shape",
        "check_citation_support",
        "check_required_claims",
        "check_prohibited_claims",
        "check_abstention",
        "check_citation_integrity",
    ]
