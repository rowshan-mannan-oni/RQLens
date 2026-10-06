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


@lru_cache
def get_settings() -> Settings:
    return Settings()
