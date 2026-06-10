# Testing

## Integration tests

The main test suite is `tests/test_stack.py`, which tests all endpoints against a live Docker stack. Run with:

```bash
cp .env.sample .env
docker compose up --build -d
docker compose exec agent-svc python3 /app/agent/tests/test_stack.py
```

The integration tests:

- Verify all service health endpoints
- Test the scraper tier pipeline (llms.txt, content negotiation, browser)
- Test search (v1 and v2), map, and crawl endpoints
- Test the agent research loop and grounded Q&A
- Test extract with schema-based structured output
- Test browser session creation, execution, and cleanup
- Test monitor creation and deletion
- Test batch scrape and llms.txt generation
- Test SSE streaming for answer and agent endpoints
- Test vector index operations (semantic-svc)
- Test cache behavior

## Unit tests

Unit tests live in the root `tests/` directory:

| Test file | Coverage |
|---|---|
| `test_politeness.py` | 14 tests for robots.txt parsing, rate limiting, domain extraction |
| `test_quality.py` | 18 tests for boilerplate detection, completeness, block page detection |
| `test_metadata.py` | 25 tests for JSON-LD, OpenGraph, Twitter Card, meta tag extraction |
| `test_stealth.py` | 12 tests for Playwright stealth configuration |
| `test_substack.py` | 26 tests for Substack adapter URL matching, RSS parsing, content extraction |
| `test_prompts.py` | System prompt structure and consistency |
| `test_llmstxt_unit.py` | llms.txt generation logic |
| `test_cache.py` | 6 tests for scrape cache hit/miss, TTL, revalidation |
| `test_answer_endpoint.py` | 4 tests for grounded Q&A response structure and streaming |
| `test_phase2_semantic.py` | Vector index operations and semantic search |
| `test_phase3_retention.py` | Index retention scoring and eviction |

Run unit tests with:

```bash
python -m pytest tests/ -v
```
