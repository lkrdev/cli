# ruff: noqa: F821
"""PR check script: verify that Looker queries produce identical results to SQL Runner queries."""

import json
import sys
from pathlib import Path


def normalize_val(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    if isinstance(v, str):
        s = v.strip()
        try:
            return round(float(s), 4)
        except ValueError:
            return s
    return str(v)


def compare_row_sets(sql_rows, looker_rows):
    if len(sql_rows) != len(looker_rows):
        return False, [f"Row count mismatch: SQL={len(sql_rows)}, Looker={len(looker_rows)}"]

    if not sql_rows and not looker_rows:
        return True, []

    sql_cols = list(sql_rows[0].keys())
    looker_cols = list(looker_rows[0].keys())

    col_mapping = {}
    unmapped_looker = []
    for l_col in looker_cols:
        tail = l_col.split(".")[-1]
        if tail in sql_cols:
            col_mapping[l_col] = tail
        elif l_col in sql_cols:
            col_mapping[l_col] = l_col
        else:
            unmapped_looker.append(l_col)

    if unmapped_looker and len(sql_cols) == len(looker_cols):
        for l_col, s_col in zip(looker_cols, sql_cols, strict=False):
            col_mapping[l_col] = s_col

    mismatches = []
    for r_idx in range(min(len(sql_rows), len(looker_rows))):
        s_row = sql_rows[r_idx]
        l_row = looker_rows[r_idx]
        for l_col, s_col in col_mapping.items():
            s_val = normalize_val(s_row.get(s_col))
            l_val = normalize_val(l_row.get(l_col))
            if s_val != l_val:
                mismatches.append(
                    f"Row {r_idx} [{l_col} -> {s_col}]: SQL={s_val}, Looker={l_val}"
                )
                if len(mismatches) >= 5:
                    return False, mismatches

    return len(mismatches) == 0, mismatches


def main():
    data_path = Path(data_json_path)  # ty: ignore[unresolved-reference]
    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    queries = data.get("queries") or []

    all_passed = True
    report = []

    for q in queries:
        sql_slug = q.get("sql_query_id")
        query_id = q.get("query_id")
        inline_q = q.get("inline_query")

        if not sql_slug:
            continue

        sql_res_raw = run_sql_query(slug=sql_slug, result_format="json")  # ty: ignore[unresolved-reference]
        sql_rows = json.loads(sql_res_raw) if isinstance(sql_res_raw, str) else (sql_res_raw or [])

        if query_id:
            looker_res_raw = run_query(query_id=query_id, result_format="json")  # ty: ignore[unresolved-reference]
        elif inline_q:
            looker_res_raw = run_inline_query(result_format="json", body=inline_q)  # ty: ignore[unresolved-reference]
        else:
            all_passed = False
            report.append({"query_index": q.get("query_index"), "passed": False, "error": "Missing Looker query payload or ID"})
            continue

        looker_rows = json.loads(looker_res_raw) if isinstance(looker_res_raw, str) else (looker_res_raw or [])
        matched, mismatches = compare_row_sets(sql_rows, looker_rows)
        if not matched:
            all_passed = False

        report.append({
            "query_index": q.get("query_index"),
            "passed": matched,
            "sql_runner_url": q.get("sql_runner_url"),
            "explore_url": q.get("explore_url"),
            "mismatches": mismatches,
        })

    result = {"all_passed": all_passed, "report": report}
    print(json.dumps(result, indent=2))
    if not all_passed:
        sys.exit(1)
    return result


try:
    main()
except NameError:
    pass
