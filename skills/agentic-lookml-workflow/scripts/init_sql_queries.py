# ruff: noqa: F821
"""Deprecated: Use pre_gate.py instead.

Initialize SQL Runner queries for all statements in input.sql and return updated data.json payload.
"""

import json
import re


def split_sql_statements(raw_sql: str) -> list[str]:
    out = []
    last = 0
    pattern = r"""('[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*"|`[^`\\]*(?:\\.[^`\\]*)*`)|(?:--[^\n]*|/\*[\s\S]*?\*/)|;"""
    for m in re.finditer(pattern, raw_sql):
        if m.group(1) is not None:
            out.append(raw_sql[last : m.end()])
        elif m.group(0) == ";":
            out.append(raw_sql[last : m.start()])
            out.append("\0")
        else:
            out.append(raw_sql[last : m.start()])
        last = m.end()
    out.append(raw_sql[last:])
    return [s.strip() for s in "".join(out).split("\0") if s.strip()]


def main():
    try:
        sql_text = str(raw_sql)  # ty: ignore[unresolved-reference]
        b_url = str(base_url).rstrip("/")  # ty: ignore[unresolved-reference]
        c_name = str(connection_name).strip()  # ty: ignore[unresolved-reference]
    except NameError:
        return None
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else (data_json or {})  # ty: ignore[unresolved-reference]
    except NameError:
        data = {}

    created_queries = []
    for idx, stmt in enumerate(split_sql_statements(sql_text)):
        res = create_sql_query(body={"connection_name": c_name, "sql": stmt}) or {}  # ty: ignore[unresolved-reference]
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
