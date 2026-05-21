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

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
