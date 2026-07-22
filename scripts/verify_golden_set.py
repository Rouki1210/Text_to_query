"""Sanity-check every gold SQL in the golden set.

A gold query that errors, returns nothing, or returns more rows than the
guard's row limit makes its eval case meaningless — this catches all three
before you spend LLM calls on an evaluation run.

    python scripts/verify_golden_set.py
"""

import sys
from collections import Counter

from fsq_agent.config import settings
from fsq_agent.sql.executor import execute_readonly
from fsq_agent.validation.evaluator import case_tags, load_cases


def main() -> int:
    cases = load_cases()
    problems = []

    for i, case in enumerate(cases, start=1):
        label = f"[{i:02d}] {case['question'][:60]}"
        try:
            df = execute_readonly(case["gold_sql"])
        except Exception as exc:  # noqa: BLE001 - report, don't crash the sweep
            problems.append(f"{label}\n     ERROR: {type(exc).__name__}: {exc}")
            continue

        if df.empty:
            problems.append(f"{label}\n     EMPTY result set")
        elif len(df) == 1 and df.size == 1 and str(df.iat[0, 0]) in ("0", "0.0"):
            # A single zero is technically a result but a worthless assertion:
            # any wrong query that also counts nothing compares equal to it.
            problems.append(
                f"{label}\n     single 0 — any query returning nothing would "
                "also 'match'; rewrite the case so the answer is distinctive"
            )
        elif len(df) >= settings.query_row_limit:
            problems.append(
                f"{label}\n     {len(df)} rows — at/over the {settings.query_row_limit} "
                "row cap, results get truncated and comparison is unreliable"
            )
        else:
            print(f"OK   {label}  ({len(df)} rows x {len(df.columns)} cols)")

    tags = Counter(t for c in cases for t in case_tags(c))
    print(f"\n{len(cases)} cases total")
    print("By sprint:", dict(Counter(c.get("sprint", 1) for c in cases)))
    print("By unit:  ", dict(Counter(c.get("unit", "?") for c in cases)))
    print("By tag:   ", dict(tags))

    if tags.get("hard", 0) < 8:
        problems.append(
            f"only {tags.get('hard', 0)} 'hard' case(s) — T2.2 asks for at least 8, "
            "otherwise the overall number stays dominated by questions the agent "
            "can answer by matching column names"
        )

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(" -", p)
        return 1

    print("\nAll gold queries execute and return usable result sets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
