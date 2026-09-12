from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# libpq query parameters that asyncpg does not accept. Neon hands you a URL
# containing both, and passing them through raises
# `connect() got an unexpected keyword argument 'sslmode'` at first connect.
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding", "connect_timeout", "target_session_attrs"}


def normalize_database_url(url: str) -> str:
    """Make a pasted Postgres URL usable by SQLAlchemy's asyncpg driver.

    Neon's console gives you:
        postgresql://user:pw@ep-x-pooler.region.aws.neon.tech/db
            ?sslmode=require&channel_binding=require

    Three things are wrong with that for us, and all three fail at runtime
    rather than at import, so they are worth fixing once here:

      1. No `+asyncpg`, so SQLAlchemy reaches for the sync psycopg2 driver.
      2. `sslmode` is a libpq parameter; asyncpg takes `ssl` instead.
      3. `channel_binding` is likewise libpq-only.

    TLS is preserved, not dropped: `sslmode=require` becomes `ssl=require`.
    """
    if not url:
        return url

    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    if "asyncpg" not in scheme:
        return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))

    kept, require_ssl = [], False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == "sslmode":
            # verify-full has no direct asyncpg query equivalent; `require` keeps
            # the connection encrypted, which is what Neon mandates.
            require_ssl = value.lower() in ("require", "verify-ca", "verify-full", "prefer")
        elif key.lower() in _LIBPQ_ONLY_PARAMS:
            continue
        else:
            kept.append((key, value))

    if require_ssl and not any(k.lower() == "ssl" for k, _ in kept):
        kept.append(("ssl", "require"))

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


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
    # Split by workload, and verified against this account's /v1/models list
    # rather than assumed -- Groq's catalogue varies per account, and a model
    # the key cannot see fails at request time with a 404, not at startup.
    #   match:  one call per candidate, up to 5 concurrent, so latency dominates.
    #   rag:    one call per answer, and it must not misquote a source, so the
    #           larger model earns its extra seconds here.
    match_model: str = "openai/gpt-oss-20b"
    rag_model: str = "openai/gpt-oss-120b"

    cors_origins: str = "http://localhost:3000"

    # Deterministic pass must return before the frontend's 5s budget.
    deterministic_budget_ms: int = 1500
    min_results_before_relaxing: int = 12

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def async_database_url(self) -> str:
        """The URL the engine should actually use. Always go through this."""
        return normalize_database_url(self.database_url)


@lru_cache
def settings() -> Settings:
    return Settings()
