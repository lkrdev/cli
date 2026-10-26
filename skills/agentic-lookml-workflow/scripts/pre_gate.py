# ruff: noqa: F821, BLE001
"""Unified pre-modeling and pre-test verification gate.

Initializes SQL Runner queries from raw_sql, validates the LookML project,
registers explore queries from inline_queries_json, checks query parity
against SQL Runner, and optionally executes test_queries_json baseline
slices in a single code-mode sandbox invocation.
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


def _to_float(v):
    if v is not None and not isinstance(v, bool):
        if isinstance(v, str) and re.match(r"^0\d+$", v.strip()):
            return None
        try:
            return float(v.strip() if isinstance(v, str) else v)
        except (ValueError, TypeError):
            pass
    return None


def normalize_val(v, digits=4):
    if v is None or isinstance(v, bool):
        return v
    f = _to_float(v)
    return round(f, digits) if f is not None else (v.strip() if isinstance(v, str) else str(v))


# ponytail: paren scan for Monty sandbox (no sqlglot); pass AST metadata from lkr parse sql if expressions wrap ROUND
def _sql_meta(sql: str):
    scales: dict[str, int] = {}
    pct_cols: set[str] = set()
    pct_idxs: set[int] = set()
    clean = re.sub(r"--[^\n]*|/\*[\s\S]*?\*/", " ", re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", sql or ""))
    for m in re.finditer(r"(?i)\bROUND\s*\(", clean):
        depth, comma, i = 1, -1, m.end()
        while i < len(clean) and depth:
            if clean[i] == "(":
                depth += 1
            elif clean[i] == ")":
                depth -= 1
            elif clean[i] == "," and depth == 1:
                comma = i if comma < 0 else -2
            i += 1
        if depth or comma == -2:
            continue
        arg2 = clean[comma + 1 : i - 1].strip() if comma > 0 else "0"
        am = re.match(
            r'^\s*(?:(?i:AS)\s+)?(?:`([^`]+)`|"([^"]+)"|([A-Za-z_]\w*))\s*(?:,|\)|;|$|(?i:FROM|WHERE|GROUP|ORDER|LIMIT|HAVING|QUALIFY|UNION)\b)',
            clean[i:],
        )
        alias = am and (am.group(1) or am.group(2) or am.group(3))
        if alias and re.match(r"^[+-]?\d+$", arg2) and alias.upper() not in {"FROM", "ASC", "DESC"}:
            scales[alias.lower()] = int(arg2)

    depth = 0
    top_chars = []
    for ch in clean:
        if ch == "(":
            depth += 1
            top_chars.append(" ")
        elif ch == ")":
            depth = max(0, depth - 1)
            top_chars.append(" ")
        else:
            top_chars.append(ch if depth == 0 else " ")
    top = "".join(top_chars)
    sm = re.search(
        r"(?i)\bSELECT\b([\s\S]*?)(?:\b(?:FROM|WHERE|GROUP|ORDER|LIMIT|HAVING|QUALIFY|UNION)\b|;|$)", top
    )
    sel_exprs: list[str] = []
    if sm:
        base, pos = sm.start(1), 0
        for p_idx, seg in enumerate(sm.group(1).split(",")):
            expr = clean[base + pos : base + pos + len(seg)]
            pos += len(seg) + 1
            sel_exprs.append(
                re.sub(
                    r"\s+",
                    "",
                    re.sub(
                        r'(?i)(?:\s+AS\s+|(?<![+\-*/=<>,(])\s+|\)\s*)(?!\b(?:END|NULL|TRUE|FALSE|AND|OR|ELSE|THEN)\b)(?:`[^`]+`|"[^"]+"|[A-Za-z_]\w*)\s*$',
                        "",
                        expr.strip(),
                    ),
                ).lower()
            )
            if re.search(r"(?:\*\s*100(?:\.0*)?(?!\d|\.)|(?<!\d|\.)100(?:\.0*)?\s*\*)", expr):
                pct_idxs.add(p_idx)
                am = re.search(
                    r'(?:(?i:\bAS)\s+|(?<![+\-*/=<>,(])\s+|\)\s*)(?:`([^`]+)`|"([^"]+)"|([A-Za-z_]\w*))\s*$',
                    expr.strip(),
                )
                alias = am and (am.group(1) or am.group(2) or am.group(3))
                if alias and alias.upper() not in {"END", "NULL", "TRUE", "FALSE", "AND", "OR", "ELSE", "THEN"}:
                    pct_cols.add(alias.lower())
    om = re.search(r"(?i)\bORDER\s+BY\b([\s\S]*?)(?:\b(?:LIMIT|OFFSET|FETCH)\b|;|$)", top)
    order_specs: list[str] = []
    if om:
        ob_base, ob_pos = om.start(1), 0
        for seg in om.group(1).split(","):
            raw_ob = clean[ob_base + ob_pos : ob_base + ob_pos + len(seg)]
            ob_pos += len(seg) + 1
            spec = re.sub(
                r"(?i)(?:\s+(?:ASC|DESC))?(?:\s+NULLS\s+(?:FIRST|LAST))?\s*$", "", raw_ob.strip()
            ).strip()
            if spec:
                order_specs.append(spec)
    lm = re.search(r"(?i)\bLIMIT\s+(\d+)\b", top)
    return scales, pct_cols, pct_idxs, sel_exprs, bool(om), order_specs, (int(lm.group(1)) if lm else None)


def _parse_ts(v):
    if not isinstance(v, str):
        return None
    m = re.match(
        r"(?i)^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:\s*UTC|Z|[+-]00(?::?00)?)?$",
        v.strip(),
    )
    return (f"{m.group(1)} {m.group(2)}", (m.group(3) or "")[:6].rstrip("0")) if m else None


def _norm_ts(v, ts_mode: str | None):
    tp = _parse_ts(v) if ts_mode else None
    return (tp[0] if ts_mode == "sec" or not tp[1] else f"{tp[0]}.{tp[1]}") if tp else v


def _cell_key(v, digits: int, mult: float = 1.0, ts_mode: str | None = None):
    v = _norm_ts(v, ts_mode)
    f = _to_float(v)
    nv = round(f * mult, digits) if f is not None else normalize_val(v, digits)
    if nv is None or isinstance(nv, bool):
        return (0 if nv is None else 1, float(nv or 0), "")
    return (2, float(nv), "") if isinstance(nv, (int, float)) else (3, 0.0, str(nv))


def _cmp_pair(rs, rl, digits: int, mult: float, ts_mode: str | None = None):
    rs, rl = _norm_ts(rs, ts_mode), _norm_ts(rl, ts_mode)
    if (
        isinstance(rs, str)
        and isinstance(rl, str)
        and re.match(r"^\d+$", rs.strip())
        and re.match(r"^\d+$", rl.strip())
    ):
        return rs.strip(), rl.strip()
    sv, lv = normalize_val(rs, digits), normalize_val(rl, digits)
    lf = _to_float(rl)
    return sv, (round(lf * mult, digits) if (mult != 1.0 and lf is not None) else lv)


def _drop_grain_keys(sql_rows, looker_rows, f_norm: list[str]) -> set[str]:
    if not sql_rows or not looker_rows:
        return set()
    s_set = {k.split(".")[-1].lower() for k in sql_rows[0]}
    l_keys = [k.lower() for k in looker_rows[0]]
    drop = {k for k in l_keys if (k == "no_group" or k.endswith(".no_group")) and "no_group" not in s_set}
    if len(l_keys) - len(drop) == len(s_set) + 1 and len(f_norm) > len(s_set):
        tail, leaf = f_norm[len(s_set)], f_norm[len(s_set)].split(".")[-1]
        if leaf not in s_set and (leaf in ("id", "pk") or leaf.endswith("_id")):
            drop.add(tail)
    return drop


def compare_row_sets(
    sql_rows,
    looker_rows,
    sql: str = "",
    looker_fields: list[str] | None = None,
    fetch_extra=None,
):
    if len(sql_rows) != len(looker_rows):
        return False, [f"Row count mismatch: SQL={len(sql_rows)}, Looker={len(looker_rows)}"]
    if not sql_rows:
        return True, []
    scales, pct_cols, pct_idxs, sel_exprs, has_order_by, order_specs, limit_n = _sql_meta(sql)
    f_norm = [f.lower() for f in (looker_fields or [])]
    drop_l = _drop_grain_keys(sql_rows, looker_rows, f_norm)

    def _norm_lr(lr):
        raw_lr = {k.lower(): v for k, v in lr.items() if k.lower() not in drop_l}
        return {k: raw_lr[k] for k in [k for k in f_norm if k in raw_lr] + list(raw_lr)}

    sr_leaves = [{k.split(".")[-1].lower(): v for k, v in sr.items()} for sr in sql_rows]
    lr_leaves = [_norm_lr(lr) for lr in looker_rows]
    bad_cols = [
        f"Row {i} column count mismatch: SQL={len(sr)}, Looker={len(lr)}"
        for i, (sr, lr) in enumerate(zip(sr_leaves, lr_leaves))
        if len(sr) != len(lr)
    ]
    if bad_cols:
        return False, bad_cols[:5]
    s_keys, l_keys = list(sr_leaves[0]), list(lr_leaves[0])
    l_by_leaf: dict[str, list[str]] = {}
    for lk in l_keys:
        l_by_leaf.setdefault(lk.split(".")[-1], []).append(lk)
    s_to_l = {
        sk: (sk if sk in lr_leaves[0] else l_by_leaf[sk][0])
        for sk in s_keys
        if sk in lr_leaves[0] or len(l_by_leaf.get(sk, ())) == 1
    }
    used_l = set(s_to_l.values())
    s_to_l.update(dict(zip([k for k in s_keys if k not in s_to_l], [k for k in l_keys if k not in used_l])))
    cols = []
    for c_idx, sk in enumerate(s_keys):
        lk = s_to_l[sk]
        digits = scales.get(sk, 4)
        mult = 1.0
        if sk in pct_cols or c_idx in pct_idxs:
            s_abs = sum(abs(f) for r in sr_leaves for f in [_to_float(r.get(sk))] if f is not None)
            l_abs = sum(abs(f) for r in lr_leaves for f in [_to_float(r.get(lk))] if f is not None)
            if l_abs > 0 and abs(s_abs - l_abs * 100.0) < abs(s_abs - l_abs):
                mult = 100.0
        s_ts = [_parse_ts(r.get(sk)) for r in sr_leaves if r.get(sk) is not None]
        l_ts = [_parse_ts(r.get(lk)) for r in lr_leaves if r.get(lk) is not None]
        is_ts = bool(s_ts and l_ts) and all(x is not None for x in s_ts + l_ts)
        ts_mode = ("sec" if not any(x[1] for x in l_ts if x) else "sub") if is_ts else None
        same_leaf = lk == sk or (lk.split(".")[-1] == sk and len(l_by_leaf.get(sk, ())) == 1)
        cols.append((sk if same_leaf else f"{sk}->{lk}", sk, lk, digits, mult, ts_mode))
    order_idxs: list[int] = []
    s_ob = None
    tied_ob = False
    if len(sr_leaves) > 1 and not has_order_by:
        sr_leaves.sort(key=lambda r: tuple(_cell_key(r[sk], d, 1.0, tm) for _, sk, _, d, _, tm in cols))
        lr_leaves.sort(key=lambda r: tuple(_cell_key(r[lk], d, m, tm) for _, _, lk, d, m, tm in cols))
    elif order_specs:
        for spec in order_specs:
            ident, norm_ob = spec.strip('`"').lower(), re.sub(r"\s+", "", spec).lower()
            leaf_hits = [i for i, sk in enumerate(s_keys) if sk == ident.split(".")[-1]]
            idx = (
                int(spec) - 1
                if spec.isdigit() and 1 <= int(spec) <= len(cols)
                else s_keys.index(ident)
                if ident in s_keys
                else sel_exprs.index(norm_ob)
                if norm_ob in sel_exprs
                else leaf_hits[0]
                if len(leaf_hits) == 1
                else -1
            )
            if idx >= 0:
                order_idxs.append(idx)
        if len(order_idxs) == len(order_specs):
            s_ob = [tuple(_cell_key(r[cols[i][1]], cols[i][3], 1.0, cols[i][5]) for i in order_idxs) for r in sr_leaves]
            l_ob = [tuple(_cell_key(r[cols[i][2]], cols[i][3], cols[i][4], cols[i][5]) for i in order_idxs) for r in lr_leaves]
            if s_ob == l_ob:
                tied_ob = True
                if len(sr_leaves) > 1:
                    sr_tied, lr_tied, start = [], [], 0
                    while start < len(sr_leaves):
                        end = start + 1
                        while end < len(sr_leaves) and s_ob[end] == s_ob[start]:
                            end += 1
                        sr_tied.extend(
                            sorted(
                                sr_leaves[start:end],
                                key=lambda r: tuple(_cell_key(r[sk], d, 1.0, tm) for _, sk, _, d, _, tm in cols),
                            )
                        )
                        lr_tied.extend(
                            sorted(
                                lr_leaves[start:end],
                                key=lambda r: tuple(_cell_key(r[lk], d, m, tm) for _, _, lk, d, m, tm in cols),
                            )
                        )
                        start = end
                    sr_leaves, lr_leaves = sr_tied, lr_tied
    mismatches = []
    bad_idxs = []
    for idx, (sr_leaf, lr_leaf) in enumerate(zip(sr_leaves, lr_leaves)):
        row_bad = False
        for label, sk, lk, digits, mult, tm in cols:
            sv, lv_cmp = _cmp_pair(sr_leaf[sk], lr_leaf[lk], digits, mult, tm)
            if sv != lv_cmp:
                mismatches.append(f"Row {idx} ({label}): SQL={sv}, Looker={lv_cmp}")
                row_bad = True
        if row_bad:
            bad_idxs.append(idx)
    if mismatches and fetch_extra is not None and tied_ob and s_ob and limit_n == len(sr_leaves) < 500:
        last_key = s_ob[-1]
        last_start = len(s_ob) - 1
        while last_start > 0 and s_ob[last_start - 1] == last_key:
            last_start -= 1
        if bad_idxs[0] >= last_start:
            try:
                extra_rows = fetch_extra(500) or []
            except Exception:
                extra_rows = []
            pool = [
                norm_lr
                for lr in extra_rows
                for norm_lr in [_norm_lr(lr)]
                if len(norm_lr) == len(sr_leaves[0])
                and all(lk in norm_lr for _, _, lk, _, _, _ in cols)
                and tuple(_cell_key(norm_lr[cols[i][2]], cols[i][3], cols[i][4], cols[i][5]) for i in order_idxs) == last_key
            ]
            all_found = True
            for sr_leaf in sr_leaves[last_start:]:
                hit_i = -1
                for p_i, cand_lr in enumerate(pool):
                    if all(
                        pair[0] == pair[1]
                        for _, sk, lk, d, m, tm in cols
                        for pair in [_cmp_pair(sr_leaf[sk], cand_lr[lk], d, m, tm)]
                    ):
                        hit_i = p_i
                        break
                if hit_i < 0:
                    all_found = False
                    break
                pool.pop(hit_i)
            if all_found:
                return True, []
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
    c_name = c_name or str(data.get("connection_name") or "").strip()

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
            raw_df = active_q.get("dynamic_fields") if isinstance(active_q, dict) else None
            dfs = (
                json.loads(raw_df)
                if isinstance(raw_df, str) and raw_df.strip().startswith("[")
                else (raw_df if isinstance(raw_df, list) else [])
            )
            q_fields = [str(f) for f in ((active_q.get("fields") if isinstance(active_q, dict) else None) or [])] + [
                str(d.get("table_calculation") or d.get("measure") or d.get("dimension"))
                for d in dfs
                if isinstance(d, dict) and (d.get("table_calculation") or d.get("measure") or d.get("dimension"))
            ]
            def _fetch_tie_pool(new_lim: int, _q=active_q):
                ext_q = dict(_q)
                ext_q["limit"] = str(new_lim)
                ext_raw = run_inline_query(result_format="json", body=ext_q)  # ty: ignore[unresolved-reference]
                ext_parsed = json.loads(ext_raw) if isinstance(ext_raw, str) else (ext_raw or [])
                return ext_parsed if isinstance(ext_parsed, list) else []

            stmt_sql = str(q.get("sql") or "")
            matched, mismatches = compare_row_sets(
                s_rows,
                l_rows,
                sql=stmt_sql,
                looker_fields=q_fields,
                fetch_extra=_fetch_tie_pool if isinstance(active_q, dict) else None,
            )
            if not matched and isinstance(active_q, dict) and s_rows and len(s_rows) == len(l_rows):
                _, _, _, _, has_ob, _, _ = _sql_meta(stmt_sql)
                clean_sql = re.sub(r"(?:\s|--[^\n]*|/\*[\s\S]*?\*/|;)+$", "", stmt_sql)
                lim_match = re.search(r"(?i)\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\s*$", clean_sql)
                if not has_ob and lim_match:
                    lim_n = int(lim_match.group(1))
                    no_lim = clean_sql[: lim_match.start()].rstrip()
                    ord_cols = ", ".join(str(i) for i in range(1, len(s_rows[0]) + 1))
                    det_sql = f"SELECT * FROM (\n{no_lim}\n) AS _lkr_det ORDER BY {ord_cols} LIMIT {lim_n}"
                    det_body = {"sql": det_sql, **({"connection_name": c_name} if c_name else {})}
                    det_slug = (create_sql_query(body=det_body) or {}).get("slug")  # ty: ignore[unresolved-reference]
                    if det_slug:
                        drop_k = _drop_grain_keys(s_rows, l_rows, [f.lower() for f in q_fields])
                        sort_f = [f for f in q_fields if f.lower() not in drop_k][: len(s_rows[0])]
                        det_q = {**active_q, "sorts": [f"{f} asc" for f in sort_f]}
                        ds = run_sql_query(slug=det_slug, result_format="json")  # ty: ignore[unresolved-reference]
                        dl = run_inline_query(result_format="json", body=det_q)  # ty: ignore[unresolved-reference]
                        matched, mismatches = compare_row_sets(
                            json.loads(ds) if isinstance(ds, str) else (ds or []),
                            json.loads(dl) if isinstance(dl, str) else (dl or []),
                            sql=f"{no_lim} ORDER BY {ord_cols} LIMIT {lim_n}",
                            looker_fields=q_fields,
                            fetch_extra=lambda new_lim, _dq=det_q: _fetch_tie_pool(new_lim, _dq),
                        )
            q["parity_status"] = "matched" if matched else "mismatched"
            q["mismatches"] = mismatches
            all_matched = all_matched and matched
        except Exception as e:
            q["parity_status"] = "error"
            q["mismatches"] = [str(e)]
            all_matched = False

    if not b_url:
        for q in queries_list:
            m_host = re.match(r"^(https?://[^/]+)", str(q.get("explore_url") or q.get("sql_runner_url") or ""))
            if m_host:
                b_url = m_host.group(1)
                break
    if b_url:
        for q in queries_list:
            if q.get("sql_query_id") and not str(q.get("sql_runner_url") or "").startswith("http"):
                q["sql_runner_url"] = f"{b_url}/sql/{q['sql_query_id']}"
            if q.get("query_slug") and not str(q.get("explore_url") or "").startswith("http"):
                q["explore_url"] = f"{b_url}/x/{q['query_slug']}"

    # 4. Run optional test-slice baseline queries (raw unformatted JSON for .test.lkml assertions)
    try:
        raw_tq = test_queries_json  # ty: ignore[unresolved-reference]
    except NameError:
        raw_tq = {}
    try:
        parsed_tq = json.loads(raw_tq) if isinstance(raw_tq, str) else (raw_tq or {})
    except (json.JSONDecodeError, TypeError):
        parsed_tq = {}

    test_queries = (
        {str(k): v for k, v in parsed_tq.items() if isinstance(v, dict)}
        if isinstance(parsed_tq, dict)
        else {}
    )

    if test_queries and not val_errors:
        test_results = {}
        for t_key, t_body in test_queries.items():
            try:
                t_raw = run_inline_query(result_format="json", body=t_body)  # ty: ignore[unresolved-reference]
                test_results[t_key] = json.loads(t_raw) if isinstance(t_raw, str) else (t_raw or [])
            except Exception as e:
                test_results[t_key] = {"error": str(e)}
        data["test_query_results"] = test_results

    data["passed"] = all_matched and not val_errors
    data["all_queries_matched"] = all_matched
    return data


main()
