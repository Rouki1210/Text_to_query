# Feature Store Query & Reporting Agent

An AI-powered business intelligence agent with two operating modes:

1. **On-demand Analyst** — translates plain-English questions into SQL against the
   feature store and returns tables / simple visualizations.
2. **Proactive Reporter** — a nightly job that scans data aggregates, detects notable
   cross-unit shifts, and publishes a plain-English executive summary to a team channel.

## Architecture (high level)

```
                 ┌────────────────────────────────────────────┐
 user question → │  Streamlit Chat UI (src/fsq_agent/ui)      │
                 └──────────────┬─────────────────────────────┘
                                ▼
                 ┌────────────────────────────────────────────┐
                 │  Agent core (core/agent.py)                │
                 │   1. retrieve relevant schema (semantic    │
                 │      layer, schema/)                       │
                 │   2. LLM generates SQL (sql/generator.py)  │
                 │   3. guarded execution (sql/executor.py)   │
                 │   4. self-correction loop on errors        │
                 └──────────────┬─────────────────────────────┘
                                ▼
                 ┌────────────────────────────────────────────┐
                 │  Feature store (DuckDB mock in dev,        │
                 │  real warehouse in prod via SQLAlchemy)    │
                 └────────────────────────────────────────────┘

 nightly cron →  reporter/pipeline.py (stats detection) →
                 reporter/narrator.py (LLM summary) → Slack webhook
```

## Repository layout

```
fsq-agent/
├── src/fsq_agent/
│   ├── config.py            # pydantic-settings, reads .env
│   ├── core/
│   │   ├── agent.py         # main orchestration loop (Sprint 1–2)
│   │   └── llm.py           # provider-agnostic LLM client
│   ├── schema/
│   │   ├── semantic_layer.py# loads & retrieves table/column descriptions
│   │   └── definitions/     # YAML data dictionary per business unit
│   ├── sql/
│   │   ├── generator.py     # prompt building + text-to-SQL
│   │   ├── executor.py      # read-only, guarded SQL execution
│   │   └── guards.py        # SELECT-only whitelist, row limits
│   ├── validation/
│   │   └── evaluator.py     # execution-accuracy scoring over evals/
│   ├── reporter/
│   │   ├── pipeline.py      # nightly stats scan (z-score / % change)
│   │   ├── narrator.py      # LLM turns findings into exec summary
│   │   └── publisher.py     # Slack/Teams webhook
│   └── ui/
│       └── app.py           # Streamlit chat interface (Sprint 2)
├── evals/
│   └── golden_set.json      # (question, gold SQL, expected result) pairs
├── data/mock/               # generated DuckDB with 2 business units
├── scripts/
│   ├── seed_mock_data.py    # build the dev feature store
│   └── run_nightly.py       # entrypoint for the scheduled job
├── tests/
├── docs/
│   └── decisions.md         # architecture decision records (ADR)
├── .env.example
├── pyproject.toml
└── README.md
```

## Sprint mapping

| Sprint | Modules to implement |
|--------|----------------------|
| 1 | `schema/`, `sql/generator.py`, `sql/executor.py`, `validation/`, mock data |
| 2 | cross-entity joins in `generator.py`, self-correction in `core/agent.py`, `ui/app.py` |
| 3 | `reporter/`, `scripts/run_nightly.py`, docs + presentation |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add your API key
python scripts/seed_mock_data.py
streamlit run src/fsq_agent/ui/app.py
```

## Development notes

- The executor is **read-only by design**: only `SELECT` statements pass
  `sql/guards.py`, and every query gets a row limit appended.
- Never let the LLM see raw credentials; all secrets live in `.env`.
- Every generated SQL is shown to the user alongside results for auditability.
