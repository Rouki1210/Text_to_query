"""Text-to-SQL generation and repair prompts."""

from fsq_agent.core.llm import LLMClient

SYSTEM_PROMPT = """You are a senior data analyst writing SQL for a feature store.

Rules:
- Output ONLY the SQL query. No markdown fences, no explanation.
- SELECT statements only. Never modify data.
- Use only the tables and columns provided in the schema context.
- If the question is ambiguous, prefer the most common business interpretation
  and add a SQL comment (-- assumption: ...) on the first line.
- Dialect: PostgreSQL.
- Identifiers are case-sensitive here. Table and column names use PascalCase
  and MUST be wrapped in double quotes exactly as shown in the schema, e.g.
  SELECT "Symbol", "ViewCount" FROM "Assets".
  Unquoted names are folded to lowercase by Postgres and will not resolve.
- Write table names unqualified. Never prefix them with a schema name.
- If the question asks for something the schema context does not contain —
  a credential or personal-data column that was withheld, or a column that
  simply does not exist — do NOT substitute a different column and do NOT
  invent a placeholder value. Returning "Username" labelled as "Email", or an
  empty string labelled as "PasswordHash", is worse than refusing: the reader
  believes it. Return exactly one row explaining the refusal instead:
  SELECT 'Cannot answer: <what was asked for> is not available.' AS "error"
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_sql(llm: LLMClient, question: str, schema_context: str) -> str:
    user = f"""Schema context:
{schema_context}

Question: {question}

Write the SQL query."""
    return _strip_fences(llm.complete(SYSTEM_PROMPT, user))


def repair_sql(
    llm: LLMClient, question: str, schema_context: str, failed_sql: str, error: str
) -> str:
    """Self-correction: feed the execution error back to the model."""
    user = f"""Schema context:
{schema_context}

Question: {question}

This SQL failed:
{failed_sql}

Error message:
{error}

Write a corrected SQL query."""
    return _strip_fences(llm.complete(SYSTEM_PROMPT, user))
