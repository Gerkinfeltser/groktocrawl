FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a
WORKDIR /app
COPY llm-svc/pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY llm-svc/llm_svc/ llm_svc/
COPY common/ common/
CMD ["uvicorn", "llm_svc.app:app", "--host", "0.0.0.0", "--port", "8011"]
