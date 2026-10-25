# Official Playwright image: Python + Chromium + all OS dependencies, pinned.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY config ./config

# Run as non-root
RUN useradd -m scraper && chown -R scraper /app
USER scraper

# The Azure Container Apps Job runs every enabled location from config/locations.yaml.
ENTRYPOINT ["python", "-m", "wmscraper"]
CMD ["run-all"]
