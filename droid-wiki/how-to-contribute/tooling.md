# Tooling

## Build system

Each service has its own `Dockerfile` and `pyproject.toml`. The `docker-compose.yml` at the repo root orchestrates all containers. There is no top-level build tool -- each service is self-contained.

## Docker

```bash
# Build all services
docker compose build

# Start the full stack
docker compose up -d

# Start with fixture services (for development/testing)
docker compose --profile fixture up -d

# Start with FlareSolverr
docker compose --profile flare-solverr up -d

# Rebuild and recreate a single service
docker compose build agent-svc
docker compose up -d --force-recreate agent-svc

# View logs
docker compose logs -f agent-svc
```

## CLI

The `groktocrawl` shell script in the repo root wraps all endpoints. It requires the `requests` library:

```bash
./groktocrawl scrape https://example.com
./groktocrawl search "query" --limit 5
./groktocrawl agent "research question" --stream
./groktocrawl map https://example.com --limit 100
./groktocrawl --json scrape https://example.com
./groktocrawl --server http://localhost:8080 agent "question"
```

## CI/CD

The `.github/workflows/` directory contains GitHub Actions workflows for automated testing on pull requests. The project uses Conventional Commits and DCO sign-off.

## AgentSkills compatibility

GroktoCrawl ships as an AgentSkills-compatible skill at `skills/groktocrawl/`. Any agent that supports the AgentSkills format (Claude Code, Cursor, Hermes Agent) can load it:

```
skills/groktocrawl/
├── SKILL.md
├── scripts/groktocrawl
├── references/triggers.md
└── assets/examples.md
```
