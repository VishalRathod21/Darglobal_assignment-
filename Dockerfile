# syntax=docker/dockerfile:1

# ---- Stage 1: build the React frontend ---------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ---------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_XET=1 \
    ENVIRONMENT=production \
    STATE_DIR=/app/state

WORKDIR /app/backend

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/data/raw/darglobal_pages.jsonl backend/data/raw/wasalt_listings.jsonl ./data/raw/

# Bake the knowledge base into the image: download the embedding model, embed every chunk
# and build the vector index at build time. The container then starts with a ready index,
# needs no persistent disk for it, and never downloads a model at runtime.
RUN python -m app.ingestion.pipeline --rebuild

COPY --from=frontend /build/dist /app/frontend/dist

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/state \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=4)"

# Hosting platforms inject $PORT; default to 8000 locally. One worker keeps memory low.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
