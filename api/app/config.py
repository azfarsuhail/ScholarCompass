from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/scholarcompass"
    session_secret: str = "dev-only-not-for-production-use-32b"
    session_ttl_hours: int = 72
    # Set false only for plain-HTTP local dev. Any deployed environment is HTTPS.
    cookie_secure: bool = True
    auto_create_schema: bool = True

    orizn_base_url: str = "https://visa.orizn.app"
    orizn_api_key: str | None = None

    # Groq (OpenAI-compatible LPU inference). No embeddings endpoint exists,
    # which is why RAG retrieval below uses Postgres FTS rather than vectors.
    groq_api_key: str | None = None
    match_model: str = "llama-3.3-70b-versatile"
    rag_model: str = "llama-3.3-70b-versatile"

    cors_origins: str = "http://localhost:3000"

    # Deterministic pass must return before the frontend's 5s budget.
    deterministic_budget_ms: int = 1500
    min_results_before_relaxing: int = 12

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def settings() -> Settings:
    return Settings()
