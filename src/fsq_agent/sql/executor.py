"""Read-only, guarded execution against the feature store."""

import re

import pandas as pd
from sqlalchemy import create_engine, event, text

from fsq_agent.config import settings
from fsq_agent.sql import guards

_engine = None

# db_schema is interpolated into a SET statement, so it must be a bare
# identifier — it comes from config, but config is not a place to allow SQL.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ExecutionError(Exception):
    """Raised for any failure the agent may try to self-correct."""


def _session_settings() -> list[str]:
    """SET statements applied to every new connection.

    These are issued after connect rather than passed as libpq startup
    `options`: Supabase's pooler silently drops the compact `-cname=value`
    form, so a search_path set that way never arrives and unqualified names
    keep resolving to the base tables — the sanitised views would be bypassed
    with no error to notice.
    """
    statements = []
    if settings.db_schema:
        if not _IDENTIFIER.match(settings.db_schema):
            raise ValueError(f"DB_SCHEMA must be a plain identifier, got {settings.db_schema!r}")
        # No fallback to the base schema: a table with no view should fail to
        # resolve rather than quietly reach the real one.
        statements.append(f"SET search_path TO {settings.db_schema}")
    # Belt to the guard's braces — enforced by the server, not by a keyword
    # blocklist, so it holds even if a write slips past guards.check().
    statements.append("SET default_transaction_read_only TO on")
    if settings.query_timeout_seconds:
        statements.append(
            f"SET statement_timeout TO {int(settings.query_timeout_seconds) * 1000}"
        )
    return statements


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url)

        # Postgres-only: DuckDB has neither GUC and would error on SET.
        if _engine.dialect.name == "postgresql":
            statements = _session_settings()

            @event.listens_for(_engine, "connect")
            def _apply_session_settings(dbapi_connection, _record):
                with dbapi_connection.cursor() as cur:
                    for statement in statements:
                        cur.execute(statement)

    return _engine


def execute_readonly(sql: str) -> pd.DataFrame:
    """Run a guarded read.

    The returned frame carries `attrs["withheld_columns"]` listing any
    sensitive columns removed from the result, so the UI can say so.
    """
    try:
        guards.check(sql)
    except guards.UnsafeSQLError as exc:
        # Unsafe SQL is also surfaced as ExecutionError so the repair loop
        # can ask the model for a plain SELECT instead.
        raise ExecutionError(f"Rejected by safety guard: {exc}") from exc

    guarded_sql = guards.with_row_limit(sql)
    try:
        with get_engine().connect() as conn:
            df = pd.read_sql(text(guarded_sql), conn)
    except Exception as exc:  # surface DB errors to the self-correction loop
        raise ExecutionError(str(exc)) from exc

    df, withheld = guards.strip_sensitive_columns(df)
    df.attrs["withheld_columns"] = withheld
    return df
