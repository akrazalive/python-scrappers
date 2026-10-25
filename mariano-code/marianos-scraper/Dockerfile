# Optional container image (the Azure job can also run the source package directly, see deploy/azure).
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src MSCRAPER_STATE_DIR=/state
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY config ./config
RUN useradd -m scraper && mkdir -p /state && chown -R scraper /app /state
USER scraper
ENTRYPOINT ["python", "-m", "mscraper"]
CMD ["run-all"]
