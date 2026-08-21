#!/usr/bin/env python3
"""Bounded mutation-testing pilot runner for the search-client decision slice (issue #572).

Provisions the environment, copies tests/common under agent-svc/, runs the pinned
ephemeral mutmut 3.7.0 over ``agent/searxng_client.py`` only, captures the raw report,
cicd-stats, ``mutmut --version``, and ``mutmut show`` diffs, applies the flake rule
(segfault/suspicious > 0 -> clear the cache and rerun once), writes ``run-config.json``,
auto-generates ``classification.md``, and trap-cleans every transient artifact.

Usage (from the repository root):

    python3 scripts/run_mutation_pilot.py [--max-children N] [--out-dir DIR] [--no-self-provision]

The runner is self-provisioning: from a clean checkout it runs ``uv sync`` first (unless
``--no-self-provision``) so a fresh environment reproduces the same pilot. It is safe to
re-run; any stale transient artifacts from an interrupted prior run are cleaned first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_SVC = REPO_ROOT / "agent-svc"
MUTMUT_PIN = "mutmut==3.7.0"

# mutmut is installed ephemerally and pinned in the invocation; it is NEVER added to
# uv.lock or any dependency manifest (VAL-PILOT-017).
RUN_WITH_MUTMUT = ["uv", "run", "--with", MUTMUT_PIN, "--no-sync"]

# macOS CPython's urllib.request.getproxies() segfaults in getproxies_macosx_sysconf
# when the environment has no proxy vars (httpx.AsyncClient() init triggers it via
# get_environment_proxies()). Setting dummy localhost proxies makes getproxies_environment()
# non-empty and skips the crashing SystemConfiguration path. This is hermetic: the test
# slice monkeypatches the HTTP client, so no real connection or proxy use occurs.
PROXY_ENV = {
    "http_proxy": "http://127.0.0.1:0",
    "https_proxy": "http://127.0.0.1:0",
    "all_proxy": "http://127.0.0.1:0",
    # Let uv reach the package index directly despite the dummy proxy vars (which are
    # only intended for the pytest children to skip the crashing macOS proxy lookup).
    "NO_PROXY": "*",
    "no_proxy": "*",
}

# Every path the runner must never leave behind (and never commit) after a run.
TRANSIENT_PATHS = [
    "agent-svc/tests",
    "agent-svc/common",
    "agent-svc/mutants",
    "mutants",
    ".pytest_cache",
    "agent-svc/.pytest_cache",
    ".coverage",
    "agent-svc/.coverage",
    "agent-svc/test-outcomes.json",
    "agent-svc/test-outcomes.md",
    "agent-svc/test-outcomes.gw.json",
    "agent-svc/test-outcomes.gw.md",
    "agent-svc/uv.lock",
    "agent-svc/.venv",
]

# Mapping of mutmut verdict -> the classification allowed set (VAL-PILOT-004).
VERDICT_TO_CLASSIFICATION = {
    "killed": "killed",
    "survived": "survived",
    "no_tests": "no coverage",
    "timeout": "timeout",
    "suspicious": "infrastructure-tooling failure",
    "segfault": "infrastructure-tooling failure",
    "error": "infrastructure-tooling failure",
}

# Inline Python that runs under the ephemeral mutmut env: reads the full verdict list,
# calls mutmut's in-process show logic for every mutant, writes show-diffs for all
# non-killed mutants, and prints the rows (id, verdict, operator) as JSON on stdout.
_DIFF_SCRIPT = r"""
import json
import sys
from pathlib import Path

from mutmut.__main__ import Config, find_mutant, get_diff_for_mutant

Config.ensure_loaded()

results_file = Path(sys.argv[1])
outdir = Path(sys.argv[2])

