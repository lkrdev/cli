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


def _pin_temporal_sql(sql_text: str, run_id: str = "") -> tuple[str, bool]:
    rm = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", str(run_id or ""))
    ymd = f"{rm.group(1)}-{rm.group(2)}-{rm.group(3)}" if rm else "2026-01-01"
    hms = f"{rm.group(4)}:{rm.group(5)}:{rm.group(6)}" if rm else "00:00:00"
    ts_lit = f"CAST('{ymd} {hms}+00:00' AS TIMESTAMP)"
    pat = (
        r"""(?is)('[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*"|`[^`\\]*(?:\\.[^`\\]*)*`|--[^\n]*|/\*[\s\S]*?\*/|\bAS\s+\w+|\.\s*\w+)"""
        r"""|\b(CURRENT_TIMESTAMP|CURRENT_DATETIME|CURRENT_DATE|CURRENT_TIME)\b(?:\s*\(\s*([^()]*?)\s*\))?"""
        r"""|\b(NOW)\s*\(\s*\d*\s*\)"""
    )
    out, last, pinned = [], 0, False
    for m in re.finditer(pat, sql_text or ""):
        if m.group(1) is not None:
            continue
        out.append(sql_text[last : m.start()])
        fn = (m.group(2) or m.group(4) or "").upper()
        arg = (m.group(3) or "").strip()
        kind = {"CURRENT_DATETIME": ("DATETIME", f"{ymd} {hms}"), "CURRENT_TIME": ("TIME", hms)}.get(
            fn, ("DATE", ymd)
        )
        out.append(
            ts_lit
            if fn in ("CURRENT_TIMESTAMP", "NOW")
            else (f"{kind[0]}({ts_lit}, {arg})" if (arg and not arg.isdigit()) else f"CAST('{kind[1]}' AS {kind[0]})")
        )
        last, pinned = m.end(), True
    return ("".join([*out, sql_text[last:]]), True) if pinned else (sql_text, False)


def _fp(s: str) -> str:
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFFFFFFFFFF
    return f"{h:x}"


def _remap_compiled_rows(rows, q_fields: list[str]):
    alias_map = {re.sub(r"[^a-z0-9_]", "_", f.lower()): f for f in q_fields}
    return [
        {
            alias_map.get(kl, k): v
            for k, v in r.items()
            for kl in [k.lower()]
            if not (kl.endswith("__sort_") and kl not in alias_map)
        }
        for r in (rows or [])
        if isinstance(r, dict)
    ]


def _to_float(v):
    if v is not None and not isinstance(v, bool):
        if isinstance(v, str) and re.match(r"^0\d+$", v.strip()):
            return None
        try:
            return float(v.strip() if isinstance(v, str) else v)
        except (ValueError, TypeError):
            pass
    return None


def _sql_round(f: float, digits: int = 4) -> float:
    if f - f != 0:
        return f
    p = 10.0**digits
    return round((int(abs(f) * p + 0.5 + 1e-12) / p) * (-1.0 if f < 0 else 1.0), digits)


def normalize_val(v, digits=4):
    if v is None or isinstance(v, bool):
        return v
    f = _to_float(v)
    return _sql_round(f, digits) if f is not None else (v.strip() if isinstance(v, str) else str(v))


