import json
import warnings
from typing import Any

from lkr.codemode.type import to_primitive
from lkr.logger import logger

query: Any = None
query_for_slug: Any = None
merge_query: Any = None
dashboard: Any = None
look: Any = None
get_conversation: Any = None
all_conversation_messages: Any = None
lookml_model_explore: Any = None
run_inline_query: Any = None
create_sql_query: Any = None
run_sql_query: Any = None
_raw_run_key_driver_analysis: Any = None


def _warn_sdk_query(msg: str) -> None:
    warnings.warn(msg, UserWarning, stacklevel=3)
    logger.warning(msg)


def _bind_sdk(sdk: Any, transport_options: Any = None) -> None:
    global query, query_for_slug, merge_query, dashboard, look
    global get_conversation, all_conversation_messages, lookml_model_explore
    global run_inline_query, create_sql_query, run_sql_query, _raw_run_key_driver_analysis

    def _wrap(attr: str) -> Any:
        fn = getattr(sdk, attr, None)
        if fn is None:
            return None

        def _inner(*a: Any, **kw: Any) -> Any:
            if transport_options is not None and "transport_options" not in kw:
                kw["transport_options"] = transport_options
            return to_primitive(fn(*a, **kw))

        return _inner

    query = _wrap("query")
    query_for_slug = _wrap("query_for_slug")
    merge_query = _wrap("merge_query")
    dashboard = _wrap("dashboard")
    look = _wrap("look")
    get_conversation = _wrap("get_conversation")
    all_conversation_messages = _wrap("all_conversation_messages")
    lookml_model_explore = _wrap("lookml_model_explore")
    create_sql_query = _wrap("create_sql_query")
    run_sql_query = _wrap("run_sql_query")

    def _run_inline(result_format: str, body: Any, **kw: Any) -> Any:
        if transport_options is not None and "transport_options" not in kw:
            kw["transport_options"] = transport_options
        raw = sdk.run_inline_query(result_format, body, **kw)
        if isinstance(raw, str):
            if result_format != "json":
                return raw
            s = raw.strip()
            return json.loads(s) if s else []
        return to_primitive(raw)

    def _raw_kda(body: Any, topts: Any = None) -> Any:
        opts = topts if topts is not None else transport_options
        return to_primitive(
            sdk.post(
                path="/internal/kda/analyze",
                structure=Any,
                body=sdk._prepare_body(body),
                transport_options=opts,
            )
        )

    run_inline_query = _run_inline
    _raw_run_key_driver_analysis = _raw_kda


# --- MONTY_KDA_PREAMBLE ---
TIME_SUFFIXES = (
    "_date",
    "_time",
    "_year",
    "_month",
    "_quarter",
    "_week",
    "_day",
    "_raw",
    "_hour",
    "_minute",
    "_fiscal_year",
    "_fiscal_quarter",
    "_month_name",
    "_month_num",
    "_day_of_week",
    "_day_of_week_index",
    "_day_of_month",
    "_day_of_year",
    "_week_of_year",
    "_quarter_of_year",
    "_hour_of_day",
    "_time_of_day",
)
PRIMARY_TIME_SUFFIXES = ("_date", "_week", "_month", "_quarter", "_year")
MACRO_TOKENS = (
    "status",
    "department",
    "traffic_source",
    "gender",
    "country",
    "event_type",
    "channel",
    "segment",
    "category",
    "browser",
    "state",
    "brand",
)
BAD_DIM_SUFFIXES = (
    ".id",
    "_id",
    "_pk",
    ".pk",
    "_url",
    "_image",
    "_image_file",
    ".image_file",
    ".portrait",
    "_email",
    ".email",
    ".name",
    "_name",
    ".ip",
    "_ssn",
    "_ssn_last_4",
    ".ssn_last_4",
    "_sequence_number",
    ".sku",
    "_sku",
    "_address",
    ".uri",
    ".history",
    ".zip",
    "_postcode",
)
BAD_DIM_TOKENS = (
    "reporting_period",
    "ytd",
    "mtd",
    "wtd",
    "months_since",
    "days_since",
    "days_to_",
    "days_between",
    "days_until",
    "first_order",
    "latest_order",
    "latitude",
    "longitude",
    "postal",
    "__sort_",
)


