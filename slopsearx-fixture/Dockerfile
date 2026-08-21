FROM python:3.13-slim
WORKDIR /app
COPY slopsearx-fixture/pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY slopsearx-fixture/slopsearx_fixture/ slopsearx_fixture/
CMD ["uvicorn", "slopsearx_fixture.app:app", "--host", "0.0.0.0", "--port", "8080"]
