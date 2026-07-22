# Architecture Decision Records

## ADR-001: Custom lightweight orchestration instead of LangChain
- Scope is 3 sprints with a well-defined pipeline (retrieve -> generate -> execute -> repair).
- A framework adds abstraction layers that make prompt debugging harder.
- Revisit if the agent needs multi-step tool use beyond SQL.

## ADR-002: DuckDB mock feature store for development
- Removes dependency on production warehouse access (biggest schedule risk).
- Same SQL surface as the target warehouse via SQLAlchemy; only DATABASE_URL changes.

## ADR-003: Hybrid reporter — statistics detect, LLM narrates
- Anomaly detection is deterministic (z-score + % change thresholds), cheap, auditable.
- The LLM only rewrites validated findings into plain English, so it cannot
  hallucinate numbers.

## ADR-004: Execution accuracy as the primary quality metric
- Comparing executed result sets (order/name-insensitive) instead of SQL strings,
  because semantically equivalent queries can differ textually.

## ADR-005: Sanitised views as the control for credential/PII columns
Context: the guard blocked writes, not reads. A generated `SELECT * FROM "Nonces"`
returned real wallet addresses and auth nonces, because the query text names no
column for a deny-list to match on. Withholding columns from the prompt does not
help — the model does not need to be told a users table has a password column.

Decision: five layers, outermost first.
1. Sensitive columns are withheld from the prompt (`semantic_layer._render_unit`).
2. `guards.check()` rejects queries naming a denied column, and rejects any
   schema-qualified name — `public."Users"` would otherwise sidestep layer 5.
3. `guards.strip_sensitive_columns()` removes denied columns from result sets,
   which is the only place `SELECT *` can be caught: `with_row_limit()` wraps
   every query as `SELECT * FROM (...)`, so the SQL text always contains a `*`.
4. The UI names what was withheld rather than quietly showing a narrower table.
5. The agent's connection is pinned to a schema of views that do not contain the
   columns (`scripts/generate_safe_views.py`, `DB_SCHEMA`).

Alternative considered: a dedicated role with column-level `GRANT SELECT`. It is
strictly stronger — the database refuses, so no application pattern has to be
right — and is available here (`postgres` has `rolcreaterole`). Deferred because
views need no new credential and no change to the 30 golden-set queries, which
keep working unchanged since the views reuse the base table names.

Residual risk, accepted: `search_path` is name resolution, not access control,
and the agent still connects as `postgres`. Layer 2's schema-qualification check
is what closes that gap, and it is a regex — so it carries regex-shaped risk.
Moving to a restricted role removes the dependency on layer 2 entirely and is
the natural follow-up before this ever faces untrusted users.

Chosen behaviour on a blocked result: drop the columns and warn, rather than
raising. Raising would send the repair loop an extra LLM round-trip to rewrite
`SELECT *` into explicit columns; the trade-off accepted is that such a query
still counts as a pass in the evaluator.
