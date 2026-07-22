"""Semantic layer: the agent's map of the feature store.

Loads YAML data-dictionary files from schema/definitions/ (one per business
unit) and returns only the slices relevant to a given question.

Sprint 1: keyword-based retrieval is enough for 2 business units.
Later: swap `retrieve` for embedding-based retrieval if the schema grows.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from fsq_agent.config import settings

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


def _describe(value: object) -> str:
    """Return a usable description, or "" for an unwritten placeholder.

    The generator seeds every field with TODO so a human can see what still
    needs business language. Those markers are useful in the YAML and pure
    noise in the prompt — a schema with 165 of them tells the model nothing
    while costing tokens on every request. Filter here rather than stripping
    them from the files, so the checklist survives.
    """
    text = str(value or "").strip()
    return "" if not text or text.upper().startswith("TODO") else text


@dataclass
class SemanticLayer:
    units: dict  # {unit_name: parsed YAML dict}

    @classmethod
    def load(cls) -> "SemanticLayer":
        units = {}
        for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
            units[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(units=units)

    def retrieve(self, question: str) -> str:
        """Return a schema description string for the prompt.

        Sprint 1 baseline: score each business unit by keyword overlap with
        the question; include all units that match (cross-entity questions
        will match several). TODO(sprint 2): smarter retrieval + join hints.
        """
        q = question.lower()
        selected = []
        for name, unit in self.units.items():
            keywords = unit.get("keywords", []) + [name]
            if any(kw.lower() in q for kw in keywords):
                selected.append((name, unit))
        if not selected:  # fall back to everything rather than guessing wrong
            selected = list(self.units.items())
        return "\n\n".join(self._render_unit(name, unit) for name, unit in selected)

    @staticmethod
    def _render_unit(name: str, unit: dict) -> str:
        # Credentials and PII are withheld from the prompt: the model cannot
        # ask for a column it was never shown. This is hygiene, not the
        # security boundary — guards.check() is what actually blocks a query
        # that names one anyway (the model can guess common column names).
        denied = settings.sensitive_column_set

        lines = [f"## Business unit: {name}"]
        if unit_desc := _describe(unit.get("description")):
            lines.append(unit_desc)

        for table in unit.get("tables", []):
            # Render identifiers exactly as they must appear in SQL. The
            # warehouse uses PascalCase names, which Postgres folds to
            # lowercase unless double-quoted, so show the quotes here rather
            # than hoping the model adds them.
            table_desc = _describe(table.get("description"))
            lines.append(
                f'\nTable "{table["name"]}"' + (f": {table_desc}" if table_desc else "")
            )
            for col in table.get("columns", []):
                if col["name"].lower() in denied:
                    continue
                col_desc = _describe(col.get("description"))
                lines.append(
                    f'  - "{col["name"]}" ({col["type"]})'
                    + (f": {col_desc}" if col_desc else "")
                )
        joins = unit.get("joins", [])
        if joins:
            lines.append("\nKnown join paths:")
            lines.extend(f"  - {j}" for j in joins)
        return "\n".join(lines)