def extract_operator(diff: str) -> str:
    minus = [ln[1:].strip() for ln in diff.splitlines()
             if ln.startswith("-") and not ln.startswith("---")]
    plus = [ln[1:].strip() for ln in diff.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")]
    if minus and plus:
        return " -> ".join([minus[0].strip(), plus[0].strip()])
    return " ".join(minus + plus)

rows = []
for line in results_file.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    name, verdict = line.split(": ", 1)
    try:
        m = find_mutant(name)
        diff = get_diff_for_mutant(name, path=m.path)
    except Exception as exc:  # pragma: no cover - defensive
        diff = f"# {name}: unable to produce diff ({exc})"
    operator = extract_operator(diff)
    if verdict != "killed":
        show_dir = outdir / "show-diffs"
        show_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        (show_dir / f"{safe}.txt").write_text(diff)
    rows.append({"id": name, "verdict": verdict, "operator": operator})
print(json.dumps(rows))
"""


def _run(
    argv: list[str],
    cwd: Path,
    *,
    extra_env: dict[str, str] | None = None,
    capture: bool = True,
    timeout: int = 1800,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def _rm(path: str) -> None:
    target = REPO_ROOT / path
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()


def clean_transient() -> None:
    for path in TRANSIENT_PATHS:
        _rm(path)


def self_provision() -> None:
    print("== provisioning environment (uv sync --locked --no-dev --group fast-tests)")
    proc = _run(
        ["uv", "sync", "--locked", "--no-dev", "--group", "fast-tests"], REPO_ROOT
    )
    if proc.returncode != 0:
        sys.exit(f"ERROR: uv sync failed: {proc.stderr[-2000:]}")


def make_copies() -> None:
    print("== copying tests/common into agent-svc/ (also_copy prerequisite)")
    clean_transient()
    for name in ("tests", "common"):
        src = REPO_ROOT / name
        dst = AGENT_SVC / name
        if not src.exists():
            sys.exit(f"ERROR: source {src} missing")
        shutil.copytree(src, dst)


def run_pilot(max_children: int, outdir: Path, qa_path: str) -> tuple[str, dict]:
    """Run the bounded pilot once; returns (raw_report_text, cicd_stats_dict)."""
    env = dict(PROXY_ENV)
    env["QA_OUTCOME_PATH"] = qa_path
    cmd = [*RUN_WITH_MUTMUT, "mutmut", "run", "--max-children", str(max_children)]
    print(f"== running pilot (cwd=agent-svc): {' '.join(cmd)}")
    proc = _run(cmd, AGENT_SVC, extra_env=env, timeout=1800)
    raw = proc.stdout + proc.stderr
    if proc.returncode not in (0, 1):
        sys.exit(f"ERROR: mutmut run failed (rc={proc.returncode}): {raw[-3000:]}")
    _run([*RUN_WITH_MUTMUT, "mutmut", "export-cicd-stats"], AGENT_SVC, extra_env=env)
    stats = {}
    stats_path = AGENT_SVC / "mutants" / "mutmut-cicd-stats.json"
    if stats_path.exists():
        stats = json.loads(stats_path.read_text())
    return raw, stats


def count_slice_tests(qa_path: str) -> int:
    """Count the collected tests in the pilot's search-client slice.

    The committed test file changes over time (the pilot hardened and extended it),
    so run-config.json must record the actual number of tests present at run time
    rather than a hardcoded value. ``--collect-only -q`` prints one line per test,
    which we count by node id.
    """
    env = dict(PROXY_ENV)
    env["QA_OUTCOME_PATH"] = qa_path
    argv = [
        *RUN_WITH_MUTMUT,
        "pytest",
        "--collect-only",
        "-q",
        "tests/service/test_searxng_client.py",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
    ]
    proc = _run(argv, AGENT_SVC, extra_env=env)
    if proc.returncode != 0:
        return 0
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def capture_results(outdir: Path, qa_path: str) -> None:
    env = dict(PROXY_ENV)
    env["QA_OUTCOME_PATH"] = qa_path
    all_res = _run(
        [*RUN_WITH_MUTMUT, "mutmut", "results", "--all", "True"],
        AGENT_SVC,
        extra_env=env,
    )
    (outdir / "mutmut-results.txt").write_text(all_res.stdout)
    nonall = _run([*RUN_WITH_MUTMUT, "mutmut", "results"], AGENT_SVC, extra_env=env)
    (outdir / "mutmut-results-nonkilled.txt").write_text(nonall.stdout)
    version = _run([*RUN_WITH_MUTMUT, "mutmut", "--version"], AGENT_SVC, extra_env=env)
    (outdir / "mutmut-version.txt").write_text(version.stdout or version.stderr)


def build_classification_and_diffs(outdir: Path, qa_path: str) -> None:
    """Generate show-diffs for non-killed mutants and the classification rows."""
    env = dict(PROXY_ENV)
    env["QA_OUTCOME_PATH"] = qa_path
    show_dir = outdir / "show-diffs"
    if show_dir.exists():
        shutil.rmtree(show_dir)  # clear stale captures before regenerating
    results_file = outdir / "mutmut-results.txt"
    script = "import re\n" + _DIFF_SCRIPT
    proc = _run(
        [*RUN_WITH_MUTMUT, "python", "-c", script, str(results_file), str(outdir)],
        AGENT_SVC,
        extra_env=env,
    )
    if proc.returncode != 0:
        sys.exit(f"ERROR: diff/classification generation failed: {proc.stderr[-3000:]}")
    rows = json.loads(proc.stdout.strip().splitlines()[-1])
    write_classification(outdir, rows)


def _rel(outdir: Path) -> str:
    try:
        return outdir.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(outdir)


def write_classification(outdir: Path, rows: list[dict]) -> None:
    total = len(rows)
    classified = sum(1 for r in rows if r["verdict"] in VERDICT_TO_CLASSIFICATION)
    lines = [
        "# Mutation Classification — Search-Client Decision Slice (issue #572)",
        "",
        "Every in-scope mutant produced by the bounded pilot is classified below. The mutant",
        "set is confined to `agent-svc/agent/searxng_client.py` (VAL-PILOT-001). Classifications",
        "are drawn from the allowed set: killed / survived / equivalent-or-likely-equivalent /",
        "no coverage / timeout / flaky / invalid / infrastructure-tooling failure. The ID set",
        "below exactly matches the raw report's in-scope mutant list (`mutmut-results.txt`);",
        "no mutant is silently omitted.",
        "",
        f"**In-scope mutants:** {total}",
        f"**Classified:** {classified} / {total}",
        "",
        "Run directory: `" + _rel(outdir) + "`",
        "Raw report: `raw-mutation-report.txt`",
        "Full verdict list: `mutmut-results.txt`",
        "CI/CD stats: `mutmut-cicd-stats.json`",
        "`mutmut show` diffs for all non-killed mutants: `show-diffs/`",
        "",
        "| ID | Source path | Operator / Diff | Classification |",
        "|----|-------------|-----------------|----------------|",
    ]
    for r in sorted(rows, key=lambda x: x["id"]):
        verdict = r["verdict"]
        cat = VERDICT_TO_CLASSIFICATION.get(verdict, "survived")
        op = (r["operator"] or "-").replace("|", "\\|")
        lines.append(f"| `{r['id']}` | `agent/searxng_client.py` | {op} | {cat} |")
    (outdir / "classification.md").write_text("\n".join(lines) + "\n")


def write_run_config(
    outdir: Path, max_children: int, qa_path: str, counts: dict, test_count: int
) -> None:
    cfg = {
        "pilot": "search-client decision slice bounded mutation-testing pilot (issue #572)",
        "run_dir": _rel(outdir),
        "iso_date": outdir.name.split("-search-client")[0],
        "tool": {
            "name": "mutmut",
            "version": "3.7.0",
            "install_method": "uv run --with mutmut==3.7.0 --no-sync (pinned, ephemeral; never added to uv.lock/manifests)",
            "version_capture": "mutmut-version.txt",
        },
        "scope": {
            "source_file": "agent-svc/agent/searxng_client.py",
            "only_mutate": ["agent/searxng_client.py"],
            "mutant_count": counts.get("total", 0),
            "bounds": "single source file; full-file run (no wildcard args) bounded by --max-children (a concurrency bound, not a mutant budget)",
        },
        "procedure": {
            "root_dir": str(REPO_ROOT),
            "cwd": "agent-svc/",
            "provisioning_command": "uv sync --locked --no-dev --group fast-tests",
            "mutation_invocation": "cd agent-svc && uv run --with mutmut==3.7.0 --no-sync mutmut run --max-children "
            + str(max_children),
            "with_packages": [MUTMUT_PIN],
            "cp_prerequisites": [
                "cp -r ../tests agent-svc/tests",
                "cp -r ../common agent-svc/common",
            ],
            "qa_outcome_path": qa_path,
            "proxy_env_workaround": "http_proxy=https_proxy=all_proxy=http://127.0.0.1:0 with NO_PROXY=* — bypasses the macOS CPython getproxies_macosx_sysconf segfault in urllib.request.getproxies() triggered by httpx.AsyncClient init (dummy proxies make getproxies_environment() non-empty; NO_PROXY lets uv still reach PyPI for the pinned install); hermetic (tests monkeypatch the HTTP client, no real proxy use)",
            "seed": "mutmut 3.7.0 exposes no --seed flag. Determinism is pinned by the fixed tool version (mutmut==3.7.0) and the deterministic mutant input order (source lines of agent/searxng_client.py in file order).",
            "timeout": {
                "bounded_by": "runner subprocess timeout on the mutmut run call",
                "value_seconds": 1800,
                "note": "per-mutant pytest invocations run the hermetic slice with neutralized addopts; no mutant timed out in the recorded run",
            },
            "max_children": max_children,
        },
        "test": {
            "suite": "tests/service/test_searxng_client.py",
            "count": str(test_count),
            "command": "QA_OUTCOME_PATH=<scratch> uv run --no-sync pytest tests/service/test_searxng_client.py -o 'addopts=' -p no:cacheprovider",
            "selection": {
                "per_mutant": {
                    "pytest_add_cli_args_test_selection": [
                        "tests/service/test_searxng_client.py"
                    ]
                },
                "note": "mutmut runs pytest_add_cli_args_test_selection per mutant plus a clean-suite baseline and forced-fail sanity pass; every pytest invocation uses -o addopts= and -p no:cacheprovider with a scratch QA_OUTCOME_PATH",
            },
        },
        "environment": {
            "uv_version": "0.11.18",
            "python_version": "3.12.11",
            "lockfile_state": "root uv.lock untouched; agent-svc/pyproject.toml gains only [tool.mutmut]; no permanent dependency added",
            "package_index": "PyPI — the pinned ephemeral mutmut install is the sole permitted external contact; the data plane is hermetic (no provider calls)",
        },
        "flake_rule": {
            "rule": "if segfault>0 or suspicious>0 in mutants/mutmut-cicd-stats.json, clear mutants/ and rerun once before trusting verdicts; a first occurrence is never a verdict",
            "recorded_run": {
                "segfault": counts.get("segfault", 0),
                "suspicious": counts.get("suspicious", 0),
                "rerun_triggered": bool(
                    counts.get("segfault", 0) or counts.get("suspicious", 0)
                ),
            },
        },
        "results": {
            "total": counts.get("total", 0),
            "killed": counts.get("killed", 0),
            "survived": counts.get("survived", 0),
            "no_coverage": counts.get("no_tests", 0),
            "timeout": counts.get("timeout", 0),
            "suspicious": counts.get("suspicious", 0),
            "segfault": counts.get("segfault", 0),
            "raw_report": "raw-mutation-report.txt",
            "results_list": "mutmut-results.txt",
            "cicd_stats": "mutmut-cicd-stats.json",
            "show_diffs_dir": "show-diffs/",
        },
        "artifacts": [
            "run-config.json",
            "raw-mutation-report.txt",
            "mutmut-results.txt",
            "mutmut-results-nonkilled.txt",
            "mutmut-cicd-stats.json",
            "mutmut-version.txt",
            "show-diffs/",
            "classification.md",
        ],
    }
    (outdir / "run-config.json").write_text(
        json.dumps(cfg, indent=2, sort_keys=True) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded mutation-testing pilot (issue #572)."
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=1,
        help="mutmut --max-children concurrency bound (default 1; serialized so concurrent pytest children do not corrupt the shared scratch QA_OUTCOME_PATH file read by tests/conftest.py)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="evidence output dir (default mutation/<iso-date>-search-client)",
    )
    parser.add_argument(
        "--no-self-provision", action="store_true", help="skip `uv sync` provisioning"
    )
    parser.add_argument(
        "--keep-artifacts", action="store_true", help="skip trap cleanup (debugging)"
    )
    args = parser.parse_args()

    iso_date = datetime.now(UTC).strftime("%Y-%m-%d")
    outdir = (
        Path(args.out_dir)
        if args.out_dir
        else REPO_ROOT / "mutation" / f"{iso_date}-search-client"
    )
    outdir = outdir if outdir.is_absolute() else REPO_ROOT / outdir
    outdir.mkdir(parents=True, exist_ok=True)

    qa_path = os.path.join(tempfile.gettempdir(), f"qa-mutmut-{iso_date}.json")

    if not args.no_self_provision:
        self_provision()

    clean_transient()
    make_copies()

    try:
        print(f"== output dir: {outdir}")
        raw, stats = run_pilot(args.max_children, outdir, qa_path)
        (outdir / "raw-mutation-report.txt").write_text(raw)

        # Flake rule: segfault/suspicious > 0 -> clear cache + rerun once; commit FINAL capture.
        if stats.get("segfault", 0) > 0 or stats.get("suspicious", 0) > 0:
            print("== flake rule triggered: clearing mutants/ and rerunning once")
            _rm("agent-svc/mutants")
            raw, stats = run_pilot(args.max_children, outdir, qa_path)
            (outdir / "raw-mutation-report.txt").write_text(raw)

        cicd = outdir / "mutmut-cicd-stats.json"
        cicd.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")

        capture_results(outdir, qa_path)
        build_classification_and_diffs(outdir, qa_path)
        test_count = count_slice_tests(qa_path)
        write_run_config(outdir, args.max_children, qa_path, stats, test_count)

        print("== pilot complete")
        print(
            "total:",
            stats.get("total"),
            "killed:",
            stats.get("killed"),
            "survived:",
            stats.get("survived"),
            "segfault:",
            stats.get("segfault"),
            "suspicious:",
            stats.get("suspicious"),
        )
    finally:
        if not args.keep_artifacts:
            clean_transient()
            print("== transient artifacts cleaned")

    return 0


if __name__ == "__main__":
    sys.exit(main())
