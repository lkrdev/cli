# ruff: noqa: F821, BLE001
"""Register Looker queries, verify result parity against SQL Runner, and update data.json."""

import json
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
        return False, [f"Row count mismatch: SQL has {len(sql_rows)}, Looker has {len(looker_rows)}"]

    if not sql_rows and not looker_rows:
        return True, []

    sql_cols = list(sql_rows[0].keys())
    looker_cols = list(looker_rows[0].keys())

    # Map looker columns (often prefixed e.g. 'orders.total_amount') to unqualified sql column names
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
        # Fall back to positional alignment if column count matches
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
                    f"Row {r_idx} mismatch for {l_col} ({s_col}): SQL={s_val}, Looker={l_val}"
                )
                if len(mismatches) >= 5:
                    return False, mismatches

    return len(mismatches) == 0, mismatches


def main():
    data_path = Path(data_json_path)  # ty: ignore[unresolved-reference]
    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    b_url = str(base_url).rstrip("/")  # ty: ignore[unresolved-reference]
    queries = data.get("queries") or []

    # inline_queries_payload can be passed as a JSON string mapping query_index to inline_query dict
    query_payloads = (
        json.loads(inline_queries_json)  # ty: ignore[unresolved-reference]
        if isinstance(inline_queries_json, str)  # ty: ignore[unresolved-reference]
        else inline_queries_json  # ty: ignore[unresolved-reference]
    )

    all_matched = True
    for q_entry in queries:
        idx = q_entry["query_index"]
        idx_key = str(idx)
        if idx_key not in query_payloads and idx not in query_payloads:
            continue

        inline_q = query_payloads.get(idx_key) or query_payloads.get(idx)
        if not inline_q:
            continue

        # Register query in Looker to get query id and explore slug
        q_obj = create_query(body=inline_q) or {}  # ty: ignore[unresolved-reference]
        q_id = q_obj.get("id")
        q_slug = q_obj.get("slug") or q_obj.get("client_id")
        explore_url = f"{b_url}/x/{q_slug}" if q_slug else (q_obj.get("share_url") or "")

        q_entry["query_id"] = str(q_id) if q_id is not None else None
        q_entry["query_slug"] = str(q_slug) if q_slug is not None else None
        q_entry["explore_url"] = explore_url
        q_entry["inline_query"] = inline_q

        # Run comparison between SQL Runner and Looker query
        sql_slug = q_entry.get("sql_query_id")
        if sql_slug:
            try:
                sql_res_raw = run_sql_query(slug=sql_slug, result_format="json")  # ty: ignore[unresolved-reference]
                sql_rows = json.loads(sql_res_raw) if isinstance(sql_res_raw, str) else (sql_res_raw or [])

                looker_res_raw = run_inline_query(result_format="json", body=inline_q)  # ty: ignore[unresolved-reference]
                looker_rows = json.loads(looker_res_raw) if isinstance(looker_res_raw, str) else (looker_res_raw or [])

                matched, mismatches = compare_row_sets(sql_rows, looker_rows)
                q_entry["parity_status"] = "matched" if matched else "mismatched"
                q_entry["mismatches"] = mismatches
                if not matched:
                    all_matched = False
            except Exception as e:
                q_entry["parity_status"] = "error"
                q_entry["mismatches"] = [str(e)]
                all_matched = False

    data["queries"] = queries
    data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"all_matched": all_matched, "queries": queries}


try:
    main()
except NameError:
    pass
