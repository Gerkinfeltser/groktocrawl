FROM python:3.13-slim

WORKDIR /app

# Install dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir mcp>=1.27.0 httpx>=0.27.0 pydantic>=2.0.0

# Copy application code
COPY groktocrawl_client.py .
COPY mcp_server.py .

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')" || exit 1

EXPOSE 8002
CMD ["python", "mcp_server.py"]
