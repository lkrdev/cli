# ruff: noqa: F821, BLE001
"""Deprecated: Use pre_gate.py instead.

Register Looker queries (when inline_queries_json is provided) and verify result parity against SQL Runner.
"""

import json


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
        return None
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
        payloads = (
            json.loads(inline_queries_json)  # ty: ignore[unresolved-reference]
            if isinstance(inline_queries_json, str)  # ty: ignore[unresolved-reference]
            else (inline_queries_json or {})  # ty: ignore[unresolved-reference]
        )
    except NameError:
        payloads = {}

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

    all_matched = True
    for q in data.get("queries") or []:
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
