"""Central configuration. All secrets and environment-specific values live in .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor .env to the repo root, not the process working directory. A relative
# path would resolve against the CWD, so launching from anywhere else (e.g.
# `streamlit run` from a subdirectory) silently fell back to the defaults
# below — empty API key and, worse, the mock DuckDB URL instead of the real
# warehouse. Real environment variables still take precedence over this file.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")

    # --- LLM ---
    llm_provider: str = "anthropic"          # keep swappable
    llm_model: str = "claude-opus-4-8"
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    # Ceiling on a single completion. Reasoning models spend this budget on
    # thinking before emitting any SQL, and thinking length scales with
    # question difficulty — a hard cross-table question was measured at ~1.6k
    # output tokens where a simple count used 47. This is a cap, not a
    # reservation: you are billed for tokens produced, so a generous ceiling
    # costs nothing on easy questions and stops hard ones truncating.
    llm_max_tokens: int = 16000
    # Transient upstream errors (429/5xx) are retried with backoff by the SDK.
    # Bumped above the SDK default of 2 because gateways can be flaky and a
    # long eval run shouldn't die on one blip.
    llm_max_retries: int = 5

    # --- Database ---
    # Dev default: local DuckDB mock. In prod, point to the real warehouse,
    # e.g. "postgresql+psycopg://user:pass@host/db"
    database_url: str = "duckdb:///data/mock/feature_store.duckdb"
    query_row_limit: int = 500               # hard cap appended to every query
    query_timeout_seconds: int = 30
    # Schema the agent queries. Point this at a schema of sanitised views
    # (see scripts/generate_safe_views.py) so credential columns are not
    # reachable even by SELECT *. It becomes the connection's entire
    # search_path — deliberately excluding the base schema, so a table with
    # no view fails to resolve instead of silently falling through. Empty
    # leaves the driver default (DuckDB has no schemas to speak of).
    db_schema: str = ""

    # --- Reporter (Sprint 3) ---
    slack_webhook_url: str = ""
    zscore_threshold: float = 2.0            # what counts as "notable"
    min_pct_change: float = 0.15             # ignore shifts smaller than 15%

    # --- Safety ---
    # Credentials and PII the agent must never read. Matched case-insensitively
    # against bare column names, so one entry covers every table that has that
    # column. Comma-separated so it stays editable from .env.
    sensitive_columns: str = (
        "PasswordHash,Password,Email,WalletAddress,NonceValue,"
        "Birthday,Brithday,Token,Secret,ApiKey,Ssn"
    )

    @property
    def sensitive_column_set(self) -> frozenset[str]:
        """Lower-cased denylist, ready for membership tests."""
        return frozenset(
            c.strip().lower() for c in self.sensitive_columns.split(",") if c.strip()
        )


settings = Settings()
