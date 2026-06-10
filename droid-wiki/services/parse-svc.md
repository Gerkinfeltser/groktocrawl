# parse-svc

Active contributors: groktopus

## Purpose

The parse service converts uploaded files to clean markdown. It handles PDF, DOCX, PPTX, and XLSX formats through a single `POST /parse` endpoint.

## Directory layout

```
parse-svc/
├── Dockerfile
├── pyproject.toml
└── parse_svc/
    └── app.py    # File parsing logic
```

## How it works

Files are uploaded via `POST /v2/parse` on agent-svc, which proxies the request to parse-svc. The service uses `python-multipart` for file reception and format-specific libraries for conversion. The response includes the extracted text as markdown.

## Integration points

- Called by agent-svc's `/v2/parse` route via HTTP proxy
- No host port is exposed -- reachable via Docker internal DNS at `http://parse-svc:8013`
