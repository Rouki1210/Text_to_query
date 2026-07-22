"""Generate semantic-layer YAML skeletons from a live database.

The semantic layer is the agent's only map of the warehouse, so every table
it should be able to query needs an entry. Hand-writing that for a real
schema is slow and error-prone — this reads information_schema and emits
one YAML file per business unit, pre-filled with real table/column names,
types, nullability and foreign-key join paths.

The generated `description:` fields are placeholders. Fill them in with
business language: that text is what lets the model map a plain-English
question onto a cryptic column name.

    python scripts/introspect_schema.py                # write to schema/definitions/
    python scripts/introspect_schema.py --dry-run      # print instead
"""

import argparse
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text

from fsq_agent.config import settings

OUT_DIR = Path(__file__).parents[1] / "src" / "fsq_agent" / "schema" / "definitions"

# Where the agent's tables live. When DB_SCHEMA points at sanitised views
# (scripts/generate_safe_views.py) we read the views, so sensitive columns are
# absent by construction rather than filtered out afterwards. Falls back to the
# base schema when no view schema is configured.
#
# auth/storage/realtime/vault are Supabase internals holding credentials — they
# are never read here regardless.
BASE_SCHEMA = "public"
SCHEMA = settings.db_schema or BASE_SCHEMA

# Tables the agent should not see: migration bookkeeping, plus the whole
# community/content side of the product (excluded by request — the agent is
# scoped to market data, users, alerts and watchlists).
EXCLUDE = {
    "__EFMigrationsHistory",
    "Articles",
    "CommunityPosts",
    "Comments",
    "PostReactions",
    "PostTags",
    "PostTopics",
    "Topics",
    "TopicFollows",
    "Bookmarks",
    "communityNotifications",
}

# Business units. Tables not listed here land in "misc" so nothing is
# silently dropped when the schema grows.
UNITS: dict[str, dict] = {
    "market_data": {
        "description": "Crypto assets, their price history, and global market indicators.",
        "keywords": ["price", "asset", "coin", "token", "market", "crypto", "btc", "eth",
                     "dominance", "volume", "market cap", "giá", "thị trường"],
        "tables": ["Assets", "PricePoints", "PriceCaches", "GlobalMetric"],
    },
    "users": {
        "description": "Platform accounts, roles, and follow relationships.",
        "keywords": ["user", "account", "role", "follow", "wallet", "member",
                     "người dùng", "tài khoản"],
        "tables": ["Users", "Roles", "UserRoles", "userFollows", "Nonces"],
    },
    "alerts": {
        "description": "Price-alert rules and the events they trigger, both per-user and global.",
        "keywords": ["alert", "rule", "trigger", "notification", "threshold",
                     "cảnh báo", "thông báo"],
        "tables": ["UserAlerts", "UserAlertHistories", "UserAlertView",
                   "GlobalAlertRules", "GlobalAlertEvents"],
    },
    "watchlists": {
        "description": "User-curated lists of assets being tracked.",
        "keywords": ["watchlist", "tracking", "danh sách theo dõi"],
        "tables": ["Watchlists", "WatchlistItems"],
    },
}


def fetch_columns(conn) -> dict[str, list[dict]]:
    rows = conn.execute(
        text(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = :schema
            ORDER BY table_name, ordinal_position
            """
        ),
        {"schema": SCHEMA},
    ).fetchall()

    tables: dict[str, list[dict]] = defaultdict(list)
    for table, column, dtype, nullable in rows:
        tables[table].append(
            {"name": column, "type": dtype, "nullable": nullable == "YES"}
        )
    return tables


def fetch_foreign_keys(conn) -> dict[str, list[str]]:
    """Return FK join paths per table, as human-readable strings.

    Always read from the base schema: views carry no FK constraints, so
    querying the view schema would silently return nothing and the model would
    lose every join hint. The views keep the base table names, so the
    expressions stay valid either way.
    """
    rows = conn.execute(
        text(
            """
            SELECT tc.table_name, kcu.column_name,
                   ccu.table_name AS ref_table, ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = :schema
            """
        ),
        {"schema": BASE_SCHEMA},
    ).fetchall()

    fks: dict[str, list[str]] = defaultdict(list)
    for table, column, ref_table, ref_column in rows:
        fks[table].append(f'"{table}"."{column}" = "{ref_table}"."{ref_column}"')
    return fks


def render_unit(name: str, spec: dict, columns: dict, fks: dict) -> str:
    lines = [
        f"# Data dictionary for the {name.replace('_', ' ')} unit.",
        "# GENERATED by scripts/introspect_schema.py — descriptions are placeholders.",
        "# Replace every TODO with business language; that text is what the model",
        "# reads to map plain-English questions onto these columns.",
        "",
        "description: >",
        f"  {spec['description']}",
        "",
        "keywords: [" + ", ".join(f'"{k}"' for k in spec["keywords"]) + "]",
        "",
        "tables:",
    ]

    joins: list[str] = []
    for table in spec["tables"]:
        if table not in columns:
            continue
        lines.append(f'  - name: "{table}"')
        lines.append(f"    description: TODO — what one row of {table} represents")
        lines.append("    columns:")
        for col in columns[table]:
            # Never write credentials or PII into the data dictionary; the
            # same denylist is enforced again at render time and at query
            # time (see semantic_layer.py and sql/guards.py).
            if col["name"].lower() in settings.sensitive_column_set:
                continue
            required = str(not col["nullable"]).lower()
            lines.append(
                f'      - {{name: "{col["name"]}", type: "{col["type"]}", '
                f'required: {required}, description: "TODO"}}'
            )
        joins.extend(fks.get(table, []))

    if joins:
        lines.append("")
        lines.append("joins:")
        # Single-quote the whole expression: it starts with a double quote,
        # which YAML would otherwise read as the start of a quoted scalar.
        lines.extend(f"  - '{j}'" for j in sorted(set(joins)))

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 20})
    with engine.connect() as conn:
        columns = fetch_columns(conn)
        fks = fetch_foreign_keys(conn)

    known = {t for spec in UNITS.values() for t in spec["tables"]}
    leftover = sorted(set(columns) - known - EXCLUDE)
    units = dict(UNITS)
    if leftover:
        units["misc"] = {
            "description": "Tables not yet assigned to a business unit.",
            "keywords": ["misc"],
            "tables": leftover,
        }
        print(f"NOTE: {len(leftover)} unassigned table(s) -> misc.yaml: {leftover}")

    for name, spec in units.items():
        content = render_unit(name, spec, columns, fks)
        if args.dry_run:
            print(f"\n{'=' * 20} {name}.yaml {'=' * 20}\n{content}")
        else:
            path = OUT_DIR / f"{name}.yaml"
            path.write_text(content, encoding="utf-8")
            n = sum(1 for t in spec["tables"] if t in columns)
            print(f"wrote {path.name}  ({n} tables)")


if __name__ == "__main__":
    main()
