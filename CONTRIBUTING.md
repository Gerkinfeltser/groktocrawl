# Contributing to GroktoCrawl

Thanks for your interest! GroktoCrawl is MIT-licensed and contributions of all kinds are welcome.

## Code of Conduct

Be excellent to each other. This project is small but aims to be a welcoming space for contributors of all experience levels.

## How to Contribute

### Reporting Bugs

Open a GitHub issue with:
- A clear description of the bug
- Steps to reproduce
- The output of `docker compose logs` for the affected service
- Your `.env` file (redact API keys)

### Suggesting Features

Open a GitHub issue with:
- What you want to accomplish
- Why it doesn't fit as a post-MVP improvement
- A sketch of the API or behavior change (optional but helpful)

### Pull Requests

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature` or `fix/your-bug`
3. Make your changes
4. Run the integration tests (see below)
5. Commit with a clear message
6. Open a PR

### Running Tests

```bash
# From the repo root:
cp .env.sample .env
docker compose up --build -d
docker compose exec agent-svc python3 /app/agent/tests/test_stack.py
```

All tests must pass before a PR is merged.

## Development Setup

You need Docker and Docker Compose. No other dependencies are required — everything runs in containers.

```bash
git clone https://github.com/your-username/groktocrawl
cd groktocrawl
cp .env.sample .env
docker compose up --build -d

# Verify health
curl http://localhost:8080/health
```

## Coding Conventions

- **Python 3.12+** with type hints
- **FastAPI** for all HTTP services
- **Async/await** throughout (except RQ worker functions which are sync wrappers)
- **MIT license** — all contributions are under this license
- Keep dependencies minimal. Each service's `pyproject.toml` should list only what it needs.
- **Webhook support required for all async endpoints** — any new endpoint that returns a job ID must accept a `webhook` field in its request and fire it on completion/failure via `deliver_webhook()` in `agent/webhook.py`. This ensures all async jobs are observable.

## Project Layout

- `agent-svc/` — the main API service (FastAPI + research worker)
- `scraper-svc/` — URL-to-markdown conversion service
- `search-svc/` — search fixture for local testing (replaceable with SearXNG)
- `llm-svc/` — LLM fixture for local testing (replaceable with any OpenAI-compatible backend)
- `test-site/` — fixture website for integration tests
- `tests/` — integration tests

## Architecture Decision Records

Significant architectural decisions are documented as ADRs in `docs/adr/`. Each ADR follows the MADR template and covers context, decision drivers, considered options, and consequences.

**Convention:**

- **File name:** `NNNN-title-with-dashes.md` (sequential numbers, imperative verb phrase)
- **Statuses:** `proposed`, `accepted`, `rejected`, `deprecated`, `superseded by ADR-NNNN`
- **Immutability:** ADRs are never edited after acceptance. To change a decision, write a new ADR and update the old one's status.
- **Linking:** Reference related ADRs via relative links in the Links section.

**When to write an ADR:**

- Adding a new integration or service
- Changing an existing architectural pattern
- Choosing between significant alternatives with lasting impact
- Any decision a future contributor would want to understand *why* it was made

**Workflow:**

1. Create the ADR as `docs/adr/NNNN-title-with-dashes.md` (next available number)
2. Get it reviewed as part of the PR
3. On acceptance, update the ADR status and the table in `docs/adr/README.md`

See `docs/adr/README.md` for the full index of existing ADRs.

## Commit Guidelines

This project uses **Conventional Commits**:

```
<type>: <short description>

<longer explanation if needed>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `chore`, `perf`, `style`

Branch names should match the commit type: `feat/add-widget`, `fix/login-timeout`.

### Sign-Off (DCO)

Every commit must include a `Signed-off-by` trailer, certifying that you have the right to contribute the code under the MIT License:

```bash
git commit -s -m "feat: add widget"
```

This is a [Developer Certificate of Origin](https://developercertificate.org/) requirement. It is legally simpler than a CLA.

## PR Template

A pull request template is available at `.github/PULL_REQUEST_TEMPLATE.md`. Fill it out completely when opening a PR.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
