FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml ./
RUN mkdir -p apps/api && touch apps/api/__init__.py \
    && pip install -e ".[dev]"

COPY alembic.ini ./
COPY apps/api ./apps/api

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
