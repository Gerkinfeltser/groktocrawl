# portal-svc

Active contributors: groktopus

## Purpose

The portal service provides a web-based user interface for GroktoCrawl. It offers a Google-inspired single-search-bar interface that routes queries through the grounded Q&A endpoint with SSE streaming.

## Directory layout

```
portal-svc/
├── Dockerfile
├── pyproject.toml
└── portal/
    ├── __init__.py
    ├── app.py          # FastAPI with GET / and POST /ask
    └── templates/
        └── index.html  # Jinja2 template for the search UI
```

## Key abstractions

| Abstraction | File | Description |
|---|---|---|
| `ask()` | `portal/app.py` | Proxies queries to agent-svc `/v2/answer` with SSE streaming |
| `index.html` | `portal/templates/index.html` | Search bar UI with real-time token display and recent queries sidebar |

## How it works

The portal is a lightweight FastAPI + Jinja2 application. The `POST /ask` endpoint receives a query from the search form, forwards it to agent-svc's `/v2/answer` endpoint with `stream: true`, and streams the SSE response back to the browser. The frontend displays tokens in real time alongside source citations.

A recent queries sidebar uses localStorage to persist the user's search history. The portal runs on port 8082.

## Integration points

- Proxies all queries to agent-svc via `AGENT_BASE_URL` environment variable
- No database -- state is client-side only (localStorage)
