# ruff: noqa: F821, BLE001
"""Unified pre-modeling and pre-test verification gate.

Initializes SQL Runner queries from raw_sql, validates the LookML project,
registers explore queries from inline_queries_json, and checks query parity
against SQL Runner in a single code-mode sandbox invocation.
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


def normalize_val(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    if isinstance(v, str):
        try:
            return round(float(v.strip()), 4)
        except ValueError:
            return v.strip()
    return str(v)


def _norm_row(row):
    return {k.split(".")[-1]: normalize_val(v) for k, v in row.items()}


def compare_row_sets(sql_rows, looker_rows):
    if len(sql_rows) != len(looker_rows):
        return False, [f"Row count mismatch: SQL={len(sql_rows)}, Looker={len(looker_rows)}"]
    mismatches = []
    for idx, (sr, lr) in enumerate(zip(sql_rows, looker_rows)):
        sn, ln = _norm_row(sr), _norm_row(lr)
        if len(sn) != len(ln):
            mismatches.append(f"Row {idx} column count mismatch: SQL={len(sn)}, Looker={len(ln)}")
            continue
        pairs = [(k, sn[k], ln[k]) for k in sn if k in ln] + [
            (f"{sk}->{lk}", sn[sk], ln[lk])
            for sk, lk in zip([k for k in sn if k not in ln], [k for k in ln if k not in sn])
        ]
        for col, sv, lv in pairs:
            if sv != lv:
                mismatches.append(f"Row {idx} ({col}): SQL={sv}, Looker={lv}")
    return not mismatches, mismatches[:5]


def main():
    try:
        raw_data = data_json  # ty: ignore[unresolved-reference]
    except NameError:
        raw_data = {}
    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    try:
        b_url = str(base_url).rstrip("/")  # ty: ignore[unresolved-reference]
    except NameError:
        b_url = ""

    try:
        c_name = str(connection_name).strip()  # ty: ignore[unresolved-reference]
    except NameError:
        c_name = ""

    # 1. Initialize SQL Runner queries from raw_sql if provided
    try:
        sql_input = str(raw_sql).strip()  # ty: ignore[unresolved-reference]
    except NameError:
        sql_input = ""

    if sql_input:
        existing_queries = {q.get("query_index"): q for q in (data.get("queries") or [])}
        created_queries = []
        for idx, stmt in enumerate(split_sql_statements(sql_input)):
            existing = existing_queries.get(idx)
            if existing and existing.get("sql_query_id") and existing.get("sql") == stmt:
                created_queries.append(existing)
            else:
                body = {"sql": stmt}
                if c_name:
                    body["connection_name"] = c_name
                res = create_sql_query(body=body) or {}  # ty: ignore[unresolved-reference]
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
                    "sql": stmt,
                })
        data["queries"] = created_queries

    # 2. Run LookML project validation if requested
    try:
        do_validate = str(validate).lower() in ("true", "1", "yes")  # ty: ignore[unresolved-reference]
    except NameError:
        do_validate = False

    val_errors = []
    p_id = data.get("project_id")
    if do_validate and p_id:
        val = validate_project(project_id=str(p_id)) or {}  # ty: ignore[unresolved-reference]
        val_errors = [
            e for e in (val.get("errors") or []) if e.get("severity", "error") in ("error", "fatal", "")
        ]
        data["validation_errors"] = val_errors

    # 3. Register inline queries and check parity
    try:
        raw_payloads = inline_queries_json  # ty: ignore[unresolved-reference]
    except NameError:
        raw_payloads = {}
    try:
        payloads = (
            json.loads(raw_payloads)
            if isinstance(raw_payloads, str)
            else (raw_payloads or {})
        )
    except (json.JSONDecodeError, TypeError):
        payloads = {}

    all_matched = True
    queries_list = data.get("queries") or []
    for q in queries_list:
        idx = q.get("query_index")
        inline_q = payloads.get(str(idx)) or payloads.get(idx)
        if inline_q:
            q_obj = create_query(body=inline_q) or {}  # ty: ignore[unresolved-reference]
            slug = q_obj.get("slug") or q_obj.get("client_id")
            q["query_id"] = str(q_obj["id"]) if q_obj.get("id") is not None else None
            q["query_slug"] = str(slug) if slug is not None else None
            q["explore_url"] = f"{b_url}/x/{slug}" if (b_url and slug) else (q_obj.get("share_url") or "")
            q["inline_query"] = inline_q

        sql_slug = q.get("sql_query_id")
        active_q = q.get("inline_query")
        if not sql_slug or not (active_q or q.get("query_id")):
            continue
        try:
            if isinstance(q.get("sql_rows"), list):
                s_rows = q["sql_rows"]
            else:
                s_raw = run_sql_query(slug=sql_slug, result_format="json")  # ty: ignore[unresolved-reference]
                s_rows = json.loads(s_raw) if isinstance(s_raw, str) else (s_raw or [])
                if isinstance(s_rows, list) and len(s_rows) <= 50:
                    q["sql_rows"] = s_rows
            l_raw = (
                run_inline_query(result_format="json", body=active_q)  # ty: ignore[unresolved-reference]
                if active_q
                else run_query(query_id=q["query_id"], result_format="json")  # ty: ignore[unresolved-reference]
            )
            l_rows = json.loads(l_raw) if isinstance(l_raw, str) else (l_raw or [])
            matched, mismatches = compare_row_sets(s_rows, l_rows)
            q["parity_status"] = "matched" if matched else "mismatched"
            q["mismatches"] = mismatches
            all_matched = all_matched and matched
        except Exception as e:
            q["parity_status"] = "error"
            q["mismatches"] = [str(e)]
            all_matched = False

    data["passed"] = all_matched and not val_errors
    data["all_queries_matched"] = all_matched
    return data


main()
