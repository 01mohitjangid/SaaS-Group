# Build context is the repo root so data/challenge (reference.json + seed) ships too.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /srv/backend/pyproject.toml
COPY backend/app /srv/backend/app
RUN pip install --no-cache-dir -e /srv/backend

COPY backend /srv/backend
COPY data /srv/data

WORKDIR /srv/backend

RUN useradd --system --uid 10001 peblo && mkdir -p /srv/storage && chown -R peblo /srv
USER peblo

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.seed --if-empty && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