def _uniq(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _is_time_field(field_name):
    s = str(field_name or "")
    return any(s.endswith(suf) for suf in TIME_SUFFIXES)


def _extract_refs(sql, default_view):
    if not sql:
        return []
    refs = []
    for part in str(sql).split("${")[1:]:
        if "}" in part:
            tok = part.split("}", 1)[0].strip()
            if (
                tok
                and tok.upper() not in ("TABLE", "EXTENDED")
                and not tok.startswith("_")
                and not tok.endswith(".SQL_TABLE_NAME")
            ):
                qual = tok if "." in tok else f"{default_view}.{tok}"
                if qual not in refs:
                    refs.append(qual)
    return refs


def _table_col(sql, view):
    s = str(sql or "").strip().rstrip(";").strip()
    for pfx in ("${TABLE}.", f"{view}."):
        if s.startswith(pfx):
            col = s[len(pfx) :].strip('`"[] ')
            if col and all(c.isalnum() or c == "_" for c in col):
                return f"{view}.{col}"
    return None


def _resolve_query_id_or_slug(qid):
    s = str(qid).strip()
    if s.isdigit():
        try:
            q = query(s)
            if q and q.get("model") and q.get("view"):
                return q
        except Exception:  # noqa: BLE001, S110
            pass
    return query_for_slug(s)


def _expand_merge_query(mid, title_prefix="", filterables=None, df_vals=None):
    mq = merge_query(str(mid)) or {}
    targets = []
    flts_list = filterables or []
    d_vals = df_vals or {}
    for idx, sq in enumerate(mq.get("source_queries") or []):
        sq_q = _resolve_query_id_or_slug(sq.get("query_id"))
        if not sq_q or not sq_q.get("model") or not sq_q.get("view"):
            continue
        tf = dict(sq_q.get("filters") or {})
        listens = {}
        matched_flts = (
            [flts_list[idx]]
            if idx < len(flts_list)
            else [
                f
                for f in flts_list
                if f.get("model") == sq_q["model"] and f.get("view") == sq_q["view"]
            ]
        )
        for flt in matched_flts:
            for lsn in flt.get("listen") or []:
                fn, fld = lsn.get("dashboard_filter_name"), lsn.get("field")
                if fn and fld:
                    listens[fn] = fld
                    if d_vals.get(fn):
                        tf[fld] = d_vals[fn]
        m_dims = [
            mf.get("source_field_name")
            for mf in (sq.get("merge_fields") or [])
            if mf.get("source_field_name")
        ]
        q_fields = _uniq(m_dims + (sq_q.get("fields") or []))
        sq_label = sq.get("name") or f"{sq_q['model']}::{sq_q['view']}"
        targets.append(
            {
                "title": f"{title_prefix} [Merge: {sq_label}]".strip()
                if title_prefix
                else f"Merge {mid} [{sq_label}]",
                "model": sq_q["model"],
                "explore": sq_q["view"],
                "fields": q_fields,
                "filters": tf,
                "slug": sq_q.get("slug") or sq_q.get("id"),
                "merge_result_id": str(mid),
                "merge_fields": m_dims,
                "filter_listens": listens,
            }
        )
    return targets


def _resolve_raw_targets(
    target=None,
    model_name=None,
    explore_name=None,
    fields=None,
    filters=None,
    tile_filter=None,
):
    if model_name and explore_name and not target:
        return (
            "explore",
            [
                {
                    "title": f"{model_name}::{explore_name}",
                    "model": model_name,
                    "explore": explore_name,
                    "fields": list(fields or []),
                    "filters": dict(filters or {}),
                    "slug": None,
                    "merge_fields": [],
                    "filter_listens": {},
                }
            ],
        )

    s = str(target or "").strip()
    url_params = {}
    if "?" in s:
        base_s, _, qs = s.partition("?")
        for kv in qs.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                clean_k = k.replace("%5B", "[").replace("%5D", "]")
                clean_v = (
                    v.replace("+", " ")
                    .replace("%20", " ")
                    .replace("%2C", ",")
                    .replace("%3A", ":")
                )
                url_params[clean_k] = clean_v
    else:
        base_s = s

    url_flts = {
        k[2:-1]: v
        for k, v in url_params.items()
        if k.startswith("f[") and k.endswith("]")
    }

    def _query_to_target(q, title=None, slug_fallback=None):
        tf = dict(q.get("filters") or {})
        tf.update(url_flts)
        return {
            "title": title or f"{q['model']}::{q['view']}",
            "model": q["model"],
            "explore": q["view"],
            "fields": list(q.get("fields") or []),
            "filters": tf,
            "slug": q.get("slug") or q.get("id") or slug_fallback,
            "merge_fields": [],
            "filter_listens": {},
        }

    # 1. Dashboard URL or LookML/UDD ID
    if (
        "/dashboards/" in base_s
        or "/dashboards-next/" in base_s
        or ("::" in base_s and "/explore/" not in base_s)
    ):
        did = (
            [p for p in base_s.split("/") if p][-1].replace("%3A%3A", "::")
            if "/" in base_s
            else base_s
        )
        d = dashboard(did) or {}
        df_vals = {
            df["name"]: df.get("default_value")
            for df in (d.get("dashboard_filters") or [])
            if df.get("name") and df.get("default_value")
        }
        df_vals.update(url_params)
        tiles = []
        for e in d.get("dashboard_elements") or []:
            rm = e.get("result_maker") or {}
            q = e.get("query") or rm.get("query")
            mid = e.get("merge_result_id") or rm.get("merge_result_id")
            if mid and not q:
                tiles.extend(
                    _expand_merge_query(
                        mid,
                        title_prefix=e.get("title") or str(e.get("id")),
                        filterables=rm.get("filterables"),
                        df_vals=df_vals,
                    )
                )
                continue
            if not q or not q.get("model") or not q.get("view"):
                continue
            tf = dict(q.get("filters") or {})
            listens = {}
            for flt in rm.get("filterables") or []:
                for lsn in flt.get("listen") or []:
                    fn, fld = lsn.get("dashboard_filter_name"), lsn.get("field")
                    if fn and fld:
                        listens[fn] = fld
                        if df_vals.get(fn):
                            tf[fld] = df_vals[fn]
            tiles.append(
                {
                    "title": e.get("title") or str(e.get("id")),
                    "model": q["model"],
                    "explore": q["view"],
                    "fields": list(q.get("fields") or []),
                    "filters": tf,
                    "slug": q.get("slug") or q.get("id"),
                    "merge_fields": [],
                    "filter_listens": listens,
                }
            )
        if tile_filter:
            tf_list = (
                [tile_filter] if isinstance(tile_filter, str) else list(tile_filter)
            )
            low_filters = [str(x).lower() for x in tf_list if x]
            tiles = [
                t
                for t in tiles
                if any(lf in str(t.get("title") or "").lower() for lf in low_filters)
            ]
        return ("dashboard", tiles)

    # 2. Look URL or numeric ID
    if "/looks/" in base_s or s.isdigit():
        lid = [p for p in base_s.split("/") if p][-1]
        try:
            lk = look(lid)
            if lk and (lk.get("query") or lk.get("query_id")):
                q = lk.get("query") or _resolve_query_id_or_slug(lk["query_id"])
                return (
                    "look",
                    [_query_to_target(q, title=lk.get("title") or f"Look {lid}")],
                )
        except Exception:
            if "/looks/" in base_s:
                raise

    # 3. Conversational Analytics Conversation URL or 32-char hex UUID
    clean_id = [p for p in base_s.split("/") if p][-1] if base_s else ""
    if (
        "/conversations/" in base_s
        or "/ca/" in base_s
        or (
            len(clean_id) == 32
            and all(c in "0123456789abcdef" for c in clean_id.lower())
        )
    ):
        c = get_conversation(clean_id)
        msgs = all_conversation_messages(clean_id)
        turns, cur_q = [], None
        for m in msgs or []:
            msg = m.get("message") or {}
            if m.get("type") == "user":
                cur_q = (msg.get("userMessage") or {}).get("text")
            gq = ((msg.get("systemMessage") or {}).get("data") or {}).get(
                "generatedLookerQuery"
            )
            if gq and gq.get("model") and (gq.get("explore") or gq.get("view")):
                raw_flts = gq.get("filters") or []
                if isinstance(raw_flts, dict):
                    flts = dict(raw_flts)
                else:
                    flts = {
                        fi["field"]: str(fi.get("value", ""))
                        for fi in raw_flts
                        if isinstance(fi, dict) and fi.get("field")
                    }
                turns.append(
                    {
                        "title": cur_q or f"Turn {len(turns) + 1}",
                        "model": gq["model"],
                        "explore": gq.get("explore") or gq.get("view"),
                        "fields": list(gq.get("fields") or []),
                        "filters": flts,
                        "slug": None,
                        "merge_fields": [],
                        "filter_listens": {},
                    }
                )
        if not turns and c and c.get("sources"):
            src = c["sources"][0]
            turns.append(
                {
                    "title": c.get("name") or "Conversation",
                    "model": src["model"],
                    "explore": src.get("explore") or src.get("view"),
                    "fields": list(fields or []),
                    "filters": dict(filters or {}),
                    "slug": None,
                    "merge_fields": [],
                    "filter_listens": {},
                }
            )
        return ("conversation", turns)

    # 4. Standalone Merge Result URL (/merge?mid=...)
    if "/merge" in base_s or "mid" in url_params:
        mid = url_params.get("mid") or clean_id
        return ("merge_result", _expand_merge_query(mid))

    # 5. Explore URL (/explore/<model>/<explore>)
    if "/explore/" in base_s:
        after = base_s.split("/explore/", 1)[1]
        parts = [p for p in after.split("/") if p]
        m_name, e_name = parts[0], parts[1]
        if "qid" in url_params:
            q = _resolve_query_id_or_slug(url_params["qid"])
            return ("explore", [_query_to_target(q, slug_fallback=url_params["qid"])])
        u_fields = [f for f in url_params.get("fields", "").split(",") if f]
        return (
            "explore",
            [
                {
                    "title": f"{m_name}::{e_name}",
                    "model": m_name,
                    "explore": e_name,
                    "fields": u_fields,
                    "filters": dict(url_flts),
                    "slug": None,
                    "merge_fields": [],
                    "filter_listens": {},
                }
            ],
        )

    # 6. Raw Query Slug / ID or Merge ID
    try:
        q = _resolve_query_id_or_slug(clean_id)
        if q and q.get("model") and q.get("view"):
            return ("query", [_query_to_target(q, slug_fallback=clean_id)])
    except Exception:  # noqa: BLE001, S110
        pass
    return ("merge_result", _expand_merge_query(clean_id))


def _decompile_single_target(tgt, exp):
    exp = exp or {}
    model_name, explore_name = tgt["model"], tgt["explore"]
    base_view = exp.get("view_name") or explore_name
    flds = exp.get("fields") or {}
    dims = flds.get("dimensions") or []
    meas = flds.get("measures") or []
    joins = exp.get("joins") or []
    sets_list = exp.get("sets") or []

    dims_by_name = {d["name"]: d for d in dims if d.get("name")}
    meas_by_name = {m["name"]: m for m in meas if m.get("name")}

    inner_joins = {
        j.get("name") for j in joins if j.get("type") == "inner" and j.get("name")
    }
    liquid_views = {
        f.get("view")
        for f in (dims + meas)
        if f.get("view") and "{%" in str(f.get("sql") or "")
    }
    bad_views = inner_joins | liquid_views

    # Conditional / role-playing left_outer joins (e.g. product_viewed on events)
    conditional_joins = {}
    for j in joins:
        j_name = j.get("name")
        if not j_name or j_name in bad_views:
            continue
        dep_flds = j.get("dependent_fields") or _extract_refs(j.get("sql_on"), j_name)
        fk_cond = None
        for df in dep_flds:
            if not df.startswith(j_name + "."):
                fk_dim = dims_by_name.get(df)
                fk_sql = str((fk_dim or {}).get("sql") or "")
                if "CASE " in fk_sql.upper() or "IF(" in fk_sql.upper():
                    fk_cond = f"{df}: {fk_sql.strip()}"
                    break
        if fk_cond or (j.get("from") and j_name != base_view):
            conditional_joins[j_name] = fk_cond or f"from: {j.get('from')}"

    # Map unfiltered additive measures by referenced dimension or ${TABLE}.col
    sum_by_dim = {}
    count_by_view = {}
    dim_by_table_col = {}
    for d in dims:
        d_name, d_view = d.get("name"), d.get("view") or base_view
        tc = _table_col(d.get("sql"), d_view)
        if d_name and tc and not d.get("is_timeframe"):
            dim_by_table_col.setdefault(tc, []).append(d_name)

    for m in meas:
        m_name = m.get("name")
        m_view = m.get("view") or base_view
        m_type = m.get("type") or ""
        if not m_name or m_view in bad_views or m.get("filters"):
            continue
        if m_type == "count":
            count_by_view.setdefault(m_view, []).insert(0, m_name)
        elif m_type == "count_distinct":
            count_by_view.setdefault(m_view, []).append(m_name)
        elif m_type in ("sum", "sum_distinct"):
            m_refs = _extract_refs(m.get("sql"), m_view)
            if len(m_refs) == 1 and m_refs[0] in dims_by_name:
                sum_by_dim.setdefault(m_refs[0], []).append(m_name)
            else:
                tc = _table_col(m.get("sql"), m_view)
                if tc:
                    for dn in dim_by_table_col.get(tc, []):
                        sum_by_dim.setdefault(dn, []).append(m_name)

    # Identify target measures in query
    q_fields = list(tgt.get("fields") or [])
    q_measures = [f for f in q_fields if f in meas_by_name]
    if not q_measures:
        default_meas = [
            m["name"]
            for m in meas
            if not m.get("hidden")
            and m.get("type") in ("sum", "count", "sum_distinct")
            and m.get("view") not in bad_views
        ]
        q_measures = default_meas[:1]

    # Decompile each measure via recursive ${...} walk
    decompiled_measures = {}
    all_target_leaf_dims = set()
    touched_views = {base_view}
    measure_drill_pool = []

    def _walk_refs(sql_expr, cur_view, visited, ref_measures, derived_dims, leaf_dims):
        for ref in _extract_refs(sql_expr, cur_view):
            if ref in visited:
                continue
            visited.add(ref)
            if ref in meas_by_name:
                rm = meas_by_name[ref]
                rm_view = rm.get("view") or cur_view
                touched_views.add(rm_view)
                ref_measures.append(ref)
                measure_drill_pool.extend(rm.get("drill_fields") or [])
                _walk_refs(
                    rm.get("sql"),
                    rm_view,
                    visited,
                    ref_measures,
                    derived_dims,
                    leaf_dims,
                )
            elif ref in dims_by_name:
                rd = dims_by_name[ref]
                rd_view = rd.get("view") or cur_view
                touched_views.add(rd_view)
                rd_sql = str(rd.get("sql") or "").strip()
                sub_refs = [
                    sr
                    for sr in _extract_refs(rd_sql, rd_view)
                    if sr in dims_by_name or sr in meas_by_name
                ]
                if sub_refs:
                    derived_dims.append(
                        {
                            "dimension": ref,
                            "sql": rd_sql,
                            "matched_additive_measures": _uniq(sum_by_dim.get(ref, [])),
                        }
                    )
                    _walk_refs(
                        rd_sql,
                        rd_view,
                        visited,
                        ref_measures,
                        derived_dims,
                        leaf_dims,
                    )
                else:
                    leaf_dims.append(ref)

    for m_name in q_measures:
        m_obj = meas_by_name.get(m_name) or {}
        m_view = m_obj.get("view") or base_view
        m_type = m_obj.get("type") or ""
        m_sql = str(m_obj.get("sql") or "").strip()
        touched_views.add(m_view)
        measure_drill_pool.extend(m_obj.get("drill_fields") or [])

        ref_measures = []
        derived_dims = []
        leaf_dims = []
        _walk_refs(m_sql, m_view, {m_name}, ref_measures, derived_dims, leaf_dims)
        if not leaf_dims and not ref_measures:
            tc = _table_col(m_sql, m_view)
            if tc:
                for dn in dim_by_table_col.get(tc, []):
                    if dn not in leaf_dims:
                        leaf_dims.append(dn)

        leaf_entries = []
        unmodeled = []
        matched_order = []
        for dd in derived_dims:
            all_target_leaf_dims.add(dd["dimension"])
            for mm in dd.get("matched_additive_measures") or []:
                if mm not in matched_order:
                    matched_order.append(mm)
        for ld_name in leaf_dims:
            all_target_leaf_dims.add(ld_name)
            ld_obj = dims_by_name.get(ld_name) or {}
            ld_view = ld_obj.get("view") or base_view
            ld_sql = str(ld_obj.get("sql") or "").strip()
            matched = _uniq(sum_by_dim.get(ld_name, []))
            for mm in matched:
                if mm not in matched_order:
                    matched_order.append(mm)
                measure_drill_pool.extend(
                    (meas_by_name.get(mm) or {}).get("drill_fields") or []
                )
            leaf_entries.append(
                {
                    "dimension": ld_name,
                    "view": ld_view,
                    "sql": ld_sql,
                    "matched_additive_measures": matched,
                }
            )
            low_ld = ld_name.lower()
            if (
                not matched
                and ld_obj.get("type") == "number"
                and not ld_obj.get("primary_key")
                and not low_ld.endswith((".id", "_id", ".pk", "_pk"))
            ):
                safe_slug = ld_name.replace(".", "_")
                unmodeled.append(
                    {
                        "dimension": ld_name,
                        "view": ld_view,
                        "sql": ld_sql,
                        "expected_measure_type": "sum",
                        "warning": f"No unfiltered SUM({ld_name}) measure exists in {model_name}::{explore_name}. Looker's run_key_driver_analysis only accepts modeled LookML measures; use run_inline_query with dynamic_fields to inspect SUM({ld_name}).",
                        "dynamic_field_hint": {
                            "measure": f"sum_of_{safe_slug}",
                            "based_on": ld_name,
                            "type": "sum",
                            "label": f"Sum of {ld_name}",
                        },
                    }
                )

        rec_measures = []
        if m_type in ("sum", "sum_distinct", "count", "count_distinct"):
            rec_measures.append(m_name)
        for rm in ref_measures:
            rm_t = (meas_by_name.get(rm) or {}).get("type") or ""
            if rm_t in ("sum", "sum_distinct", "count", "count_distinct"):
                rec_measures.append(rm)
        rec_measures.extend(matched_order)
        if m_type in ("average", "average_distinct", "median"):
            v_cnts = count_by_view.get(m_view, [])
            if v_cnts:
                rec_measures.append(v_cnts[0])
            else:
                unmodeled.append(
                    {
                        "dimension": f"{m_view}.*",
                        "view": m_view,
                        "sql": "COUNT(*)",
                        "expected_measure_type": "count",
                        "warning": f"No unfiltered COUNT measure exists on view {m_view} in {model_name}::{explore_name} to decompose {m_name}.",
                    }
                )
        if not rec_measures:
            rec_measures.append(m_name)

        decompiled_measures[m_name] = {
            "type": m_type,
            "view": m_view,
            "sql": m_sql,
            "referenced_measures": _uniq(ref_measures),
            "derived_dimensions": derived_dims,
            "leaf_dimensions": leaf_entries,
            "recommended_kda_measures": _uniq(rec_measures),
            "unmodeled_components": unmodeled,
        }

    # Transitive dimension ref helper to detect tautological _tier / derived dimensions
    def _dim_touches_leaf(d_name):
        stack = [d_name]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur in all_target_leaf_dims:
                return True
            d_obj = dims_by_name.get(cur)
            if d_obj:
                d_v = d_obj.get("view") or base_view
                for r in _extract_refs(d_obj.get("sql"), d_v):
                    if r not in seen:
                        stack.append(r)
        return False

    def _is_valid_driver_dim(d_name, allow_yesno_tier=False):
        d = dims_by_name.get(d_name)
        if not d:
            return False
        dtype = d.get("type") or "string"
        d_view = d.get("view") or base_view
        if (
            d.get("hidden")
            or d.get("primary_key")
            or d.get("is_timeframe")
            or dtype.startswith("date")
            or d.get("is_numeric")
            or dtype in ("number", "distance", "location", "zipcode")
            or not d.get("can_filter", True)
            or d_view in bad_views
        ):
            return False
        if not allow_yesno_tier and dtype in ("yesno", "tier"):
            return False
        low = d_name.lower()
        if any(low.endswith(suf) for suf in BAD_DIM_SUFFIXES):
            return False
        if any(tok in low for tok in BAD_DIM_TOKENS):
            return False
        return not (
            (dtype == "tier" or "${" in str(d.get("sql") or ""))
            and _dim_touches_leaf(d_name)
        )

    def _macro_rank(d_name):
        low = d_name.lower()
        for idx, tok in enumerate(MACRO_TOKENS):
            if low.endswith(("." + tok, "_" + tok)):
                return (0 if d_name.startswith(base_view + ".") else 1, idx, d_name)
        return (2 if d_name.startswith(base_view + ".") else 3, 99, d_name)

    # Timeframes & Filter split
    all_timeframes = [
        d["name"] for d in dims if d.get("is_timeframe") and d.get("name")
    ]
    tframe_set = set(all_timeframes)
    avail_tframes = [
        f
        for f in all_timeframes
        if f.startswith(base_view + ".")
        and any(f.endswith(suf) for suf in PRIMARY_TIME_SUFFIXES)
    ] or [
        f
        for f in all_timeframes
        if any(f.endswith(suf) for suf in PRIMARY_TIME_SUFFIXES)
    ]

    raw_filters = dict(tgt.get("filters") or {})
    base_filters = {}
    colliding_time_filters = {}
    for k, v in raw_filters.items():
        if k in tframe_set or _is_time_field(k):
            colliding_time_filters[k] = v
        else:
            base_filters[k] = v

    query_tframes = _uniq(
        [f for f in q_fields if f in tframe_set or _is_time_field(f)]
        + list(colliding_time_filters.keys())
    )

    # Collect drill_fields from measures, query dims, base count measure, and explore["sets"]
    for vm in count_by_view.get(base_view, []):
        measure_drill_pool.extend((meas_by_name.get(vm) or {}).get("drill_fields") or [])
    for qf in q_fields:
        measure_drill_pool.extend((dims_by_name.get(qf) or {}).get("drill_fields") or [])
    for s_entry in sets_list:
        s_name = str(s_entry.get("name") or "")
        s_view = s_name.split(".", 1)[0] if "." in s_name else base_view
        if s_view not in bad_views and s_view not in conditional_joins:
            measure_drill_pool.extend(s_entry.get("value") or [])

    # Bucket candidate dimensions
    query_dims = _uniq(
        [
            f
            for f in q_fields
            if f not in meas_by_name
            and f not in tframe_set
            and not _is_time_field(f)
            and _is_valid_driver_dim(f, allow_yesno_tier=True)
            and (dims_by_name[f].get("view") or base_view) not in conditional_joins
        ]
    )
    drill_dims = sorted(
        _uniq(
            [
                f
                for f in measure_drill_pool
                if f not in query_dims
                and f not in base_filters
                and _is_valid_driver_dim(f, allow_yesno_tier=False)
                and (dims_by_name[f].get("view") or base_view) not in conditional_joins
            ]
        ),
        key=_macro_rank,
    )

    entity_dims = []
    flag_tier_dims = []
    cond_join_dims = []
    seen_cands = set(query_dims) | set(drill_dims)

    for d in dims:
        dn = d.get("name")
        if not dn or dn in seen_cands or dn in base_filters:
            continue
        dv = d.get("view") or base_view
        if not _is_valid_driver_dim(dn, allow_yesno_tier=True):
            continue
        if dv in conditional_joins:
            cond_join_dims.append(
                {
                    "dimension": dn,
                    "view": dv,
                    "join_condition": conditional_joins[dv],
                }
            )
        elif d.get("type") in ("yesno", "tier"):
            flag_tier_dims.append(dn)
        else:
            entity_dims.append(dn)

    entity_dims.sort(key=_macro_rank)
    pass1 = _uniq(query_dims + drill_dims + entity_dims + flag_tier_dims)[:6]

    return {
        "title": tgt.get("title") or f"{model_name}::{explore_name}",
        "data_source": {
            "model_name": model_name,
            "explore_name": explore_name,
        },
        "slug": tgt.get("slug"),
        "merge_result_id": tgt.get("merge_result_id"),
        "base_filters": base_filters,
        "colliding_time_filters": colliding_time_filters,
        "query_timeframes": query_tframes,
        "available_timeframes": avail_tframes,
        "measures": decompiled_measures,
        "candidate_dimensions": {
            "query_dimensions": query_dims,
            "drill_dimensions": drill_dims,
            "entity_dimensions": entity_dims,
            "secondary_flag_and_tier_dimensions": flag_tier_dims,
            "conditional_join_dimensions": cond_join_dims,
        },
        "recommended_pass1_dimensions": pass1,
        "excluded_views": sorted(bad_views),
        "_views": sorted(
            {
                (d.get("view") or base_view)
                for d in dims
                if (d.get("view") or base_view) not in bad_views
            }
        ),
        "_filter_listens": tgt.get("filter_listens") or {},
        "_merge_fields": tgt.get("merge_fields") or [],
    }


def decompile_kda_target(
    target=None,
    model_name=None,
    explore_name=None,
    fields=None,
    filters=None,
    tile_filter=None,
):
    """Decompile an Explore URL, Query slug, Look, Dashboard, Merge Result, or Conversation into KDA measures and candidate driver dimensions."""
    t_type, raw_targets = _resolve_raw_targets(
        target=target,
        model_name=model_name,
        explore_name=explore_name,
        fields=fields,
        filters=filters,
        tile_filter=tile_filter,
    )
    explore_cache = {}
    compiled_targets = []
    for rt in raw_targets:
        if fields:
            rt["fields"] = _uniq(list(rt.get("fields") or []) + list(fields))
        if filters:
            merged_flts = dict(rt.get("filters") or {})
            merged_flts.update(filters)
            rt["filters"] = merged_flts
        key = (rt["model"], rt["explore"])
        if key not in explore_cache:
            explore_cache[key] = lookml_model_explore(rt["model"], rt["explore"])
        compiled_targets.append(_decompile_single_target(rt, explore_cache[key]))

    overlaps = []
    if len(explore_cache) > 1:
        views_by_exp = {}
        dims_by_exp = {}
        tframes_by_exp = {}
        filter_map = {}
        merge_keys = []
        for ct in compiled_targets:
            ek = f"{ct['data_source']['model_name']}::{ct['data_source']['explore_name']}"
            cands = ct["candidate_dimensions"]
            all_d = (
                cands["query_dimensions"]
                + cands["drill_dimensions"]
                + cands["entity_dimensions"]
            )
            if ek not in views_by_exp:
                views_by_exp[ek] = list(ct.get("_views") or [])
                dims_by_exp[ek] = list(all_d)
                tframes_by_exp[ek] = list(ct.get("available_timeframes") or [])
            for fn, fld in (ct.get("_filter_listens") or {}).items():
                filter_map.setdefault(fn, {})[ek] = fld
            for mf in ct.get("_merge_fields") or []:
                if mf not in merge_keys:
                    merge_keys.append(mf)

        exp_keys = sorted(views_by_exp.keys())
        for i in range(len(exp_keys)):
            for j in range(i + 1, len(exp_keys)):
                e1, e2 = exp_keys[i], exp_keys[j]
                v1, v2 = views_by_exp.get(e1) or [], views_by_exp.get(e2) or []
                d1, d2 = dims_by_exp.get(e1) or [], dims_by_exp.get(e2) or []
                shared_views = sorted([v for v in v1 if v in v2])
                shared_dims = sorted(_uniq([d for d in d1 if d in d2]))
                shared_flts = {
                    fn: fmap
                    for fn, fmap in filter_map.items()
                    if e1 in fmap and e2 in fmap
                }
                overlaps.append(
                    {
                        "explores": [e1, e2],
                        "shared_views": shared_views,
                        "shared_dimensions": shared_dims,
                        "shared_filter_mappings": shared_flts,
                        "merge_join_keys": merge_keys,
                        "timeframes_by_explore": {
                            e1: tframes_by_exp[e1],
                            e2: tframes_by_exp[e2],
                        },
                    }
                )

    for ct in compiled_targets:
        ct.pop("_views", None)
        ct.pop("_filter_listens", None)
        ct.pop("_merge_fields", None)

    return {
        "target_type": t_type,
        "targets": compiled_targets,
        "cross_explore_overlaps": overlaps,
    }


def _kda_fallback_422(
    model_name,
    explore_name,
    contribution_metric,
    dimensions,
    base_filters,
    baseline_filters,
    breach_filters,
    min_support=0.05,
    top_k=5,
):
    # ponytail: BQML-parity fallback for Looker 26.20-26.22 KdaResponse::Success.status 422 bug
    dims = list(dimensions or [])[:6]
    base = dict(base_filters or {})
    b_ctrl = dict(baseline_filters or {})
    b_test = dict(breach_filters or {})

    # Single-query cohort folding when filtering on the same single scalar key
    fold_key = None
    if len(b_ctrl) == 1 and len(b_test) == 1:
        k_c = next(iter(b_ctrl))
        k_t = next(iter(b_test))
        v_c, v_t = str(b_ctrl[k_c]).strip(), str(b_test[k_t]).strip()
        if (
            k_c == k_t
            and v_c != v_t
            and "," not in v_c
            and "," not in v_t
            and " " not in v_c
            and " " not in v_t
            and not v_c.startswith("-")
            and not v_t.startswith("-")
        ):
            fold_key = k_c

    def _q(flds, flts):
        return (
            run_inline_query(
                "json",
                {
                    "model": model_name,
                    "view": explore_name,
                    "fields": flds,
                    "filters": flts,
                    "limit": "50000",
                },
            )
            or []
        )

    if fold_key:
        q_flts = dict(base)
        q_flts[fold_key] = f"{b_ctrl[fold_key]},{b_test[fold_key]}"
        all_rows = _q(_uniq([fold_key] + dims + [contribution_metric]), q_flts)
        vc_str, vt_str = str(b_ctrl[fold_key]).strip(), str(b_test[fold_key]).strip()
        ctrl_rows = [r for r in all_rows if str(r.get(fold_key)) == vc_str]
        test_rows = [r for r in all_rows if str(r.get(fold_key)) == vt_str]
    else:
        q_fields = _uniq(dims + [contribution_metric])
        cf, tf = dict(base), dict(base)
        cf.update(b_ctrl)
        tf.update(b_test)
        ctrl_rows = _q(q_fields, cf)
        test_rows = _q(q_fields, tf)

    if not ctrl_rows or not test_rows:
        return {"status": "FAILED", "dimensions": dims, "drivers": []}

    min_non_null = 0.75 * len(test_rows)
    kept_dims = [
        d
        for d in dims
        if sum(1 for r in test_rows if r.get(d) is not None) >= min_non_null
    ]
    if not kept_dims:
        kept_dims = [
            d
            for d in dims
            if any(r.get(d) is not None for r in test_rows)
            or any(r.get(d) is not None for r in ctrl_rows)
        ]
    if not kept_dims:
        return {"status": "FAILED", "dimensions": dims, "drivers": []}

    allowed = {}
    for d in kept_dims:
        counts = {}
        for r in test_rows:
            v = r.get(d)
            if v is not None:
                sv = str(v)
                counts[sv] = counts.get(sv, 0) + 1
        allowed[d] = {
            k for k, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:60]
        }

    def _prep(rows):
        out, tot, dropped = [], 0.0, 0
        for r in rows:
            if any(r.get(d) is None for d in kept_dims):
                dropped += 1
                continue
            vals = []
            for d in kept_dims:
                val_str = str(r.get(d))
                vals.append(val_str if val_str in allowed[d] else "__OTHER__")
            m = float(r.get(contribution_metric) or 0.0)
            out.append((vals, m))
            tot += m
        return out, tot, dropped

    test_cohort, tot_test, drop_test = _prep(test_rows)
    ctrl_cohort, tot_ctrl, drop_ctrl = _prep(ctrl_rows)
    if tot_test <= 0 and tot_ctrl <= 0:
        return {"status": "FAILED", "dimensions": kept_dims, "drivers": []}

    overall_diff = tot_test - tot_ctrl
    n = len(kept_dims)
    full_agg = {}
    for vals, m in test_cohort:
        k = tuple(vals)
        cur = full_agg.get(k)
        if cur is None:
            full_agg[k] = [m, 0.0]
        else:
            cur[0] += m
    for vals, m in ctrl_cohort:
        k = tuple(vals)
        cur = full_agg.get(k)
        if cur is None:
            full_agg[k] = [0.0, m]
        else:
            cur[1] += m

    raw_insights = []
    for mask in range(1 << n):
        idxs = [i for i in range(n) if (mask >> i) & 1]
        agg = {}
        for full_k, (mt, mc) in full_agg.items():
            k = tuple(full_k[i] for i in idxs)
            cur = agg.get(k)
            if cur is None:
                agg[k] = [mt, mc]
            else:
                cur[0] += mt
                cur[1] += mc
        for k, (mt, mc) in agg.items():
            if sum(1 for v in k if v == "__OTHER__") > 1:
                continue
            sup = max(
                mt / tot_test if tot_test else 0.0,
                mc / tot_ctrl if tot_ctrl else 0.0,
            )
            if sup < min_support:
                continue
            diff = mt - mc
            rel_diff = (diff / mc) if mc != 0.0 else None
            t_rest, c_rest = tot_test - mt, tot_ctrl - mc
            if idxs and t_rest == 0.0 and c_rest == 0.0:
                continue
            if t_rest == 0.0 and c_rest == 0.0:
                unexp, rel_unexp = diff, rel_diff
            elif c_rest == 0.0:
                unexp, rel_unexp = None, None
            else:
                unexp = mt - (mc * (t_rest / c_rest))
                rel_unexp = (
                    ((mt / t_rest) * (c_rest / mc) - 1.0)
                    if (t_rest != 0.0 and mc != 0.0)
                    else None
                )
            drv = (
                ["all"]
                if not idxs
                else [
                    f"{d}_is_other" if v == "__OTHER__" else f"{d}={v}"
                    for d, v in sorted(
                        (kept_dims[idxs[j]], k[j]) for j in range(len(idxs))
                    )
                ]
            )
            if drv == ["all"]:
                archetype = "HEADLINE_TOTAL"
            elif overall_diff != 0 and (diff * overall_diff) < 0:
                archetype = "COUNTER_TREND_OFFSET"
            elif rel_unexp is not None and abs(rel_unexp) < 0.015:
                archetype = "TIDE_FOLLOWER"
            elif unexp is not None and overall_diff != 0 and (unexp * overall_diff) < 0:
                archetype = "HIDDEN_DRAG"
            elif sup < 0.20 and rel_unexp is not None and abs(rel_unexp) >= 0.08:
                archetype = "OUTLIER_SURGE"
            else:
                archetype = "PRIMARY_ACCELERATOR"

            raw_insights.append(
                {
                    "drivers": drv,
                    "archetype": archetype,
                    "metric_test": round(mt, 2),
                    "metric_control": round(mc, 2),
                    "difference": round(diff, 2),
                    "relative_difference": round(rel_diff, 4)
                    if rel_diff is not None
                    else None,
                    "unexpected_difference": round(unexp, 2)
                    if unexp is not None
                    else None,
                    "relative_unexpected_difference": round(rel_unexp, 4)
                    if rel_unexp is not None
                    else None,
                    "apriori_support": round(sup, 4),
                    "contribution": round(abs(diff), 2),
                    "share_of_total_change": round(diff / overall_diff, 4)
                    if overall_diff != 0
                    else None,
                }
            )

    groups = {}
    for ins in raw_insights:
        fp = (
            ins["metric_test"],
            ins["metric_control"],
            ins["difference"],
            ins["apriori_support"],
        )
        groups.setdefault(fp, []).append(ins)

    pruned = []
    for grp in groups.values():
        if len(grp) == 1:
            pruned.append(grp[0])
            continue
        grp_sorted = sorted(grp, key=lambda x: len(x["drivers"]))
        for i, cur in enumerate(grp_sorted):
            if cur["drivers"] == ["all"] or not any(
                len(cur["drivers"]) < len(o["drivers"])
                and set(cur["drivers"]).issubset(set(o["drivers"]))
                for o in grp_sorted[i + 1 :]
            ):
                pruned.append(cur)

    pruned.sort(key=lambda x: x["contribution"], reverse=True)
    return {
        "status": "SUCCESS",
        "dimensions": kept_dims,
        "dropped_null_rows": {"test": drop_test, "control": drop_ctrl},
        "drivers": pruned[:top_k] if top_k else pruned,
    }