# ponytail: paren scan for Monty sandbox (no sqlglot); pass AST metadata from lkr parse sql if expressions wrap ROUND
def _sql_meta(sql: str):
    scales: dict[str, int] = {}
    pct_cols: set[str] = set()
    pct_idxs: set[int] = set()
    pct_re = r"(?:\*\s*100(?:\.0*)?(?!\d|\.)|(?<!\d|\.)100(?:\.0*)?\s*\*)"
    alias_re = r'(?:(?i:\bAS)\s+|(?<![+\-*/=<>,(])\s+|(?<=\))\s*)(?:`([^`]+)`|"([^"]+)"|([A-Za-z_]\w*))\s*$'
    kw_skip = {"END", "NULL", "TRUE", "FALSE", "AND", "OR", "ELSE", "THEN", "FROM", "ASC", "DESC"}
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
        if alias and re.match(r"^[+-]?\d+$", arg2) and alias.upper() not in kw_skip:
            scales[alias.lower()] = int(arg2)

    depth = 0
    depths: list[int] = []
    top_chars = []
    for ch in clean:
        depths.append(depth)
        if ch == "(":
            depth += 1
            top_chars.append(" ")
        elif ch == ")":
            depth = max(0, depth - 1)
            top_chars.append(" ")
        else:
            top_chars.append(ch if depth == 0 else " ")
    top = "".join(top_chars)
    sel_exprs: list[str] = []
    end_kw = r"(?i)^(?:FROM|WHERE|GROUP|ORDER|LIMIT|HAVING|QUALIFY|UNION)\b"
    for sm in re.finditer(r"(?i)\bSELECT\b", clean):
        base_d, i, seg_start, segs = depths[sm.start()], sm.end(), sm.end(), []
        while i < len(clean):
            ch, d_i = clean[i], depths[i]
            if d_i == base_d and (
                ch in ");" or (ch.isalpha() and not (i and (clean[i - 1].isalnum() or clean[i - 1] == "_")) and re.match(end_kw, clean[i:]))
            ):
                break
            if ch == "," and d_i == base_d:
                segs.append(clean[seg_start:i])
                seg_start = i + 1
            i += 1
        segs.append(clean[seg_start:i])
        first_top = base_d == 0 and not sel_exprs
        for p_idx, expr in enumerate(segs):
            raw_e = re.sub(r"(?i)^(?:DISTINCT|ALL)\s+", "", expr.strip()) if p_idx == 0 else expr.strip()
            am = re.search(alias_re, raw_e)
            alias = am and (am.group(1) or am.group(2) or am.group(3))
            al = alias.lower() if alias and alias.upper() not in kw_skip else None
            core = re.sub(r"\s+", "", raw_e[: am.start()] if (am and al) else raw_e).lower()
            if first_top:
                sel_exprs.append(core)
            src_col = core.split(".")[-1] if re.match(r"^[a-z_]\w*(?:\.[a-z_]\w*)?$", core) else ""
            if al and src_col in scales and al not in scales:
                scales[al] = scales[src_col]
            if re.search(pct_re, raw_e) or src_col in pct_cols:
                if base_d == 0:
                    pct_idxs.add(p_idx)
                if al:
                    pct_cols.add(al)
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
    if ts_mode == "bool":
        return {"true": True, "yes": True, "false": False, "no": False}.get(v.strip().lower(), v) if isinstance(v, str) else v
    tp = _parse_ts(v) if ts_mode else None
    return (tp[0] if ts_mode == "sec" or not tp[1] else f"{tp[0]}.{tp[1]}") if tp else v


def _cell_key(v, digits: int, mult: float = 1.0, ts_mode: str | None = None):
    v = _norm_ts(v, ts_mode)
    f = _to_float(v)
    nv = _sql_round(f * mult, digits) if f is not None else normalize_val(v, digits)
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
    return sv, (_sql_round(lf * mult, digits) if (mult != 1.0 and lf is not None) else lv)


def _drop_grain_keys(sql_rows, looker_rows, f_norm: list[str], dfs: list | None = None) -> set[str]:
    if not sql_rows or not looker_rows:
        return set()
    s_set = {k.split(".")[-1].lower() for k in sql_rows[0]}
    l_keys = [k.lower() for k in looker_rows[0]]
    drop = {k for k in l_keys if (k == "no_group" or k.endswith(".no_group")) and "no_group" not in s_set}
    if len(l_keys) - len(drop) == len(s_set) + 1 and len(f_norm) > len(s_set):
        tail, leaf = f_norm[len(s_set)], f_norm[len(s_set)].split(".")[-1]
        if leaf not in s_set and (leaf in ("id", "pk") or leaf.endswith("_id")):
            drop.add(tail)
    tcs = [d for d in (dfs or []) if isinstance(d, dict) and d.get("table_calculation")]
    if tcs and len(l_keys) - len(drop) > len(s_set):
        tc_names = {str(d["table_calculation"]).lower() for d in tcs}
        tc_refs = {r.lower() for d in tcs for r in re.findall(r"\$\{(\w+\.\w+)\}", str(d.get("expression") or ""))}
        for k in l_keys:
            if len(l_keys) - len(drop) > len(s_set) and k in tc_refs and k not in tc_names and k.split(".")[-1] in tc_names:
                drop.add(k)
        cand = [k for k in l_keys if k in tc_refs and k not in drop and k.split(".")[-1] not in s_set]
        if 0 < len(cand) == len(l_keys) - len(drop) - len(s_set):
            drop.update(cand)
    return drop


