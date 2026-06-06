# Using GroktoCrawl with curl

```bash
# Health check
curl http://localhost:8080/health

# Scrape a URL
curl -X POST http://localhost:8080/v2/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Start an agent research job
curl -X POST http://localhost:8080/v2/agent \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?"}'

# Check agent job status
curl http://localhost:8080/v2/agent/<job_id>

# Cancel an agent job
curl -X DELETE http://localhost:8080/v2/agent/<job_id>

# Grounded Q&A — one call, cited answer
curl -X POST http://localhost:8080/v2/answer \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the capital of France?", "num_sources": 3}'

# Grounded Q&A with SSE streaming (real-time tokens)
curl -X POST http://localhost:8080/v2/answer \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the Fed rate?", "num_sources": 3, "stream": true}'
```
