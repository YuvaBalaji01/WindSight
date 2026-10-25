# ── WindSight UK – Backend Dockerfile ──────────────────────────────────────
# Slim Python 3.12 base keeps the image small while staying close to dev env.
FROM python:3.12-slim

# Security: run as non-root
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY analytics.py ingestion.py main.py routes.py ./

# The cache directory is mounted as a volume in docker-compose so that
# Elexon data fetched on first startup persists across container restarts.
RUN mkdir -p /app/cache && chown appuser:appgroup /app/cache

USER appuser

EXPOSE 8000

# Use 1 worker for development; increase in production.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
