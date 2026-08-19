# Release and Dependency-Update PR Triage

Owner: GroktoCrawl maintainers

## When to use

Run this routine once a week (or whenever the open PR queue holds release or
dependency-update PRs) so automated maintenance does not age. Automated PRs —
dependabot version bumps, pip-audit CVE remediation, and release-please
release PRs — are individually low-risk, but without a disposition they sit
open and make the project health signal hard to interpret
([issue #475](https://github.com/groktopus/groktocrawl/issues/475)).

## Automation cadence

| Automation | Cadence | Config |
|------------|---------|--------|
| **dependabot** | Weekly, Monday 09:00 America/New_York | [`.github/dependabot.yml`](../../.github/dependabot.yml) |
| **pip-audit** | Weekly, Monday 06:00 UTC + on push to `main` | [`.github/workflows/pip-audit.yml`](../../.github/workflows/pip-audit.yml) |
| **release-please** | On merge to `main` (creates/updates a release PR) | [`.github/workflows/release-please.yml`](../../.github/workflows/release-please.yml) |

- **dependabot** opens version-update PRs for Python (`pip`) and GitHub Actions
  dependencies each Monday. Grouped minor/patch updates land as grouped PRs for
  `agent-svc` (`fastapi`, `httpx` groups); ungrouped bumps open one PR each.
- **pip-audit** fails its job when any service's dependency tree contains a
  known CVE. It runs on a schedule and on every push to `main`, so a merge that
  introduces a vulnerable version is caught immediately.
- **release-please** (v5, `googleapis/release-please-action@v5`) creates or
  updates a release PR whenever a conventional-commit change lands on `main`,
  and — once that release PR is merged — tags the version and publishes a
  GitHub release.

## Dispositions

Every open release/dependency PR must be assigned one of these four
dispositions before it is left open or merged. Record the disposition on the
PR (a short comment is enough).

| Disposition | When to use | Action |
|-------------|-------------|--------|
| **merge** | CI is green (`Code Quality Gate` + `Runtime Gate`) and the change is wanted as-is. | Merge via `gh pr merge <PR> --merge --delete-branch --admin` (maintainer path), or let the bot merge once the required checks pass. |
| **rebase-fix** | The PR is stale or failing because it is behind `main`, or its lockfile drifted. | Rebase onto `main`, regenerate `uv.lock` (`uv lock` / `uv sync --locked`), push, then re-triage. |
| **supersede** | A newer change makes this PR redundant — a later bump already covers the same dependency, or the update was reverted/replaced. | Close it with a pointer to the superseding PR/commit. |
| **close** | The update is unwanted (a breaking or incompatible version, a range the project intentionally pins away from) or the PR is abandoned. | Close with a reason. |

## Classifying CI failures before leaving a PR open

Before a PR stays open with failing or unstable checks, classify the failure
into one of the three classes below and only then decide whether a rerun is
appropriate.

| Class | Meaning | Rerun? |
|-------|---------|--------|
| **product** | The change itself breaks the build/tests — e.g. a new dependency is incompatible with our Python version or a pinned range. | No. Rerunning does not help; fix the change (`rebase-fix`) or `supersede`/`close`. |
| **infrastructure** | The failure is environmental and unrelated to the PR — self-hosted runner flake, timeout, service outage, registry hiccup. | Yes. Re-run the failed job (`gh run rerun <run-id>` or the workflow's re-run action). If it passes, the PR is healthy. |
| **stale-branch** | The PR fails only because it is behind `main` or its lockfile is out of date. | Not immediately. First bring the branch up to date (rebase + regenerate `uv.lock`), then let CI run; rerun only after the branch is refreshed. |

**Rerun criteria:**

- Rerun a failing job only when the failure class is **infrastructure**
  (transient) or **stale-branch** *after* the branch has been refreshed.
- Never rerun to mask a **product** failure — fix the change first.
- To classify, read the individual check conclusions with `gh pr checks <PR>`
  and inspect the workflow run with `gh run view` to see which step failed
  before deciding the class.

## Aging threshold

During the weekly routine, review any open release/dependency PR older than
7 days. If it has no disposition, assign one and act on it. A PR left open
indefinitely with an untriaged CI state means the routine is not being run.

## Escalation

- **Level 1 (maintainer)**: run the weekly routine, assign each open
  release/dependency PR a disposition, and act on it (merge / rebase-fix /
  supersede / close).
- **Level 2 (security)**: if pip-audit reports a CVE, treat the affected
  dependency's PR as **merge** priority (or **rebase-fix** if the bump needs
  the lockfile regenerated) rather than letting it age.

## Current queue example (2026-08)

- **PR #511** (dependabot: cloakbrowser 0.5.2 → 0.5.3) — disposition **merge**; merged.
- **PR #526** (dependabot: qdrant-client `<1.20.0`) — disposition **merge**; merged.
- **PR #420** (release-please: release 0.13.0) — disposition **merge** once the
  maintainer approves and the required gates pass. Per
  [ADR-0046](../adr/0046-enforce-qa-checks-and-review-policy-on-main.md),
  release-please PRs (authored by `github-actions[bot]`) require a human
  approving review; the bot cannot merge them.
