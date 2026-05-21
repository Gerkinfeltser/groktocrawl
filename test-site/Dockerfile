FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY test_site/ test_site/
CMD ["uvicorn", "test_site.app:app", "--host", "0.0.0.0", "--port", "8000"]
