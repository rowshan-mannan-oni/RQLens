from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults point at the Docker Compose services as seen from the host.
    database_url: str = "postgresql+psycopg://rqlens:rqlens@localhost:5432/rqlens"
    redis_url: str = "redis://localhost:6379/0"

    # One .duckdb file per project lives here.
    data_dir: Path = Path("data")
    max_upload_bytes: int = 500 * 1024 * 1024

    # Per-user limits. 0 means no limit.
    max_projects_per_user: int = 20
    max_datasets_per_project: int = 50
    # AI use per calendar month (UTC), summed over the user's projects. Free-tier models cost
    # nothing, so the call count is the limit that applies to them.
    monthly_llm_budget_usd: float = 5.0
    monthly_llm_calls: int = 2000
    duckdb_memory_limit: str = "2GB"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Shared with the web app, which signs short-lived JWTs for signed-in users.
    api_jwt_secret: str = ""

    # Any OpenAI-compatible endpoint. Default: Google Gemini free tier.
    # Groq: https://api.groq.com/openai/v1  OpenRouter: https://openrouter.ai/api/v1
    # Ollama (local): http://host.docker.internal:11434/v1
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.7-flash"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    # USD per 1M tokens as {"model": [input, output]}. Models not listed cost 0 (free tier).
    llm_prices: dict[str, tuple[float, float]] = {}
    # Error tracking (optional): a Sentry DSN, and the share of requests to trace (0 to 1).
    environment: str = "development"
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # Embeddings for column retrieval on wide tables. Empty disables them (word matching only).
    llm_embedding_model: str = "gemini-embedding-001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
