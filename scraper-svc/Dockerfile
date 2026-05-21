FROM python:3.13-slim

# Install Playwright browsers
RUN pip install playwright && playwright install chromium

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY scraper/ scraper/

CMD ["uvicorn", "scraper.app:app", "--host", "0.0.0.0", "--port", "8001"]
