# Feature Store Query & Reporting Agent

An AI-powered business intelligence agent with two operating modes:

1. **On-demand Analyst** — translates plain-English questions into SQL against the
   feature store and returns tables / simple visualizations.
2. **Proactive Reporter** — a nightly job that scans data aggregates, detects notable
   cross-unit shifts, and publishes a plain-English executive summary to a team channel.

## Architecture (high level)

```
                 ┌────────────────────────────────────────────┐
 user question → │  Streamlit Chat UI (ui/app.py)             │
                 │  always shows the generated SQL            │
                 └──────────────┬─────────────────────────────┘
                                ▼
                 ┌────────────────────────────────────────────┐
                 │  Agent core (core/agent.py)                │
                 │   1. retrieve relevant schema slices       │
                 │      (schema/semantic_layer.py)            │
                 │   2. LLM writes SQL (sql/generator.py)     │
                 │   3. guarded execution (sql/executor.py)   │
                 │   4. self-correction, max 2 repairs        │
                 └──────────────┬─────────────────────────────┘
                                ▼
                 ┌────────────────────────────────────────────┐
                 │  Warehouse — any SQLAlchemy dialect.       │
                 │  Agent reads a schema of sanitised views,  │
                 │  never the base tables.                    │
                 └────────────────────────────────────────────┘

 nightly cron →  reporter/pipeline.py (stats detect the shifts) →
                 reporter/narrator.py (LLM only narrates them) → Slack
```

Every LLM call goes through `core/llm.py`, so the model and provider are one
config change. Schema knowledge lives in YAML under `schema/definitions/`,
never inside a prompt.

### How a query is kept safe

Five layers, outermost first. The first four are application code and hold
only as far as their patterns are correct; the last one is what holds if any
of them has a gap.

| # | Where | What it does |
|---|-------|--------------|
| 1 | `schema/semantic_layer.py` | Credential and PII columns are never rendered into the prompt |
| 2 | `sql/guards.py` → `check()` | Rejects anything that isn't a single `SELECT`/`WITH`, names a denied column, or reaches into another schema |
| 3 | `sql/guards.py` → `strip_sensitive_columns()` | Removes denied columns from the *result set*, which is what catches `SELECT *` — the query text names no column, so step 2 has nothing to match |
| 4 | `sql/executor.py` | Per-connection `SET`: read-only transactions, a statement timeout, and a `search_path` pinned to the view schema. Plus a hard row cap on every query |
| 5 | The database | The views simply do not contain the columns. `scripts/generate_safe_views.py` emits the DDL |

Layer 3 exists because layer 2 cannot see through `SELECT *`, and layer 4's
row-limit wrapper makes every query textually a `SELECT *` anyway. Layer 4's
settings are issued as `SET` after connecting rather than as libpq startup
options — a pooler may silently drop the latter, which would leave the view
layer inert with no error to notice.

### Measuring quality

`validation/evaluator.py` runs both the gold SQL and the generated SQL, then
compares **result sets** — order-, column-name- and numeric-type-insensitive.
Two different queries that return the same answer both count as correct.

Cases in `evals/golden_set.json` carry tags, and accuracy is reported per tag.
An overall figure hides which kind of question is failing: questions that
merely echo column names score high whatever the semantic layer contains, so
the `hard` group is the one that says whether the descriptions earn their cost.

## Repository layout

```
fsq-agent/
├── src/fsq_agent/
│   ├── config.py                 # pydantic-settings; .env is resolved from
│   │                             #   the repo root, not the working directory
│   ├── core/
│   │   ├── agent.py              # orchestration + self-correction loop
│   │   └── llm.py                # provider-agnostic LLM client
│   ├── schema/
│   │   ├── semantic_layer.py     # loads YAML, retrieves relevant slices,
│   │   │                         #   withholds sensitive columns
│   │   └── definitions/          # data dictionary, one YAML per unit
│   │       ├── market_data.yaml
│   │       ├── users.yaml
│   │       ├── alerts.yaml
│   │       └── watchlists.yaml
│   ├── sql/
│   │   ├── generator.py          # system prompt + text-to-SQL + repair
│   │   ├── executor.py           # guarded execution, session settings
│   │   └── guards.py             # SELECT-only, denied columns, schema fence
│   ├── validation/
│   │   └── evaluator.py          # execution accuracy, reported per tag
│   ├── reporter/
│   │   ├── pipeline.py           # nightly stats scan (z-score / % change)
│   │   ├── narrator.py           # LLM turns findings into an exec summary
│   │   └── publisher.py          # Slack webhook, dry-runs to stdout
│   └── ui/
│       └── app.py                # Streamlit chat interface
├── evals/
│   ├── golden_set.json           # (question, gold SQL) pairs, tagged
│   └── results/                  # one snapshot per evaluation run (gitignored)
├── scripts/
│   ├── introspect_schema.py      # generate the YAML data dictionary from a DB
│   ├── generate_safe_views.py    # emit DDL for the sanitised view schema
│   ├── verify_security.py        # prove no path returns sensitive data
│   ├── verify_golden_set.py      # every gold SQL runs and is worth asserting
│   └── run_nightly.py            # entrypoint for the scheduled job
├── tests/                        # offline; no database or network needed
├── docs/
│   └── decisions.md              # architecture decision records (ADR)
├── .env.example
├── pyproject.toml
└── README.md
```

## Sprint mapping

| Sprint | Modules | State |
|--------|---------|-------|
| 1 | `schema/`, `sql/`, `validation/` | Engine, security model and tagged eval set in place |
| 2 | cross-entity joins, smarter retrieval, `ui/app.py` | Self-correction loop works; retrieval is still keyword-based |
| 3 | `reporter/`, `scripts/run_nightly.py`, docs | Not wired to the current schema — `WATCHED_METRICS` still names the old mock tables |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # -e matters: the package must be importable
cp .env.example .env             # add ANTHROPIC_API_KEY and DATABASE_URL
```

Point the agent at a database. It reads a schema of sanitised views rather
than the base tables, so create that first:

```bash
python scripts/generate_safe_views.py -o safe_views.sql   # review it, then run it
# set DB_SCHEMA=fsq_safe in .env
python scripts/introspect_schema.py                       # regenerate the YAML
```

Then check it works and start the UI:

```bash
python scripts/verify_security.py      # no path returns sensitive data
python scripts/verify_golden_set.py    # every gold SQL still runs
pytest                                  # offline, no DB needed
streamlit run src/fsq_agent/ui/app.py
```

Measuring quality:

```bash
python -m fsq_agent.validation.evaluator --sprint 1   # full scope
python -m fsq_agent.validation.evaluator --tag hard   # just the hard group
```

## Development notes

- **Read-only by design, in five places.** See the table above; the load-bearing
  one is the view schema, because it is the only layer that does not depend on
  a pattern being right.
- **Run the evaluator before and after any prompt change**, and compare the
  `hard` group rather than the overall number. Snapshots land in
  `evals/results/` so the two runs can be diffed.
- **The model is not deterministic.** A one-case swing between runs is noise;
  re-run before reading anything into it.
- **New tables and columns are added as YAML**, generated by
  `scripts/introspect_schema.py` and then given business descriptions by hand.
  Never hardcode schema into a prompt.
- **Secrets live in `.env` only.** Credential and PII columns never reach the
  prompt, the result set, or the views.
- **Every generated SQL is shown to the user** alongside the results. Keep it.
