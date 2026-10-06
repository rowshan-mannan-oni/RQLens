FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Pango and fonts for PDF reports (WeasyPrint).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml ./
RUN mkdir -p apps/api && touch apps/api/__init__.py \
    && pip install -e ".[dev]"

COPY alembic.ini ./
COPY apps/api ./apps/api

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
