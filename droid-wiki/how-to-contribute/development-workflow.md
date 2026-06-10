# Development workflow

## Branch, code, test, PR

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Make your changes in the relevant service directory
3. Run the integration tests (see [Testing](testing.md))
4. Commit with a clear Conventional Commits message: `git commit -s -m "feat: add widget"`
5. Open a pull request against the main branch

## Making changes to a service

```bash
# Edit the relevant service code
vim agent-svc/agent/api.py

# Rebuild the service image
docker compose build agent-svc

# Recreate the container
docker compose up -d --force-recreate agent-svc

# Run integration tests
docker compose exec agent-svc python3 /app/agent/tests/test_stack.py
```

## Adding a new endpoint

1. Add the route handler in `agent-svc/agent/api.py`
2. Add request/response models in `agent-svc/agent/models.py`
3. For async endpoints (returning a job ID), accept a `webhook` field and fire it via `deliver_webhook()` in `agent/webhook.py`
4. Rebuild the agent-svc image
5. Add a test case in `tests/test_stack.py`

## Architecture Decision Records

Significant architectural decisions are documented as ADRs in `docs/adr/`. When making a change with lasting impact, write a new ADR following the MADR template. ADRs are immutable after acceptance -- to change a decision, write a new ADR and update the old one's status.
