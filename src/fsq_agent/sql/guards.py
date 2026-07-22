"""Safety guards for LLM-generated SQL.

Defense in depth, outermost layer first:
1. Sensitive columns are withheld from the prompt (schema/semantic_layer.py).
2. These application-level checks reject anything that isn't a plain SELECT,
   names a credential/PII column, or reaches outside the agent's schema.
3. Sensitive columns are stripped from result sets, catching `SELECT *`.
4. A row limit is appended to every query.
5. The agent queries a schema of sanitised views, so the columns are not
   reachable at all (scripts/generate_safe_views.py).

Layers 1-4 live in the application and are therefore only as good as the
patterns below. Layer 5 is the one that holds if any of them has a gap.
"""

import re

import pandas as pd

from fsq_agent.config import settings

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|attach|merge)\b",
    re.IGNORECASE,
)

# Schema-qualifying a name sidesteps the search_path that points the agent at
# sanitised views — `public."Users"` reads the base table, and the internal
# Supabase schemas hold credentials outright. The agent has no legitimate
# reason to qualify anything: its own schema is already the search_path.
BLOCKED_SCHEMAS = re.compile(
    r"\b(public|auth|storage|realtime|vault|extensions|graphql|graphql_public"
    r"|pgbouncer|pgsodium|supabase_functions|supabase_migrations|cron|net"
    r"|information_schema|pg_catalog|pg_temp|pg_toast)\s*\.",
    re.IGNORECASE,
)


class UnsafeSQLError(Exception):
    pass


def _sensitive_column_in(sql: str) -> str | None:
    """Return the first denylisted column the query names, if any.

    Withholding these columns from the prompt is not enough — the model can
    guess that a users table has a password column without being told, and a
    user can ask for it directly. This is the check that actually stops it.

    Matching is on whole words, so a denied `Email` blocks `"Email"` and
    `Email` but not a legitimately different `EmailTemplates`. The trade-off
    is that composite names like `user_email` are a distinct word to the
    regex — add those to SENSITIVE_COLUMNS in .env if your schema uses them.
    """
    for column in settings.sensitive_column_set:
        if re.search(rf"\b{re.escape(column)}\b", sql, re.IGNORECASE):
            return column
    return None


def check(sql: str) -> None:
    stripped = _strip_comments(sql).strip()
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT/WITH queries are allowed.")
    if FORBIDDEN.search(stripped):
        raise UnsafeSQLError("Query contains a forbidden statement keyword.")
    if ";" in stripped.rstrip(";"):
        raise UnsafeSQLError("Multiple statements are not allowed.")
    if column := _sensitive_column_in(stripped):
        # Named explicitly so the self-correction loop can rewrite without it
        # rather than burning its retries guessing what went wrong.
        raise UnsafeSQLError(
            f"Query references restricted column '{column}'. This column holds "
            "credentials or personal data and can never be selected, filtered "
            "on, or joined. Rewrite the query without it."
        )
    if match := BLOCKED_SCHEMAS.search(stripped):
        schema = match.group(1)
        raise UnsafeSQLError(
            f"Query reaches into the '{schema}' schema. Write table names "
            "unqualified — the connection already resolves them to the tables "
            f"you were shown, e.g. FROM \"Users\" rather than {schema}.\"Users\"."
        )


def strip_sensitive_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Drop credential/PII columns from a result set.

    This is what catches `SELECT *`: the query text names no column, so
    `_sensitive_column_in()` has nothing to match on. Inspecting the SQL
    string cannot work here either — `with_row_limit()` wraps every query as
    `SELECT * FROM (...)`, so a literal `*` is always present.

    Returns the filtered frame plus the names that were withheld, so callers
    can tell the user something was held back rather than silently trimming.
    """
    denied = settings.sensitive_column_set
    withheld = [c for c in df.columns if str(c).lower() in denied]
    if not withheld:
        return df, []
    return df.drop(columns=withheld), withheld


def with_row_limit(sql: str) -> str:
    """Wrap the query so the row cap applies regardless of inner LIMITs."""
    return f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _guarded LIMIT {settings.query_row_limit}"


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
