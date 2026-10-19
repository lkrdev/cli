# ruff: noqa: F821
"""Initialize SQL Runner queries for all statements in input.sql and record them in data.json."""

import json
from pathlib import Path


def split_sql_statements(raw_sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    length = len(raw_sql)

    while i < length:
        ch = raw_sql[i]
        nxt = raw_sql[i + 1] if i + 1 < length else ""

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(ch)
            if ch == "*" and nxt == "/":
                current.append("/")
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if not in_single_quote and not in_double_quote:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                current.append("--")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                current.append("/*")
                i += 2
                continue

        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single_quote and not in_double_quote:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    last = "".join(current).strip()
    if last:
        statements.append(last)

    return statements


def main():
    sql_path = Path(sql_file)  # ty: ignore[unresolved-reference]
    data_path = Path(data_json_path)  # ty: ignore[unresolved-reference]
    b_url = str(base_url).rstrip("/")  # ty: ignore[unresolved-reference]
    m_name = str(model_name)  # ty: ignore[unresolved-reference]

    raw_sql = sql_path.read_text(encoding="utf-8")
    statements = split_sql_statements(raw_sql)

    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}

    created_queries = []
    for idx, stmt in enumerate(statements):
        res = create_sql_query(body={"model_name": m_name, "sql": stmt}) or {}  # ty: ignore[unresolved-reference]
        sql_slug = res.get("slug") or ""
        sql_runner_url = f"{b_url}/sql/{sql_slug}" if sql_slug else ""

        entry = {
            "query_index": idx,
            "sql_query_id": sql_slug,
            "sql_runner_url": sql_runner_url,
            "query_id": None,
            "query_slug": None,
            "explore_url": None,
            "inline_query": None,
            "parity_status": "pending",
        }
        created_queries.append(entry)

    data["queries"] = created_queries
    data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"queries_count": len(created_queries), "queries": created_queries}


try:
    main()
except NameError:
    pass
