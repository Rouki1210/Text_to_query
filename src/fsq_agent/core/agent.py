"""Main orchestration loop: question -> schema retrieval -> SQL -> execution.

Sprint 1: single-unit questions, no retry.
Sprint 2: cross-entity joins + self-correction loop (implemented below as a skeleton).
"""

from dataclasses import dataclass

import pandas as pd

from fsq_agent.core.llm import LLMClient
from fsq_agent.schema.semantic_layer import SemanticLayer
from fsq_agent.sql.executor import ExecutionError, execute_readonly
from fsq_agent.sql.generator import generate_sql, repair_sql

MAX_REPAIR_ATTEMPTS = 2


@dataclass
class AgentResult:
    question: str
    sql: str
    dataframe: pd.DataFrame | None
    error: str | None = None
    attempts: int = 1


class Agent:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.semantic_layer = SemanticLayer.load()

    def answer(self, question: str) -> AgentResult:
        """End-to-end: NL question -> validated result set."""
        # 1. Retrieve only the schema slices relevant to this question.
        schema_context = self.semantic_layer.retrieve(question)

        # 2. First SQL attempt.
        sql = generate_sql(self.llm, question, schema_context)

        # 3. Guarded execution with a self-correction loop.
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
            try:
                df = execute_readonly(sql)
                return AgentResult(question=question, sql=sql, dataframe=df, attempts=attempt)
            except ExecutionError as exc:
                if attempt > MAX_REPAIR_ATTEMPTS:
                    return AgentResult(
                        question=question, sql=sql, dataframe=None,
                        error=str(exc), attempts=attempt,
                    )
                sql = repair_sql(self.llm, question, schema_context, sql, str(exc))

        raise RuntimeError("unreachable")
