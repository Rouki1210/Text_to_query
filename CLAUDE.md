# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

**Feature Store Query & Reporting Agent** — an internship project (3 sprints) building a BI agent with two modes:

1. **On-demand analyst**: plain-English question → SQL → data table / simple chart (Streamlit chat UI).
2. **Proactive reporter**: nightly job that statistically detects notable shifts across business units, then uses an LLM to write a plain-English executive summary posted to Slack.

The feature store spans two business units: **real estate** and **electric vehicles**. In dev, it's a local DuckDB mock; in prod it will be a real warehouse (only `DATABASE_URL` changes).

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                      # then fill in ANTHROPIC_API_KEY

# Build the local mock feature store (required before anything else)
python scripts/seed_mock_data.py

# Run tests
pytest                                    # or: pytest tests/test_guards.py -q

# Lint
ruff check src tests

# Run the chat UI (Sprint 2)
streamlit run src/fsq_agent/ui/app.py

# Run the text-to-SQL evaluation (Sprint 1 quality metric)
python -m fsq_agent.validation.evaluator

# Run the nightly report once, manually (Sprint 3)
python scripts/run_nightly.py             # dry-runs to stdout if SLACK_WEBHOOK_URL unset
```

If running scripts without installing the package: prefix with `PYTHONPATH=src`.

## Architecture — the pipeline

Question flow (see `core/agent.py`, the orchestrator):

```
question
  → SemanticLayer.retrieve()        schema/semantic_layer.py  (pick relevant schema slices)
  → generate_sql()                  sql/generator.py          (LLM, prompt lives here)
  → execute_readonly()              sql/executor.py           (guards + SQLAlchemy)
      └─ on ExecutionError → repair_sql() and retry (max 2 repairs)
```

Nightly flow (`scripts/run_nightly.py`):

```
detect()   reporter/pipeline.py   — pandas z-score + %-change vs 28-day baseline
→ narrate() reporter/narrator.py  — LLM rewrites validated findings only
→ publish() reporter/publisher.py — Slack webhook (dry-run prints to stdout)
```

## Non-negotiable design rules

- **Read-only SQL, always.** Every generated query must pass `sql/guards.check()`
  (SELECT/WITH only, no multi-statement, forbidden-keyword blocklist) and gets
  wrapped with a hard row limit via `guards.with_row_limit()`. Never bypass the
  guard, never add write capability, never widen the blocklist exceptions.
- **The LLM never sees raw data in the reporter.** Statistics decide what is
  "notable" (deterministic, auditable); the LLM only narrates pre-computed
  `Finding` objects. Do not refactor this into "LLM reads the tables".
- **Show the SQL.** The UI always exposes generated SQL for auditability. Keep it.
- **Provider-agnostic LLM.** All LLM calls go through `core/llm.py` (`LLMClient`).
  Never call a provider SDK directly from other modules.
- **Config via `config.py` only.** No hardcoded secrets, thresholds, or DB URLs;
  everything reads from `.env` through pydantic-settings.
- **Semantic layer is the source of schema truth.** New tables/columns are added
  as YAML in `schema/definitions/<unit>.yaml` (with `keywords`, per-column
  descriptions, and `joins` hints) — not hardcoded in prompts.

## Quality metric

Text-to-SQL quality = **execution accuracy** over `evals/golden_set.json`:
run both gold SQL and generated SQL, compare result sets order- and
column-name-insensitively (`validation/evaluator.py`). When changing prompts in
`sql/generator.py`, run the evaluator before and after. Add new eval cases
whenever a failure mode is found — target is 20–30 cases.

## Sprint status

- **Sprint 0 (done):** scaffold, tech stack, mock data, guards + tests, ADRs.
- **Sprint 1 (current):** tune `sql/generator.py` prompts, expand golden set,
  hit good execution accuracy on single-unit questions for both business units.
- **Sprint 2:** cross-entity joins (region is the shared key), smarter schema
  retrieval, polish self-correction loop and Streamlit UI.
- **Sprint 3:** tune reporter thresholds, schedule the job, docs + final presentation.

Architecture decisions and their rationale live in `docs/decisions.md` (ADRs).
When making a significant design choice, append a new ADR there.

## Known gotchas

- The mock data injects an upward EV trend for all of July, so by mid-July it is
  absorbed into the 28-day baseline and `detect()` returns 0 findings. To test
  the reporter, either add a sharp shift near the final seeded day in
  `scripts/seed_mock_data.py` or temporarily lower `ZSCORE_THRESHOLD` /
  `MIN_PCT_CHANGE` in `.env`.
- `data/mock/*.duckdb` is gitignored; always re-run `seed_mock_data.py` after a
  fresh clone. The seed is deterministic (seed=42) so eval results are reproducible.
- SemanticLayer retrieval is keyword-based (Sprint 1 baseline); if it selects no
  unit it deliberately falls back to including ALL units rather than guessing.
- `streamlit run` needs the package importable — install with `pip install -e .`
  or set `PYTHONPATH=src`.
