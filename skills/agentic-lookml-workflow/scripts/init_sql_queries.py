# ruff: noqa: F821
"""Initialize SQL Runner queries for all statements in input.sql and return updated data.json payload."""

import json
import re


def split_sql_statements(raw_sql: str) -> list[str]:
    # ponytail: Monty sandbox has no sqlglot; single-pass regex preserves '', "", `` literals while stripping comments and splitting on ;
    tokenized = re.sub(
        r"""('[^']*'|"[^"]*"|`[^`]*`)|(?:--[^\n]*|/\*[\s\S]*?\*/)|;""",
        lambda m: m.group(1) if m.group(1) is not None else ("\0" if m.group(0) == ";" else ""),
        raw_sql,
    )
    return [s.strip() for s in tokenized.split("\0") if s.strip()]


def main():
    try:
        sql_text = str(raw_sql)  # ty: ignore[unresolved-reference]
        b_url = str(base_url).rstrip("/")  # ty: ignore[unresolved-reference]
        m_name = str(model_name)  # ty: ignore[unresolved-reference]
    except NameError:
        return None
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else (data_json or {})  # ty: ignore[unresolved-reference]
    except NameError:
        data = {}

    created_queries = []
    for idx, stmt in enumerate(split_sql_statements(sql_text)):
        res = create_sql_query(body={"model_name": m_name, "sql": stmt}) or {}  # ty: ignore[unresolved-reference]
        slug = res.get("slug") or ""
        created_queries.append({
            "query_index": idx,
            "sql_query_id": slug,
            "sql_runner_url": f"{b_url}/sql/{slug}" if slug else "",
            "query_id": None,
            "query_slug": None,
            "explore_url": None,
            "inline_query": None,
            "parity_status": "pending",
        })

    data["queries"] = created_queries
    return data


main()