def run_key_driver_analysis(body=None, transport_options=None):
    """Analyze Key Drivers with automatic API 4.0 query slug resolution, colliding timeframe filter stripping, and Looker 26.20-26.22 HTTP 422 fallback."""
    payload = dict(body or {})
    ds = dict(payload.get("data_source") or {})
    base = dict(payload.get("base_filters") or {})
    baseline = dict(payload.get("baseline_filters") or {})
    breach = dict(payload.get("breach_filters") or {})

    # Fix #1: Never send string query_id to /internal/kda/analyze
    if ds.get("query_id") and (not ds.get("model_name") or not ds.get("explore_name")):
        q = _resolve_query_id_or_slug(ds["query_id"])
        ds = {"model_name": q["model"], "explore_name": q["view"]}
        q_flts = dict(q.get("filters") or {})
        q_flts.update(base)
        base = q_flts
    elif "query_id" in ds and ds.get("model_name") and ds.get("explore_name"):
        ds.pop("query_id", None)

    if any(_is_time_field(k) for k in list(baseline.keys()) + list(breach.keys())):
        base = {k: v for k, v in base.items() if not _is_time_field(k)}

    clean_body = {
        "data_source": ds,
        "contribution_metric": payload.get("contribution_metric"),
        "dimensions": list(payload.get("dimensions") or [])[:6],
        "base_filters": base,
        "baseline_filters": baseline,
        "breach_filters": breach,
    }
    try:
        res = _raw_run_key_driver_analysis(clean_body, transport_options)
        if res and res.get("drivers") is not None:
            return res
    except Exception as exc:
        err_s = str(exc)
        if (
            "422" not in err_s
            and "status" not in err_s
            and "KdaResponse" not in err_s
            and "ValidationError" not in err_s
        ):
            raise

    return _kda_fallback_422(
        model_name=ds.get("model_name"),
        explore_name=ds.get("explore_name"),
        contribution_metric=clean_body["contribution_metric"],
        dimensions=clean_body["dimensions"],
        base_filters=base,
        baseline_filters=baseline,
        breach_filters=breach,
    )


