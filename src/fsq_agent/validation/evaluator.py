"""Execution-accuracy evaluation over the golden set (Sprint 1 deliverable).

For each eval case we run BOTH the gold SQL and the agent-generated SQL,
then compare result sets. Comparing executed results is more robust than
comparing SQL strings, since many different queries are equivalent.

Accuracy is also reported per tag. An overall number hides which kind of
question the agent is failing: a set of questions that merely echo column
names scores high without the semantic layer contributing anything, so the
`hard` group is what tells you whether descriptions are earning their cost.

Usage:
    python -m fsq_agent.validation.evaluator              # all cases
    python -m fsq_agent.validation.evaluator --sprint 1   # Sprint 1 scope only
    python -m fsq_agent.validation.evaluator --tag hard   # just the hard group
    python -m fsq_agent.validation.evaluator --no-save    # don't write a snapshot
"""

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from fsq_agent.config import settings
from fsq_agent.core.agent import Agent
from fsq_agent.sql.executor import execute_readonly

REPO_ROOT = Path(__file__).parents[3]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

# A case with no tags is one the agent can answer by matching question words
# against column names. Everything deliberately harder carries a tag.
DEFAULT_TAGS = ("easy",)

# Printed in this order; anything else follows alphabetically. Keeps the
# headline groups at the top and the diagnostic sub-groups underneath.
TAG_ORDER = ("easy", "hard")


def case_tags(case: dict) -> tuple[str, ...]:
    return tuple(case.get("tags") or DEFAULT_TAGS)


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    failures: list = field(default_factory=list)
    sprint: int | None = None
    tag: str | None = None
    model: str = ""
    # tag -> {"total": n, "passed": n}. A case counts towards every tag it
    # carries, so these sum to more than `total` — that is intended, they are
    # overlapping views of the same run, not a partition.
    by_tag: dict = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def record(self, tags: tuple[str, ...], passed: bool) -> None:
        for tag in tags:
            bucket = self.by_tag.setdefault(tag, {"total": 0, "passed": 0})
            bucket["total"] += 1
            bucket["passed"] += int(passed)