def compare_row_sets(
    sql_rows,
    looker_rows,
    sql: str = "",
    looker_fields: list[str] | None = None,
    fetch_extra=None,
    dynamic_fields: list | None = None,
):
    if len(sql_rows) != len(looker_rows):
        return False, [f"Row count mismatch: SQL={len(sql_rows)}, Looker={len(looker_rows)}"]
    if not sql_rows:
        return True, []
    scales, pct_cols, pct_idxs, sel_exprs, has_order_by, order_specs, limit_n = _sql_meta(sql)
    f_norm = [f.lower() for f in (looker_fields or [])]
    drop_l = _drop_grain_keys(sql_rows, looker_rows, f_norm, dynamic_fields)

    def _norm_lr(lr):
        raw_lr = {k.lower(): v for k, v in lr.items() if k.lower() not in drop_l}
        return {k: raw_lr[k] for k in [k for k in f_norm if k in raw_lr] + list(raw_lr)}

    sr_leaves = [{k.split(".")[-1].lower(): v for k, v in sr.items()} for sr in sql_rows]
    lr_leaves = [_norm_lr(lr) for lr in looker_rows]
    bad_cols = [
        f"Row {i} column count mismatch: SQL={len(sr)} {list(sr)}, Looker={len(lr)} {list(lr)}"
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
        s_strs = [r[sk].strip() for r in sr_leaves if isinstance(r.get(sk), str) and r[sk].strip()]
        l_strs = [r[lk].strip() for r in lr_leaves if isinstance(r.get(lk), str) and r[lk].strip()]
        if s_strs and l_strs and all(re.match(r"^\d+\.\s+\S", s) for s in s_strs) and not any(
            re.match(r"^\d+\.\s+\S", s) for s in l_strs
        ):
            for r in sr_leaves:
                if isinstance(r.get(sk), str):
                    r[sk] = re.sub(r"^\d+\.\s+", "", r[sk].strip())
        digits = scales.get(sk, 4)
        mult = 1.0
        if sk in pct_cols or c_idx in pct_idxs:
            s_abs = sum(abs(f) for r in sr_leaves for f in [_to_float(r.get(sk))] if f is not None)
            l_abs = sum(abs(f) for r in lr_leaves for f in [_to_float(r.get(lk))] if f is not None)
            if l_abs > 0 and abs(s_abs - l_abs * 100.0) < abs(s_abs - l_abs):
                mult = 100.0
        s_vals = [r[sk] for r in sr_leaves if r.get(sk) is not None]
        l_vals = [r[lk] for r in lr_leaves if r.get(lk) is not None]
        s_ts, l_ts = [_parse_ts(x) for x in s_vals], [_parse_ts(x) for x in l_vals]
        is_ts = bool(s_ts and l_ts) and all(x is not None for x in s_ts + l_ts)
        is_b = bool(s_vals and l_vals) and all(
            isinstance(x, bool) or (isinstance(x, str) and x.strip().lower() in ("true", "false", "yes", "no"))
            for x in s_vals + l_vals
        )
        ts_mode = "bool" if is_b else (("sec" if not any(x[1] for x in l_ts if x) else "sub") if is_ts else None)
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
    if mismatches and sr_leaves:
        for label, sk, lk, digits, mult, tm in cols:
            pairs = [_cmp_pair(sr[sk], lr[lk], digits, mult, tm) for sr, lr in zip(sr_leaves, lr_leaves)]
            if all(lv in (0, 0.0, None) for _, lv in pairs) and any(sv not in (0, 0.0, None) for sv, _ in pairs):
                mismatches.append(f"Hint ({label}): all Looker values are 0/NULL — check LookML filters (escape ',' as '^,' or use '-NULL'/'NOT NULL').")
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


def _as_dict(raw):
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _exec_sql(sql_str: str, conn_name: str):
    body = {"sql": sql_str, **({"connection_name": conn_name} if conn_name else {})}
    slug = (create_sql_query(body=body) or {}).get("slug")  # ty: ignore[unresolved-reference]
    if not slug:
        return None
    raw = run_sql_query(slug=slug, result_format="json")  # ty: ignore[unresolved-reference]
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (json.JSONDecodeError, TypeError):
        return None


def main():
    try:
        data = _as_dict(data_json)  # ty: ignore[unresolved-reference]
    except NameError:
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
        payloads = _as_dict(inline_queries_json)  # ty: ignore[unresolved-reference]
    except NameError:
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
            q.pop("sql_rows", None)
            stmt_sql = str(q.get("sql") or "")
            run_id_str = str(data.get("run_id") or "")
            pinned_stmt, stmt_pinned = _pin_temporal_sql(stmt_sql, run_id_str)
            q_id = q.get("query_id")
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
            has_post_sql = bool(
                (
                    isinstance(active_q, dict)
                    and any(active_q.get(k) for k in ("pivots", "fill_fields", "subtotals", "row_total"))
                )
                or any(isinstance(d, dict) and d.get("table_calculation") for d in dfs)
            )

            def _q_call(fmt: str, aq=active_q, qid=q_id, **kw):
                return (
                    run_inline_query(result_format=fmt, body=aq, **kw)  # ty: ignore[unresolved-reference]
                    if aq
                    else run_query(query_id=qid, result_format=fmt, **kw)  # ty: ignore[unresolved-reference]
                )

            def _compile_pinned_sql(aq=active_q, _rid=run_id_str):
                l_sql = _q_call("sql", aq=aq)
                ok = isinstance(l_sql, str) and re.match(r"(?is)^(?:\s|--[^\n]*|/\*[\s\S]*?\*/)*(?:SELECT|WITH)\b", l_sql)
                return _pin_temporal_sql(l_sql, _rid)[0] if ok else None

            def _run_pinned_q(aq=active_q, _ps=pinned_stmt, _qf=q_fields, _cn=c_name):
                pl = _compile_pinned_sql(aq=aq)
                raw_r = _exec_sql(f"-- parity-pin-{_fp(_ps + chr(0) + pl)}\n{pl}", _cn) if pl else None
                return _remap_compiled_rows(raw_r, _qf) if isinstance(raw_r, list) else None

            def _run_looker_live(bypass_cache: bool = False, _aq=active_q):
                raw = _q_call("json", aq=_aq, **({"cache": False} if bypass_cache else {}))
                return raw, (json.loads(raw) if isinstance(raw, str) else (raw or []))

            pinned_mode = False
            s_rows, l_rows = [], []
            if stmt_pinned and not has_post_sql:
                try:
                    pinned_l_sql = _compile_pinned_sql()
                    if pinned_l_sql is not None:
                        tag = f"-- parity-pin-{_fp(pinned_stmt + chr(0) + pinned_l_sql)}\n"
                        ps_rows, pl_rows = _exec_sql(f"{tag}{pinned_stmt}", c_name), _exec_sql(f"{tag}{pinned_l_sql}", c_name)
                        if ps_rows is not None and pl_rows is not None:
                            s_rows, l_rows, pinned_mode = ps_rows, _remap_compiled_rows(pl_rows, q_fields), True
                except Exception:
                    pinned_mode = False

            if not pinned_mode:
                s_raw = run_sql_query(slug=sql_slug, result_format="json")  # ty: ignore[unresolved-reference]
                s_rows = json.loads(s_raw) if isinstance(s_raw, str) else (s_raw or [])
                _, l_rows = _run_looker_live(bypass_cache=stmt_pinned)

            def _fetch_tie_pool(new_lim: int, _q=active_q, _pm=pinned_mode, _nc=stmt_pinned):
                nq = {**_q, "limit": str(new_lim)}
                res_p = _run_pinned_q(aq=nq) if _pm else _run_looker_live(bypass_cache=_nc, _aq=nq)[1]
                return res_p if isinstance(res_p, list) else []

            matched, mismatches = compare_row_sets(
                s_rows,
                l_rows,
                sql=stmt_sql,
                looker_fields=q_fields,
                fetch_extra=_fetch_tie_pool if isinstance(active_q, dict) else None,
                dynamic_fields=dfs,
            )
            if not matched and stmt_pinned and not pinned_mode:
                l_raw, l_rows = _run_looker_live(bypass_cache=True)
                try:
                    ps_retry = _exec_sql(f"-- parity-live-{_fp(str(l_raw))}\n{stmt_sql}", c_name)
                except Exception:
                    ps_retry = None
                if ps_retry is not None:
                    s_rows = ps_retry
                matched, mismatches = compare_row_sets(
                    s_rows,
                    l_rows,
                    sql=stmt_sql,
                    looker_fields=q_fields,
                    fetch_extra=_fetch_tie_pool if isinstance(active_q, dict) else None,
                    dynamic_fields=dfs,
                )
            if not matched and isinstance(active_q, dict) and s_rows and len(s_rows) == len(l_rows) and not has_post_sql:
                _, _, _, _, has_ob, _, _ = _sql_meta(stmt_sql)
                base_stmt = pinned_stmt if pinned_mode else stmt_sql
                clean_sql = re.sub(r"(?:\s|--[^\n]*|/\*[\s\S]*?\*/|;)+$", "", base_stmt)
                lim_match = re.search(r"(?i)\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\s*$", clean_sql)
                ex_sorts = [str(s) for s in (active_q.get("sorts") or []) if str(s).strip()] if has_ob else []
                if lim_match and (not has_ob or ex_sorts):
                    lim_clause = clean_sql[lim_match.start() :].lstrip()
                    no_lim = clean_sql[: lim_match.start()].rstrip()
                    ord_cols = ", ".join(str(i) for i in range(1, len(s_rows[0]) + 1))
                    drop_k = _drop_grain_keys(s_rows, l_rows, [f.lower() for f in q_fields], dfs)
                    sort_f = [f for f in q_fields if f.lower() not in drop_k][: len(s_rows[0])]
                    seen_sf = {s.split()[0].lower() for s in ex_sorts}
                    det_sql = (
                        f"{no_lim}, {ord_cols} {lim_clause}"
                        if has_ob
                        else f"SELECT * FROM (\n{no_lim}\n) AS _lkr_det ORDER BY {ord_cols} {lim_clause}"
                    )
                    det_q = {**active_q, "sorts": ex_sorts + [f"{f} asc" for f in sort_f if f.lower() not in seen_sf]}
                    try:
                        ds_rows = _exec_sql(det_sql, c_name)
                        dl_rows = (
                            (_run_pinned_q(aq=det_q) if pinned_mode else _run_looker_live(_aq=det_q)[1])
                            if isinstance(ds_rows, list) and len(ds_rows) == len(s_rows)
                            else None
                        )
                    except Exception:
                        ds_rows, dl_rows = None, None
                    if isinstance(ds_rows, list) and isinstance(dl_rows, list):
                        matched, mismatches = compare_row_sets(
                            ds_rows,
                            dl_rows,
                            sql=stmt_sql if has_ob else f"{no_lim} ORDER BY {ord_cols} {lim_clause}",
                            looker_fields=q_fields,
                            fetch_extra=lambda new_lim, _dq=det_q: _fetch_tie_pool(new_lim, _dq),
                            dynamic_fields=dfs,
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
        parsed_tq = _as_dict(test_queries_json)  # ty: ignore[unresolved-reference]
    except NameError:
        parsed_tq = {}
    test_queries = {str(k): v for k, v in parsed_tq.items() if isinstance(v, dict)}

    if test_queries and all_matched and not val_errors:
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
