"""DuckDB dialect script for building and searching the _field_value_search PDT."""

from __future__ import annotations

import sys
from pathlib import Path

DIALECT_NAMES = ("duckdb",)


def build_persist_sql(union_select_sql: str, table_ref: str = "${SQL_TABLE_NAME}") -> list[str]:
    return [
        f"CREATE OR REPLACE TABLE {table_ref} AS\n{union_select_sql}",
        f"PRAGMA create_fts_index('{table_ref}', 'field_value', 'field_value', overwrite=1)",
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
        f"  ROUND(\n"
        f"    CASE WHEN LOWER(field_value) = LOWER('{q}') THEN 100.0\n"
        f"         WHEN CONTAINS(LOWER(field_value), LOWER('{q}')) THEN 85.0\n"
        f"         ELSE jaro_winkler_similarity(LOWER(field_value), LOWER('{q}')) * 100.0\n"
        f"    END, 2\n"
        f"  ) AS match_score\n"
        f"FROM {table_ref}\n"
        f"WHERE (CONTAINS(LOWER(field_value), LOWER('{q}'))\n"
        f"   OR jaro_winkler_similarity(LOWER(field_value), LOWER('{q}')) >= 0.80\n"
        f"   OR levenshtein(LOWER(field_value), LOWER('{q}')) <= 2){extra}\n"
        f"ORDER BY match_score DESC, field_value ASC\n"
        f"LIMIT {lim}"
    )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scratch_search import cli_main

    cli_main(default_dialect="duckdb")
