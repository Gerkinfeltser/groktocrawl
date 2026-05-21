FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY search_svc/ search_svc/
CMD ["uvicorn", "search_svc.app:app", "--host", "0.0.0.0", "--port", "8010"]
