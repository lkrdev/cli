"""PostgreSQL / AlloyDB dialect script for building and searching the _field_value_search PDT."""

from __future__ import annotations

import sys
from pathlib import Path

DIALECT_NAMES = ("postgres", "alloydb", "cloudsql_postgres")


def build_persist_sql(union_select_sql: str, table_ref: str = "${SQL_TABLE_NAME}") -> list[str]:
    return [
        f"CREATE TABLE {table_ref} AS\n{union_select_sql}",
        f"CREATE INDEX IF NOT EXISTS idx_field_value_fts ON {table_ref} USING GIN (to_tsvector('simple', field_value))",
    ]


def build_search_sql(
    search_query: str,
    table_ref: str = "${_field_value_search.SQL_TABLE_NAME}",
    where_extra: str = "",
    limit: int = 25,
) -> str:
    q = search_query.strip().replace("'", "''")
    lim = max(1, int(limit))
    extra = f"\n  AND ({where_extra})" if where_extra else ""
    return (
        f"SELECT\n"
        f"  model_name, explore_name, field_name, subtype, field_value,\n"
        f"  (CASE WHEN LOWER(field_value) = LOWER('{q}') THEN 100.0\n"
        f"        WHEN to_tsvector('simple', field_value) @@ websearch_to_tsquery('simple', '{q}')\n"
        f"          THEN 85.0 + ts_rank(to_tsvector('simple', field_value), websearch_to_tsquery('simple', '{q}')) * 10.0\n"
        f"        ELSE 65.0\n"
        f"   END) AS match_score\n"
        f"FROM {table_ref}\n"
        f"WHERE (to_tsvector('simple', field_value) @@ websearch_to_tsquery('simple', '{q}')\n"
        f"   OR LOWER(field_value) LIKE LOWER('%{q}%')){extra}\n"
        f"ORDER BY match_score DESC, field_value ASC\n"
        f"LIMIT {lim}"
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scratch_search import cli_main

    cli_main(default_dialect="postgres")