def _json_dumps(v):
    if v is None or isinstance(v, bool):
        return "null" if v is None else ("true" if v else "false")
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{esc}"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_json_dumps(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_json_dumps(str(k))}: {_json_dumps(val)}" for k, val in v.items()) + "}"
    return _json_dumps(str(v))


def _json_loads(s):
    n = len(s)

    def _ws(i):
        while i < n and s[i] in " \t\r\n":
            i += 1
        return i

    def _str(i):
        i += 1
        out = []
        while i < n and s[i] != '"':
            if s[i] == "\\":
                i += 1
                out.append({"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(s[i], s[i]))
            else:
                out.append(s[i])
            i += 1
        return "".join(out), i + 1

    def _val(i):
        i = _ws(i)
        if s[i] == '"':
            return _str(i)
        if s[i] == "[":
            arr, i = [], _ws(i + 1)
            while i < n and s[i] != "]":
                v, i = _val(i)
                arr.append(v)
                i = _ws(i)
                if i < n and s[i] == ",":
                    i = _ws(i + 1)
            return arr, i + 1
        if s[i] == "{":
            obj, i = {}, _ws(i + 1)
            while i < n and s[i] != "}":
                k, i = _str(_ws(i))
                v, i = _val(_ws(i) + 1)
                obj[k] = v
                i = _ws(i)
                if i < n and s[i] == ",":
                    i = _ws(i + 1)
            return obj, i + 1
        for lit, val in (("true", True), ("false", False), ("null", None)):
            if s.startswith(lit, i):
                return val, i + len(lit)
        j = i
        while j < n and s[j] not in " \t\r\n,]}":
            j += 1
        tok = s[i:j]
        return (float(tok) if ("." in tok or "e" in tok or "E" in tok) else int(tok)), j

    return _val(0)[0]


def _clone(x):
    if isinstance(x, dict):
        return {k: _clone(v) for k, v in x.items()}
    return [_clone(v) for v in x] if isinstance(x, list) else x


def _parse_dyn_items(raw):
    if isinstance(raw, str):
        if not (s := raw.strip()):
            return []
        try:
            raw = _json_loads(s)
        except Exception:  # noqa: BLE001
            return []
    return [dict(d) for d in raw if isinstance(d, dict)] if isinstance(raw, list) else []


def _sql_alias(name):
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in str(name))


def _strip_trailing_limit(sql):
    toks = sql.rstrip().rsplit(None, 2)
    if len(toks) >= 2 and toks[-2].upper() == "LIMIT" and toks[-1].isdigit():
        return sql[: sql.upper().rfind("LIMIT")].rstrip()
    return sql


def _rewrite_tc_expr(expr, field_origin):
    parts = str(expr).split("${")
    out = [parts[0]]
    for part in parts[1:]:
        if "}" in part:
            ref, rest = part.split("}", 1)
            colon = ref.strip().split(":", 1)
            if (base := colon[0].strip()) in field_origin:
                sfx = (":" + colon[1]) if len(colon) > 1 else ""
                out.append(f"${{sql_runner_query.{field_origin[base][1]}{sfx}}}{rest}")
                continue
        out.append("${" + part)
    return "".join(out)


def _warn_query(msg):
    try:
        _warn_sdk_query(msg)
    except Exception:  # noqa: BLE001
        print("WARNING: " + str(msg))


def execute_looker_query(spec, transport_options=None):
    """Execute one or more Looker queries with SQL CTE joins and SQL Runner / Python fallback."""
    spec_dict = {"source_queries": spec} if isinstance(spec, list) and spec else (spec or {})

    def _parse_rows(raw, ctx=""):
        res = _json_loads(raw.strip()) if isinstance(raw, str) and raw.strip() else raw
        if isinstance(res, dict) and ("errors" in res or "message" in res):
            raise RuntimeError(f"Looker query error ({ctx}): {res}")
        return res if isinstance(res, list) else []

    def _run_json(q):
        body = q.get("body", q)
        return _parse_rows(run_inline_query("json", body), str(body.get("view")))

    if not isinstance(spec_dict, dict) or not spec_dict:
        raise ValueError("At least one query is required")
    if "source_queries" not in spec_dict:
        body0 = spec_dict.get("body", spec_dict)
        if not isinstance(body0, dict) or (not body0.get("view") and not body0.get("fields")):
            raise ValueError("At least one query is required")
        return _run_json(spec_dict)

    raw_sqs = spec_dict["source_queries"]
    if not isinstance(raw_sqs, list) or not raw_sqs:
        raise ValueError("At least one query is required in source_queries")
    if len(raw_sqs) == 1:
        sq0 = raw_sqs[0] if isinstance(raw_sqs[0], dict) else {}
        return _run_json(sq0.get("query", sq0))

    q_bodies = []
    warned_src_tc = False
    for sq in raw_sqs:
        q_raw = sq.get("query", sq) if isinstance(sq, dict) else {}
        qb = _clone(q_raw.get("body", q_raw) if isinstance(q_raw, dict) else {})
        dyn = _parse_dyn_items(qb.get("dynamic_fields"))
        tc_names = {d["table_calculation"] for d in dyn if isinstance(d.get("table_calculation"), str)}
        if tc_names:
            if not warned_src_tc:
                _warn_query("Table calculations on source queries are ignored when merging multiple queries.")
                warned_src_tc = True
            kept = [d for d in dyn if "table_calculation" not in d]
            qb.update(dynamic_fields=_json_dumps(kept)) if kept else qb.pop("dynamic_fields", None)
            if isinstance(qb.get("fields"), list):
                qb["fields"] = [f for f in qb["fields"] if f not in tc_names]
            if isinstance(qb.get("sorts"), list):
                qb["sorts"] = [s for s in qb["sorts"] if str(s).split()[0] not in tc_names]
        q_bodies.append(qb)

    final_tcs = []
    for d in _parse_dyn_items(spec_dict.get("dynamic_fields")) + _parse_dyn_items(spec_dict.get("table_calculations")):
        if "table_calculation" not in d and isinstance(d.get("name"), str) and "dimension" not in d and "measure" not in d:
            d = {**d, "table_calculation": d["name"]}
        if isinstance(d.get("table_calculation"), str) and d["table_calculation"]:
            d.setdefault("label", d["table_calculation"])
            final_tcs.append(d)

    needs_total = bool(spec_dict.get("total")) or any(":total" in str(tc.get("expression", "")) for tc in final_tcs)
    if needs_total:
        for qb in q_bodies:
            qb["total"] = True

    p0_fields = q_bodies[0].get("fields") or []
    joins_meta = [
        (
            (sq.get("merge_fields") if isinstance(sq, dict) else None)
            or [{"field_name": f, "source_field_name": f} for f in p0_fields if f in (q_bodies[idx].get("fields") or [])],
            str((sq.get("join_type") if isinstance(sq, dict) else None) or spec_dict.get("join_type") or "left").lower(),
        )
        for idx, sq in enumerate(raw_sqs[1:], start=1)
    ]

    try:
        if create_sql_query is None or run_sql_query is None:
            raise RuntimeError("SQL Runner methods unavailable on SDK")

        ctes = []
        field_origin = {}
        alias_to_field = {}
        for idx, qb in enumerate(q_bodies):
            for f in qb.get("fields") or []:
                if isinstance(f, str) and f not in field_origin:
                    alias = _sql_alias(f)
                    field_origin[f] = (idx, alias)
                    alias_to_field[alias] = f
                    alias_to_field[alias.lower()] = f
            raw_sql = run_inline_query("sql", qb)
            if not isinstance(raw_sql, str) or not raw_sql.strip() or raw_sql.lstrip().startswith(("{", "[")):
                raise RuntimeError(f"Expected SQL string from run_inline_query, got: {raw_sql!r}")
            sql = raw_sql.strip().rstrip(";").strip()
            if str(qb.get("limit", spec_dict.get("limit", ""))).strip() == "-1":
                sql = _strip_trailing_limit(sql)
            ctes.append(f"cte_{idx} AS (\n{sql}\n)")

        joins = []
        for idx, (mfields, jtype) in enumerate(joins_meta, start=1):
            if not mfields:
                raise ValueError(f"source_queries[{idx}] is missing merge_fields")
            on_sql = " AND ".join(
                f"cte_0.{_sql_alias(m['field_name'])} = cte_{idx}.{_sql_alias(m['source_field_name'])}"
                for m in mfields
            )
            joins.append(f"{'INNER JOIN' if jtype == 'inner' else 'LEFT JOIN'} cte_{idx} ON {on_sql}")

        projected = _uniq([f for f in (spec_dict.get("fields") or []) if f in field_origin] + list(field_origin.keys()))
        select_sql = ", ".join(f"cte_{field_origin[f][0]}.{field_origin[f][1]} AS {field_origin[f][1]}" for f in projected)
        sql_lines = [f"WITH {', '.join(ctes)}", f"SELECT {select_sql}", f"FROM cte_0 {' '.join(joins)}"]

        if not final_tcs:
            order_cols = [
                f"{field_origin[c][1] if (c := s.strip().split()[0]) in field_origin else _sql_alias(c)} {'DESC' if len(s.strip().split()) > 1 and s.strip().split()[1].lower() == 'desc' else 'ASC'}"
                for s in (spec_dict.get("sorts") or [])
                if isinstance(s, str) and s.strip() and s != "__UNSORTED__"
            ]
            if order_cols:
                sql_lines.append(f"ORDER BY {', '.join(order_cols)}")
            if (lim_val := spec_dict.get("limit")) is not None and str(lim_val).strip() not in ("", "-1"):
                sql_lines.append(f"LIMIT {int(lim_val)}")

        merged_sql = "\n".join(sql_lines)
        model = spec_dict.get("model") or q_bodies[0].get("model")
        if conn := spec_dict.get("connection_name"):
            sql_q = create_sql_query(body={"connection_name": conn, "sql": merged_sql})
        else:
            try:
                sql_q = create_sql_query(body={"model_name": model, "sql": merged_sql})
            except Exception:
                if not model or lookml_model_explore is None:
                    raise
                exp = lookml_model_explore(model, q_bodies[0].get("view", ""), fields="connection_name")
                conn_fb = exp.get("connection_name") if isinstance(exp, dict) else getattr(exp, "connection_name", None)
                if not conn_fb:
                    raise
                sql_q = create_sql_query(body={"connection_name": conn_fb, "sql": merged_sql})

        slug = sql_q.get("slug") if isinstance(sql_q, dict) else getattr(sql_q, "slug", None)
        if not slug:
            raise RuntimeError("create_sql_query did not return a slug")

        def _remap(rows):
            return [{alias_to_field.get(s := k.removeprefix("sql_runner_query."), alias_to_field.get(s.lower(), k)): v for k, v in r.items()} for r in rows]

        sql_rows = _parse_rows(run_sql_query(slug=slug, result_format="json"), f"sql:{slug}")
        if not final_tcs:
            return _remap(sql_rows)

        rewritten_tcs = []
        for tc in final_tcs:
            tc_c = dict(tc)
            if isinstance(expr := tc_c.get("expression"), str):
                tc_c["expression"] = _rewrite_tc_expr(expr, field_origin)
            for fk in ("based_on", "source_field"):
                if isinstance(fv := tc_c.get(fk), str) and fv in field_origin:
                    tc_c[fk] = f"sql_runner_query.{field_origin[fv][1]}"
            if isinstance(args := tc_c.get("args"), list):
                tc_c["args"] = [f"sql_runner_query.{field_origin[a][1]}" if isinstance(a, str) and a in field_origin else a for a in args]
            rewritten_tcs.append(tc_c)

        explore_body = {
            "model": f"sql__{slug}",
            "view": "sql_runner_query",
            "fields": [f"sql_runner_query.{field_origin[f][1]}" for f in projected],
            "dynamic_fields": _json_dumps(rewritten_tcs),
        }
        if needs_total:
            explore_body["total"] = True
        if spec_dict.get("sorts"):
            explore_body["sorts"] = [
                f"sql_runner_query.{field_origin[p[0]][1]}{' ' + p[1] if len(p) > 1 else ''}"
                if isinstance(s, str) and (p := s.strip().split(None, 1)) and p[0] in field_origin
                else s
                for s in spec_dict["sorts"]
            ]
        if spec_dict.get("limit") is not None:
            explore_body["limit"] = str(spec_dict["limit"])

        return _remap(_parse_rows(run_inline_query("json", explore_body), f"sql__{slug}"))
    except Exception:  # noqa: BLE001
        _warn_query("SQL Runner merge unavailable; falling back to Python merge with source query row limits applied.")
        if final_tcs:
            _warn_query("Python merge fallback cannot process table calculations; table calculations were ignored.")

    sub_results = [_run_json(qb) for qb in q_bodies]
    merged_rows = [dict(r) for r in sub_results[0]]
    for idx, (mfields, join_type) in enumerate(joins_meta, start=1):
        sec_rows = sub_results[idx]
        lookup = {}
        for sr in sec_rows:
            raw_key = tuple(sr.get(m["source_field_name"]) for m in mfields)
            if None not in raw_key:
                lookup.setdefault(tuple(str(k) for k in raw_key), []).append(sr)

        null_pad = dict.fromkeys(sec_rows[0]) if sec_rows else {}
        next_merged = []
        for pr in merged_rows:
            raw_key = tuple(pr.get(m["field_name"]) for m in mfields)
            if None not in raw_key and (matches := lookup.get(tuple(str(k) for k in raw_key))):
                for sr in matches:
                    next_merged.append({**sr, **pr})
            elif join_type != "inner":
                next_merged.append({**null_pad, **pr})
        merged_rows = next_merged

    for s in reversed(spec_dict.get("sorts") or []):
        if isinstance(s, str) and s.strip() and s != "__UNSORTED__":
            parts = s.strip().split()
            col, desc = parts[0], len(parts) > 1 and parts[1].lower() == "desc"
            merged_rows.sort(
                key=lambda r, c=col: (r.get(c) is None, r.get(c) if r.get(c) is not None else ""),
                reverse=desc,
            )

    limit = int(spec_dict["limit"]) if spec_dict.get("limit") else -1
    return merged_rows[:limit] if limit >= 0 else merged_rows