def _as_float(series: pd.Series) -> pd.Series | None:
    """Return `series` as float64 if it holds numbers, else None.

    SQL leaves the numeric type of an aggregate up to the author: MAX(x::int)
    comes back int64, MAX(x::numeric) comes back float64 or Decimal. Those are
    the same answer, so comparing dtypes would fail a correct query over an
    arbitrary choice. Booleans are deliberately excluded — True is not 1 here.
    """
    if pd.api.types.is_bool_dtype(series):
        return None
    if pd.api.types.is_numeric_dtype(series):
        return series.astype("float64")
    # NUMERIC columns can arrive as object-dtype Decimals.
    values = series.dropna()
    if series.dtype == object and len(values) and all(
        isinstance(v, Decimal) for v in values
    ):
        return series.astype("float64")
    return None


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Order-insensitive, name-insensitive, numeric-type-insensitive basis.

    Numbers are coerced to float and rounded so that mathematically equivalent
    queries don't fail on last-digit drift or on int-vs-numeric. Strings are
    left alone: '1' must stay distinct from 1, which is what makes the
    text-typed `Rank` column a meaningful trap.
    """
    out = df.copy()
    out.columns = range(len(out.columns))
    for col in out.columns:
        if (numeric := _as_float(out[col])) is not None:
            out[col] = numeric.round(4)
    return out.sort_values(by=list(out.columns)).reset_index(drop=True)


def results_match(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if a.shape != b.shape:
        return False
    try:
        return _normalize(a).equals(_normalize(b))
    except TypeError:
        return _normalize(a).astype(str).equals(_normalize(b).astype(str))


def load_cases(sprint: int | None = None, tag: str | None = None) -> list[dict]:
    """Load the golden set, optionally narrowed to a sprint and/or a tag.

    Cases without a `sprint` key are treated as Sprint 1, and cases without
    `tags` as `easy`, so older entries keep working untouched.
    """
    cases = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    if sprint is not None:
        cases = [c for c in cases if c.get("sprint", 1) == sprint]
    if tag is not None:
        cases = [c for c in cases if tag in case_tags(c)]
    return cases


def run(sprint: int | None = None, tag: str | None = None) -> EvalReport:
    cases = load_cases(sprint, tag)
    agent = Agent()
    report = EvalReport(
        total=len(cases), sprint=sprint, tag=tag, model=settings.llm_model
    )

    for i, case in enumerate(cases, start=1):
        tags = case_tags(case)
        gold_df = execute_readonly(case["gold_sql"])

        # Isolate per-case failures: a transient upstream error (proxy 502,
        # rate limit) must not discard the LLM calls already spent on the
        # rest of the run.
        try:
            result = agent.answer(case["question"])
        except Exception as exc:  # noqa: BLE001
            report.failures.append(
                {
                    "question": case["question"],
                    "unit": case.get("unit", ""),
                    "tags": list(tags),
                    "generated_sql": "",
                    "error": f"{type(exc).__name__}: {exc}",
                    "attempts": 0,
                }
            )
            report.record(tags, passed=False)
            print(f"  [{i}/{len(cases)}] ERROR {type(exc).__name__}")
            continue

        passed = result.dataframe is not None and results_match(gold_df, result.dataframe)
        report.record(tags, passed)
        if passed:
            report.passed += 1
            print(f"  [{i}/{len(cases)}] pass  [{','.join(tags)}]")
        else:
            report.failures.append(
                {
                    "question": case["question"],
                    "unit": case.get("unit", ""),
                    "tags": list(tags),
                    "generated_sql": result.sql,
                    "error": result.error,
                    "attempts": result.attempts,
                }
            )
            print(f"  [{i}/{len(cases)}] FAIL  [{','.join(tags)}]")

    return report


def format_by_tag(by_tag: dict) -> list[str]:
    """Render the per-tag breakdown, headline groups first."""
    def sort_key(tag: str) -> tuple[int, str]:
        return (TAG_ORDER.index(tag) if tag in TAG_ORDER else len(TAG_ORDER), tag)

    lines = []
    for tag in sorted(by_tag, key=sort_key):
        stats = by_tag[tag]
        total, passed = stats["total"], stats["passed"]
        pct = passed / total if total else 0.0
        indent = "  " if tag in TAG_ORDER else "    "
        lines.append(f"{indent}{tag:<14} {passed:>3}/{total:<3} ({pct:.0%})")
    return lines


def save_snapshot(report: EvalReport) -> Path:
    """Persist a run so prompt changes can be compared before/after."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scope = f"sprint{report.sprint}" if report.sprint else "all"
    if report.tag:
        scope += f"-{report.tag}"
    path = RESULTS_DIR / f"{stamp}-{scope}.json"
    payload = asdict(report) | {"accuracy": report.accuracy, "timestamp": stamp}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprint", type=int, help="only evaluate cases for this sprint")
    parser.add_argument("--tag", help="only evaluate cases carrying this tag")
    parser.add_argument("--no-save", action="store_true", help="skip writing a snapshot")
    args = parser.parse_args()

    report = run(sprint=args.sprint, tag=args.tag)
    scope = " + ".join(
        filter(None, [f"sprint {args.sprint}" if args.sprint else "all cases",
                      f"tag={args.tag}" if args.tag else ""])
    )
    print(f"\nModel: {report.model}   Scope: {scope}")
    print(f"Execution accuracy: {report.passed}/{report.total} ({report.accuracy:.0%})")
    for line in format_by_tag(report.by_tag):
        print(line)

    for f in report.failures:
        print(f"\nFAILED [{','.join(f.get('tags') or [])}]:", f["question"])
        print("  SQL:", f["generated_sql"])
        if f["error"]:
            print("  Error:", f["error"])

    if not args.no_save:
        print(f"\nSnapshot: {save_snapshot(report)}")


if __name__ == "__main__":
    main()
