from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from typing import cast

from lkr.codemode.type import to_primitive
from lkr.logger import logger

_DictFn = Callable[..., dict[str, object]]
_ListDictFn = Callable[..., list[dict[str, object]]]

query: _DictFn = cast(_DictFn, None)
query_for_slug: _DictFn = cast(_DictFn, None)
merge_query: _DictFn = cast(_DictFn, None)
dashboard: _DictFn = cast(_DictFn, None)
look: _DictFn = cast(_DictFn, None)
get_conversation: _DictFn = cast(_DictFn, None)
all_conversation_messages: _ListDictFn = cast(_ListDictFn, None)
lookml_model_explore: _DictFn = cast(_DictFn, None)
run_inline_query: Callable[..., object] = cast(Callable[..., object], None)
create_sql_query: _DictFn | None = None
run_sql_query: Callable[..., object] | None = None
_raw_run_key_driver_analysis: _DictFn = cast(_DictFn, None)


def _warn_sdk_query(msg: str) -> None:
    warnings.warn(msg, UserWarning, stacklevel=3)
    logger.warning(msg)


def _bind_sdk(sdk: object, transport_options: object = None) -> None:
    global query, query_for_slug, merge_query, dashboard, look
    global get_conversation, all_conversation_messages, lookml_model_explore
    global run_inline_query, create_sql_query, run_sql_query, _raw_run_key_driver_analysis

    def _wrap(attr: str, *, raw: bool = False) -> Callable[..., object] | None:
        fn = getattr(sdk, attr, None)
        if fn is None:
            return None

        def _inner(*a: object, **kw: object) -> object:
            assert fn is not None
            if transport_options is not None and "transport_options" not in kw:
                kw["transport_options"] = transport_options
            res = fn(*a, **kw)
            return res if raw else to_primitive(res)

        return _inner

    def _wrap_dict(attr: str) -> _DictFn:
        return cast(_DictFn, _wrap(attr))

    query = _wrap_dict("query")
    query_for_slug = _wrap_dict("query_for_slug")
    merge_query = _wrap_dict("merge_query")
    dashboard = _wrap_dict("dashboard")
    look = _wrap_dict("look")
    get_conversation = _wrap_dict("get_conversation")
    all_conversation_messages = cast(_ListDictFn, _wrap("all_conversation_messages"))
    lookml_model_explore = _wrap_dict("lookml_model_explore")
    create_sql_query = cast("_DictFn | None", _wrap("create_sql_query"))
    run_sql_query = _wrap("run_sql_query")
    raw_inline = _wrap("run_inline_query", raw=True)
    post_fn = cast("Callable[..., object]", getattr(sdk, "post", None))
    prep_fn = cast("Callable[[object], object]", getattr(sdk, "_prepare_body", None))

    def _run_inline(result_format: str, body: object, **kw: object) -> object:
        assert raw_inline is not None
        raw = raw_inline(result_format, body, **kw)
        if isinstance(raw, str):
            if result_format not in ("json", "json_detail", "json_bi"):
                return raw
            s = raw.strip()
            return json.loads(s) if s else ([] if result_format == "json" else {})
        return to_primitive(raw)

    def _raw_kda(body: object, topts: object = None) -> dict[str, object]:
        opts = topts if topts is not None else transport_options
        return cast(
            dict[str, object],
            to_primitive(
                post_fn(
                    path="/internal/kda/analyze",
                    structure=dict,
                    body=prep_fn(body),
                    transport_options=opts,
                )
            ),
        )

    run_inline_query = _run_inline
    _raw_run_key_driver_analysis = _raw_kda


def _normalize_data_app(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        return {}
    ctx = data.get("context")
    if ctx is None:
        data["context"] = {}
    elif isinstance(ctx, str):
        data["context"] = json.loads(ctx) if ctx.strip() else {}
    return data


def _serialize_data_app_body(request_body: object) -> object:
    if isinstance(request_body, dict) and "context" in request_body and not isinstance(request_body["context"], str):
        ctx_val = request_body["context"]
        return {
            **request_body,
            "context": json.dumps({} if ctx_val is None else ctx_val),
        }
    return request_body


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


def _as_dict(v: object) -> dict[str, object]:
    return v if isinstance(v, dict) else {}


def _as_dicts(v: object) -> list[dict[str, object]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _as_strs(v: object) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _uniq(seq: list[str]) -> list[str]:
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _is_time_field(field_name: object) -> bool:
    s = str(field_name or "")
    return any(s.endswith(suf) for suf in TIME_SUFFIXES)


def _extract_refs(sql: object, default_view: object) -> list[str]:
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


def _table_col(sql: object, view: object) -> str | None:
    s = str(sql or "").strip().rstrip(";").strip()
    for pfx in ("${TABLE}.", f"{view}."):
        if s.startswith(pfx):
            col = s[len(pfx) :].strip('`"[] ')
            if col and all(c.isalnum() or c == "_" for c in col):
                return f"{view}.{col}"
    return None


def _resolve_query_id_or_slug(qid: object) -> dict[str, object]:
    s = str(qid).strip()
    if s.isdigit():
        try:
            q = query(s)
            if q and q.get("model") and q.get("view"):
                return q
        except Exception:  # noqa: BLE001, S110
            pass
    return query_for_slug(s)


def _expand_merge_query(
    mid: object,
    title_prefix: str = "",
    filterables: list[dict[str, object]] | None = None,
    df_vals: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    mq = merge_query(str(mid)) or {}
    targets = []
    flts_list = filterables or []
    d_vals = df_vals or {}
    for idx, sq in enumerate(_as_dicts(mq.get("source_queries"))):
        sq_q = _resolve_query_id_or_slug(sq.get("query_id"))
        if not sq_q or not sq_q.get("model") or not sq_q.get("view"):
            continue
        tf = dict(_as_dict(sq_q.get("filters")))
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
            for lsn in _as_dicts(flt.get("listen")):
                fn, fld = lsn.get("dashboard_filter_name"), lsn.get("field")
                if isinstance(fn, str) and fn and isinstance(fld, str) and fld:
                    listens[fn] = fld
                    if d_vals.get(fn):
                        tf[fld] = d_vals[fn]
        m_dims = [
            sf
            for mf in _as_dicts(sq.get("merge_fields"))
            if isinstance((sf := mf.get("source_field_name")), str) and sf
        ]
        q_fields = _uniq(m_dims + _as_strs(sq_q.get("fields")))
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
    target: object = None,
    model_name: str | None = None,
    explore_name: str | None = None,
    fields: list[str] | None = None,
    filters: dict[str, str] | dict[str, object] | None = None,
    tile_filter: str | list[str] | None = None,
) -> tuple[str, list[dict[str, object]]]:
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

    def _query_to_target(
        q: dict[str, object],
        title: str | None = None,
        slug_fallback: str | None = None,
    ) -> dict[str, object]:
        tf = dict(_as_dict(q.get("filters")))
        tf.update(url_flts)
        return {
            "title": title or f"{q['model']}::{q['view']}",
            "model": q["model"],
            "explore": q["view"],
            "fields": _as_strs(q.get("fields")),
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
            dn: df.get("default_value")
            for df in _as_dicts(d.get("dashboard_filters"))
            if isinstance((dn := df.get("name")), str)
            and dn
            and df.get("default_value")
        }
        df_vals.update(url_params)
        tiles = []
        for e in _as_dicts(d.get("dashboard_elements")):
            rm = _as_dict(e.get("result_maker"))
            q = e.get("query") or rm.get("query")
            mid = e.get("merge_result_id") or rm.get("merge_result_id")
            if mid and not q:
                tiles.extend(
                    _expand_merge_query(
                        mid,
                        title_prefix=str(e.get("title") or e.get("id")),
                        filterables=_as_dicts(rm.get("filterables")),
                        df_vals=df_vals,
                    )
                )
                continue
            if not isinstance(q, dict) or not q.get("model") or not q.get("view"):
                continue
            tf = dict(_as_dict(q.get("filters")))
            listens = {}
            for flt in _as_dicts(rm.get("filterables")):
                for lsn in _as_dicts(flt.get("listen")):
                    fn, fld = lsn.get("dashboard_filter_name"), lsn.get("field")
                    if isinstance(fn, str) and fn and isinstance(fld, str) and fld:
                        listens[fn] = fld
                        if df_vals.get(fn):
                            tf[fld] = df_vals[fn]
            tiles.append(
                {
                    "title": e.get("title") or str(e.get("id")),
                    "model": q["model"],
                    "explore": q["view"],
                    "fields": _as_strs(q.get("fields")),
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
                raw_q = lk.get("query")
                q = (
                    raw_q
                    if isinstance(raw_q, dict)
                    else _resolve_query_id_or_slug(lk["query_id"])
                )
                return (
                    "look",
                    [_query_to_target(q, title=str(lk.get("title") or f"Look {lid}"))],
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
            msg = _as_dict(m.get("message"))
            if m.get("type") == "user":
                cur_q = _as_dict(msg.get("userMessage")).get("text")
            gq = _as_dict(_as_dict(msg.get("systemMessage")).get("data")).get(
                "generatedLookerQuery"
            )
            if (
                isinstance(gq, dict)
                and gq.get("model")
                and (gq.get("explore") or gq.get("view"))
            ):
                raw_flts = gq.get("filters") or []
                if isinstance(raw_flts, dict):
                    flts = dict(raw_flts)
                else:
                    flts = {
                        ff: str(fi.get("value", ""))
                        for fi in _as_dicts(raw_flts)
                        if isinstance((ff := fi.get("field")), str) and ff
                    }
                turns.append(
                    {
                        "title": cur_q or f"Turn {len(turns) + 1}",
                        "model": gq["model"],
                        "explore": gq.get("explore") or gq.get("view"),
                        "fields": _as_strs(gq.get("fields")),
                        "filters": flts,
                        "slug": None,
                        "merge_fields": [],
                        "filter_listens": {},
                    }
                )
        raw_sources = c.get("sources") if c else None
        if not turns and c and isinstance(raw_sources, list) and raw_sources:
            src = _as_dict(raw_sources[0])
            turns.append(
                {
                    "title": c.get("name") or "Conversation",
                    "model": src.get("model"),
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


def _decompile_single_target(
    tgt: dict[str, object], exp: dict[str, object] | None
) -> dict[str, object]:
    exp = _as_dict(exp)
    model_name, explore_name = tgt["model"], tgt["explore"]
    base_view = str(exp.get("view_name") or explore_name)
    flds = _as_dict(exp.get("fields"))
    dims = _as_dicts(flds.get("dimensions"))
    meas = _as_dicts(flds.get("measures"))
    joins = _as_dicts(exp.get("joins"))
    sets_list = _as_dicts(exp.get("sets"))

    dims_by_name = {
        dn: d
        for d in dims
        if isinstance((dn := d.get("name")), str) and dn
    }
    meas_by_name = {
        mn: m
        for m in meas
        if isinstance((mn := m.get("name")), str) and mn
    }

    inner_joins = {
        jn
        for j in joins
        if j.get("type") == "inner" and isinstance((jn := j.get("name")), str) and jn
    }
    liquid_views = {
        fv
        for f in (dims + meas)
        if isinstance((fv := f.get("view")), str)
        and fv
        and "{%" in str(f.get("sql") or "")
    }
    bad_views = inner_joins | liquid_views

    # Conditional / role-playing left_outer joins (e.g. product_viewed on events)
    conditional_joins = {}
    for j in joins:
        j_name = j.get("name")
        if not isinstance(j_name, str) or not j_name or j_name in bad_views:
            continue
        dep_flds = _as_strs(j.get("dependent_fields")) or _extract_refs(
            j.get("sql_on"), j_name
        )
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
    sum_by_dim: dict[str, list[str]] = {}
    count_by_view: dict[str, list[str]] = {}
    dim_by_table_col: dict[str, list[str]] = {}
    for d in dims:
        d_name, d_view = d.get("name"), str(d.get("view") or base_view)
        tc = _table_col(d.get("sql"), d_view)
        if isinstance(d_name, str) and d_name and tc and not d.get("is_timeframe"):
            dim_by_table_col.setdefault(tc, []).append(d_name)

    for m in meas:
        m_name = m.get("name")
        m_view = str(m.get("view") or base_view)
        m_type = m.get("type") or ""
        if not isinstance(m_name, str) or not m_name or m_view in bad_views or m.get("filters"):
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
    q_fields = _as_strs(tgt.get("fields"))
    q_measures = [f for f in q_fields if f in meas_by_name]
    if not q_measures:
        default_meas = [
            mn
            for m in meas
            if isinstance((mn := m.get("name")), str)
            and mn
            and not m.get("hidden")
            and m.get("type") in ("sum", "count", "sum_distinct")
            and m.get("view") not in bad_views
        ]
        q_measures = default_meas[:1]

    # Decompile each measure via recursive ${...} walk
    decompiled_measures = {}
    all_target_leaf_dims: set[str] = set()
    touched_views = {base_view}
    measure_drill_pool: list[str] = []

    def _walk_refs(
        sql_expr: object,
        cur_view: object,
        visited: set[str],
        ref_measures: list[str],
        derived_dims: list[dict[str, object]],
        leaf_dims: list[str],
    ) -> None:
        for ref in _extract_refs(sql_expr, cur_view):
            if ref in visited:
                continue
            visited.add(ref)
            if ref in meas_by_name:
                rm = meas_by_name[ref]
                rm_view = str(rm.get("view") or cur_view)
                touched_views.add(rm_view)
                ref_measures.append(ref)
                measure_drill_pool.extend(_as_strs(rm.get("drill_fields")))
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
                rd_view = str(rd.get("view") or cur_view)
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
        m_view = str(m_obj.get("view") or base_view)
        m_type = m_obj.get("type") or ""
        m_sql = str(m_obj.get("sql") or "").strip()
        touched_views.add(m_view)
        measure_drill_pool.extend(_as_strs(m_obj.get("drill_fields")))

        ref_measures: list[str] = []
        derived_dims: list[dict[str, object]] = []
        leaf_dims: list[str] = []
        _walk_refs(m_sql, m_view, {m_name}, ref_measures, derived_dims, leaf_dims)
        if not leaf_dims and not ref_measures:
            tc = _table_col(m_sql, m_view)
            if tc:
                for dn in dim_by_table_col.get(tc, []):
                    if dn not in leaf_dims:
                        leaf_dims.append(dn)

        leaf_entries = []
        unmodeled = []
        matched_order: list[str] = []
        for dd in derived_dims:
            all_target_leaf_dims.add(str(dd["dimension"]))
            for mm in _as_strs(dd.get("matched_additive_measures")):
                if mm not in matched_order:
                    matched_order.append(mm)
        for ld_name in leaf_dims:
            all_target_leaf_dims.add(ld_name)
            ld_obj = dims_by_name.get(ld_name) or {}
            ld_view = str(ld_obj.get("view") or base_view)
            ld_sql = str(ld_obj.get("sql") or "").strip()
            matched = _uniq(sum_by_dim.get(ld_name, []))
            for mm in matched:
                if mm not in matched_order:
                    matched_order.append(mm)
                measure_drill_pool.extend(
                    _as_strs((meas_by_name.get(mm) or {}).get("drill_fields"))
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
    def _dim_touches_leaf(d_name: str) -> bool:
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

    def _is_valid_driver_dim(
        d_name: str, allow_yesno_tier: bool = False
    ) -> bool:
        d = dims_by_name.get(d_name)
        if not d:
            return False
        dtype = str(d.get("type") or "string")
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

    def _macro_rank(d_name: str) -> tuple[int, int, str]:
        low = d_name.lower()
        for idx, tok in enumerate(MACRO_TOKENS):
            if low.endswith(("." + tok, "_" + tok)):
                return (0 if d_name.startswith(base_view + ".") else 1, idx, d_name)
        return (2 if d_name.startswith(base_view + ".") else 3, 99, d_name)

    # Timeframes & Filter split
    all_timeframes = [
        dn
        for d in dims
        if d.get("is_timeframe") and isinstance((dn := d.get("name")), str) and dn
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

    raw_filters = dict(_as_dict(tgt.get("filters")))
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
        measure_drill_pool.extend(
            _as_strs((meas_by_name.get(vm) or {}).get("drill_fields"))
        )
    for qf in q_fields:
        measure_drill_pool.extend(
            _as_strs((dims_by_name.get(qf) or {}).get("drill_fields"))
        )
    for s_entry in sets_list:
        s_name = str(s_entry.get("name") or "")
        s_view = s_name.split(".", 1)[0] if "." in s_name else base_view
        if s_view not in bad_views and s_view not in conditional_joins:
            measure_drill_pool.extend(_as_strs(s_entry.get("value")))

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
        if not isinstance(dn, str) or not dn or dn in seen_cands or dn in base_filters:
            continue
        dv = str(d.get("view") or base_view)
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
                str(d.get("view") or base_view)
                for d in dims
                if (d.get("view") or base_view) not in bad_views
            }
        ),
        "_filter_listens": tgt.get("filter_listens") or {},
        "_merge_fields": tgt.get("merge_fields") or [],
    }


def decompile_kda_target(
    target: object = None,
    model_name: str | None = None,
    explore_name: str | None = None,
    fields: list[str] | None = None,
    filters: dict[str, str] | dict[str, object] | None = None,
    tile_filter: str | list[str] | None = None,
) -> dict[str, object]:
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
            rt["fields"] = _uniq(_as_strs(rt.get("fields")) + list(fields))
        if filters:
            merged_flts = dict(_as_dict(rt.get("filters")))
            merged_flts.update(filters)
            rt["filters"] = merged_flts
        key = (str(rt["model"]), str(rt["explore"]))
        if key not in explore_cache:
            explore_cache[key] = lookml_model_explore(rt["model"], rt["explore"])
        compiled_targets.append(_decompile_single_target(rt, explore_cache[key]))

    overlaps = []
    if len(explore_cache) > 1:
        views_by_exp = {}
        dims_by_exp = {}
        tframes_by_exp = {}
        filter_map: dict[str, dict[str, object]] = {}
        merge_keys = []
        for ct in compiled_targets:
            ds_obj = _as_dict(ct.get("data_source"))
            ek = f"{ds_obj.get('model_name')}::{ds_obj.get('explore_name')}"
            cands = _as_dict(ct.get("candidate_dimensions"))
            all_d = (
                _as_strs(cands.get("query_dimensions"))
                + _as_strs(cands.get("drill_dimensions"))
                + _as_strs(cands.get("entity_dimensions"))
            )
            if ek not in views_by_exp:
                views_by_exp[ek] = _as_strs(ct.get("_views"))
                dims_by_exp[ek] = list(all_d)
                tframes_by_exp[ek] = _as_strs(ct.get("available_timeframes"))
            for fn, fld in _as_dict(ct.get("_filter_listens")).items():
                filter_map.setdefault(fn, {})[ek] = fld
            for mf in _as_strs(ct.get("_merge_fields")):
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
    model_name: object,
    explore_name: object,
    contribution_metric: object,
    dimensions: list[str] | None,
    base_filters: dict[str, object] | None,
    baseline_filters: dict[str, object] | None,
    breach_filters: dict[str, object] | None,
    min_support: float = 0.05,
    top_k: int = 5,
) -> dict[str, object]:
    # ponytail: BQML-parity fallback for Looker 26.20-26.22 KdaResponse::Success.status 422 bug
    dims = list(dimensions or [])[:6]
    cm = str(contribution_metric or "")
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

    def _q(flds: list[str], flts: dict[str, object]) -> list[dict[str, object]]:
        res = (
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
        return _as_dicts(res)

    if fold_key:
        q_flts = dict(base)
        q_flts[fold_key] = f"{b_ctrl[fold_key]},{b_test[fold_key]}"
        all_rows = _q(_uniq([fold_key] + dims + [cm]), q_flts)
        vc_str, vt_str = str(b_ctrl[fold_key]).strip(), str(b_test[fold_key]).strip()
        ctrl_rows = [r for r in all_rows if str(r.get(fold_key)) == vc_str]
        test_rows = [r for r in all_rows if str(r.get(fold_key)) == vt_str]
    else:
        q_fields = _uniq(dims + [cm])
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

    def _prep(
        rows: list[dict[str, object]],
    ) -> tuple[list[tuple[list[str], float]], float, int]:
        out, tot, dropped = [], 0.0, 0
        for r in rows:
            if any(r.get(d) is None for d in kept_dims):
                dropped += 1
                continue
            vals = []
            for d in kept_dims:
                val_str = str(r.get(d))
                vals.append(val_str if val_str in allowed[d] else "__OTHER__")
            m = float(str(r.get(cm) or 0.0))
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


def run_key_driver_analysis(
    body: dict[str, object] | None = None,
    transport_options: object = None,
) -> dict[str, object]:
    """Analyze Key Drivers with automatic API 4.0 query slug resolution, colliding timeframe filter stripping, and Looker 26.20-26.22 HTTP 422 fallback."""
    payload = dict(body or {})
    ds = dict(_as_dict(payload.get("data_source")))
    base = dict(_as_dict(payload.get("base_filters")))
    baseline = dict(_as_dict(payload.get("baseline_filters")))
    breach = dict(_as_dict(payload.get("breach_filters")))

    # Fix #1: Never send string query_id to /internal/kda/analyze
    if ds.get("query_id") and (not ds.get("model_name") or not ds.get("explore_name")):
        q = _resolve_query_id_or_slug(ds["query_id"])
        ds = {"model_name": q["model"], "explore_name": q["view"]}
        q_flts = dict(_as_dict(q.get("filters")))
        q_flts.update(base)
        base = q_flts
    elif "query_id" in ds and ds.get("model_name") and ds.get("explore_name"):
        ds.pop("query_id", None)

    if any(_is_time_field(k) for k in list(baseline.keys()) + list(breach.keys())):
        base = {k: v for k, v in base.items() if not _is_time_field(k)}

    clean_dims = _as_strs(payload.get("dimensions"))[:6]
    clean_body = {
        "data_source": ds,
        "contribution_metric": payload.get("contribution_metric"),
        "dimensions": clean_dims,
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
        dimensions=clean_dims,
        base_filters=base,
        baseline_filters=baseline,
        breach_filters=breach,
    )


def _json_dumps(v: object) -> str:
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


def _json_loads(s: str) -> object:
    n = len(s)

    def _ws(i: int) -> int:
        while i < n and s[i] in " \t\r\n":
            i += 1
        return i

    def _str(i: int) -> tuple[str, int]:
        i += 1
        out = []
        while i < n and s[i] != '"':
            if s[i] == "\\":
                i += 1
                if s[i] == "u" and i + 4 < n:
                    out.append(chr(int(s[i + 1 : i + 5], 16)))
                    i += 4
                else:
                    out.append({"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(s[i], s[i]))
            else:
                out.append(s[i])
            i += 1
        return "".join(out), i + 1

    def _val(i: int) -> tuple[object, int]:
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


def _clone(x: object) -> object:
    if isinstance(x, dict):
        return {k: _clone(v) for k, v in x.items()}
    return [_clone(v) for v in x] if isinstance(x, list) else x


def _parse_dyn_items(raw: object) -> list[dict[str, object]]:
    if isinstance(raw, str):
        if not (s := raw.strip()):
            return []
        try:
            raw = _json_loads(s)
        except Exception:  # noqa: BLE001
            return []
    return [dict(d) for d in raw if isinstance(d, dict)] if isinstance(raw, list) else []


def _sql_alias(name: object) -> str:
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in str(name))


def _extract_select_aliases(sql: str) -> list[tuple[str, str]]:
    n, i, depth = len(sql), 0, 0
    in_select = False
    cur_start = -1
    items: list[tuple[str, int]] = []
    last_as = -1
    stop_kws = ("FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "UNION", "INTERSECT", "EXCEPT", "QUALIFY", "WINDOW")

    while i < n:
        c = sql[i]
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            nl = sql.find("\n", i + 2)
            i = nl + 1 if nl != -1 else n
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = end + 2 if end != -1 else n
            continue
        if c in ("'", '"', "`"):
            q = c
            i += 1
            while i < n:
                if sql[i] == "\\" and q != "`" and i + 1 < n:
                    i += 2
                elif sql[i] == q:
                    if i + 1 < n and sql[i + 1] == q:
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            if depth > 0:
                depth -= 1
            i += 1
            continue
        if depth == 0:
            if in_select and c == ",":
                items.append((sql[cur_start:i], last_as - cur_start if last_as >= cur_start else -1))
                cur_start = i + 1
                last_as = -1
                i += 1
                continue
            if (c.isalnum() or c == "_") and (i == 0 or (not (sql[i - 1].isalnum() or sql[i - 1] == "_") and sql[i - 1] != ".")):
                j = i + 1
                while j < n and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                kw = sql[i:j].upper()
                if not in_select and kw == "SELECT":
                    in_select = True
                    cur_start = j
                elif in_select and kw in stop_kws and (j == n or sql[j] != "."):
                    items.append((sql[cur_start:i], last_as - cur_start if last_as >= cur_start else -1))
                    in_select = False
                    break
                elif in_select and kw == "AS":
                    last_as = i
                i = j
                continue
        i += 1
    if in_select and cur_start >= 0:
        items.append((sql[cur_start:], last_as - cur_start if last_as >= cur_start else -1))

    out: list[tuple[str, str]] = []
    for item, as_off in items:
        if as_off >= 0:
            raw_id = item[as_off + 2 :]
            if not raw_id.lstrip().startswith(('"', "`")):
                raw_id = raw_id.split("--", 1)[0].split("/*", 1)[0]
            alias = raw_id.strip().strip('`"[] ')
            if alias and all(ch.isalnum() or ch == "_" for ch in alias):
                out.append((item[:as_off].strip(), alias))
    return out


def _suffix_num(alias: str) -> int:
    pos = alias.rfind("_")
    return int(alias[pos + 1 :]) if pos > 0 and alias[pos + 1 :].isdigit() else 0


def _looks_like_case_sort(expr: str) -> bool:
    up = expr.upper()
    if "CASE" not in up or " THEN " not in up:
        return False
    thens = [p.lstrip() for p in up.split(" THEN ")[1:]]
    return bool(thens) and all(t[:1].isdigit() for t in thens)


def _resolve_cte_aliases(fields: list[str], sql: str) -> dict[str, str]:
    select_cols = _extract_select_aliases(sql)
    if not select_cols:
        return {f: _sql_alias(f) for f in fields}

    exact_idx = {a: i for i, (_, a) in enumerate(select_cols)}
    lower_idx = {a.lower(): i for i, (_, a) in enumerate(select_cols)}
    resolved: dict[str, str] = {}
    used_idx: set[int] = set()
    unresolved: list[str] = []

    for f in fields:
        if f in resolved:
            continue
        raw = _sql_alias(f)
        idx = exact_idx.get(raw)
        if idx is None:
            idx = lower_idx.get(raw.lower())
        if idx is not None and idx not in used_idx:
            used_idx.add(idx)
            resolved[f] = select_cols[idx][1]
        else:
            unresolved.append(f)

    if not unresolved:
        return resolved

    unused = [(i, expr, a) for i, (expr, a) in enumerate(select_cols) if i not in used_idx]
    cands_by_field: dict[str, list[tuple[int, str, str]]] = {}
    groups: dict[tuple[int, ...], list[str]] = {}
    for f in unresolved:
        stripped = _sql_alias(f).replace("_", "").lower()
        cands = []
        for item in unused:
            _, _, a = item
            pos = a.rfind("_")
            base_a = a[:pos] if pos > 0 and a[pos + 1 :].isdigit() else a
            base_clean = base_a.replace("_", "").lower()
            if base_clean and stripped.startswith(base_clean) and (base_clean == stripped or len(base_clean) >= min(len(stripped), 28)):
                cands.append(item)
        cands_by_field[f] = cands
        if cands:
            groups.setdefault(tuple(c[0] for c in cands), []).append(f)
        else:
            resolved[f] = _sql_alias(f)

    for gf_list in groups.values():
        cands = cands_by_field[gf_list[0]]
        if len(gf_list) == 1:
            resolved[gf_list[0]] = max(cands, key=lambda item: (_suffix_num(item[2]), item[0]))[2]
        else:
            non_sort = [c for c in cands if not _looks_like_case_sort(c[1])]
            picked = non_sort if len(non_sort) >= len(gf_list) else cands[-len(gf_list) :]
            for i, gf in enumerate(gf_list):
                resolved[gf] = picked[i][2] if i < len(picked) else _sql_alias(gf)
    return resolved


def _strip_trailing_limit(sql: str) -> str:
    toks = sql.rstrip().rsplit(None, 2)
    if len(toks) >= 2 and toks[-2].upper() == "LIMIT" and toks[-1].isdigit():
        return sql[: sql.upper().rfind("LIMIT")].rstrip()
    return sql


def _rewrite_tc_expr(
    expr: object, field_origin: dict[str, tuple[int, str]]
) -> str:
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


def _warn_query(msg: str) -> None:
    try:
        _warn_sdk_query(msg)
    except Exception:  # noqa: BLE001
        print("WARNING: " + msg)


def execute_looker_query(
    spec: object, transport_options: object = None
) -> list[dict[str, object]]:
    """Execute one or more Looker queries with SQL CTE joins and SQL Runner / Python fallback."""
    spec_dict = {"source_queries": spec} if isinstance(spec, list) and spec else (spec or {})

    def _parse_rows(raw: object, ctx: str = "") -> list[dict[str, object]]:
        res = _json_loads(raw.strip()) if isinstance(raw, str) and raw.strip() else raw
        if isinstance(res, dict) and ("errors" in res or "message" in res):
            raise RuntimeError(f"Looker query error ({ctx}): {res}")
        return _as_dicts(res)

    def _run_json(q: dict[str, object]) -> list[dict[str, object]]:
        raw_b = q.get("body", q)
        body = raw_b if isinstance(raw_b, dict) else q
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
        q0 = sq0.get("query", sq0)
        return _run_json(q0 if isinstance(q0, dict) else sq0)

    q_bodies = []
    warned_src_tc = False
    for sq in raw_sqs:
        q_raw = sq.get("query", sq) if isinstance(sq, dict) else {}
        raw_qb = _clone(q_raw.get("body", q_raw) if isinstance(q_raw, dict) else {})
        qb = raw_qb if isinstance(raw_qb, dict) else {}
        dyn = _parse_dyn_items(qb.get("dynamic_fields"))
        tc_names = {d["table_calculation"] for d in dyn if isinstance(d.get("table_calculation"), str)}
        if tc_names:
            if not warned_src_tc:
                _warn_query("Table calculations on source queries are ignored when merging multiple queries.")
                warned_src_tc = True
            kept = [d for d in dyn if "table_calculation" not in d]
            qb.update(dynamic_fields=_json_dumps(kept)) if kept else qb.pop("dynamic_fields", None)
            if isinstance((qb_fields := qb.get("fields")), list):
                qb["fields"] = [f for f in qb_fields if f not in tc_names]
            if isinstance((qb_sorts := qb.get("sorts")), list):
                qb["sorts"] = [s for s in qb_sorts if str(s).split()[0] not in tc_names]
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

    p0_fields = _as_strs(q_bodies[0].get("fields"))
    joins_meta = [
        (
            _as_dicts(sq.get("merge_fields") if isinstance(sq, dict) else None)
            or [
                {"field_name": f, "source_field_name": f}
                for f in p0_fields
                if f in _as_strs(q_bodies[idx].get("fields"))
            ],
            str((sq.get("join_type") if isinstance(sq, dict) else None) or spec_dict.get("join_type") or "left").lower(),
        )
        for idx, sq in enumerate(raw_sqs[1:], start=1)
    ]

    try:
        if create_sql_query is None or run_sql_query is None:
            raise RuntimeError("SQL Runner methods unavailable on SDK")

        ctes = []
        cte_aliases: list[dict[str, str]] = []
        field_origin: dict[str, tuple[int, str]] = {}
        alias_to_field: dict[str, str] = {}
        for idx, qb in enumerate(q_bodies):
            raw_sql = run_inline_query("sql", qb)
            if not isinstance(raw_sql, str) or not raw_sql.strip() or raw_sql.lstrip().startswith(("{", "[")):
                raise RuntimeError(f"Expected SQL string from run_inline_query, got: {raw_sql!r}")
            sql = raw_sql.strip().rstrip(";").strip()
            if str(qb.get("limit", spec_dict.get("limit", ""))).strip() == "-1":
                sql = _strip_trailing_limit(sql)
            ctes.append(f"cte_{idx} AS (\n{sql}\n)")

            q_flds = _as_strs(qb.get("fields"))
            q_aliases = _resolve_cte_aliases(q_flds, sql)
            cte_aliases.append(q_aliases)
            for f in q_flds:
                if f not in field_origin:
                    src_alias = q_aliases[f]
                    out_alias = src_alias
                    if out_alias.lower() in alias_to_field:
                        n = 2
                        out_alias = f"{src_alias[:124]}_{n}"
                        while out_alias.lower() in alias_to_field:
                            n += 1
                            out_alias = f"{src_alias[: 127 - len(str(n))]}_{n}"
                    field_origin[f] = (idx, out_alias)
                    alias_to_field[out_alias] = f
                    alias_to_field[out_alias.lower()] = f

        joins = []
        for idx, (mfields, jtype) in enumerate(joins_meta, start=1):
            if not mfields:
                raise ValueError(f"source_queries[{idx}] is missing merge_fields")
            on_sql = " AND ".join(
                f"cte_0.{cte_aliases[0].get(fn := str(m['field_name']), _sql_alias(fn))} = cte_{idx}.{cte_aliases[idx].get(sfn := str(m['source_field_name']), _sql_alias(sfn))}"
                for m in mfields
            )
            joins.append(f"{'INNER JOIN' if jtype == 'inner' else 'LEFT JOIN'} cte_{idx} ON {on_sql}")

        projected = _uniq(
            [f for f in _as_strs(spec_dict.get("fields")) if f in field_origin]
            + list(field_origin.keys())
        )
        select_sql = ", ".join(
            f"cte_{field_origin[f][0]}.{cte_aliases[field_origin[f][0]][f]} AS {field_origin[f][1]}"
            for f in projected
        )
        sql_lines = [f"WITH {', '.join(ctes)}", f"SELECT {select_sql}", f"FROM cte_0 {' '.join(joins)}"]

        if not final_tcs:
            order_cols = []
            for s in spec_dict.get("sorts") or []:
                if isinstance(s, str) and s.strip() and s != "__UNSORTED__":
                    parts = s.strip().split()
                    c = parts[0]
                    col_ref = (
                        field_origin[c][1]
                        if c in field_origin
                        else (
                            field_origin[c[:-7]][1]
                            if c.endswith("__sort_") and c[:-7] in field_origin
                            else _sql_alias(c)
                        )
                    )
                    order_cols.append(f"{col_ref} {'DESC' if len(parts) > 1 and parts[1].lower() == 'desc' else 'ASC'}")
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

        def _remap(rows: list[dict[str, object]]) -> list[dict[str, object]]:
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


def _cell_val(cell: object) -> object:
    return cell.get("value") if isinstance(cell, dict) else cell


def _to_float(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except Exception:  # noqa: BLE001
        return None


def _to_int(v: object) -> int:
    f = _to_float(v)
    return round(f) if f is not None else 0


def _days_to_ymd(days: int) -> str:
    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    y += 1 if m <= 2 else 0
    return f"{y:04d}-{m:02d}-{d:02d}"


def _root_field_type(d: dict[str, object]) -> str:
    dtype = str(d.get("type") or "string")
    if dtype == "yesno":
        return "yesno"
    if (
        dtype.startswith(("date", "time"))
        or bool(d.get("is_timeframe"))
        or (bool(d.get("dimension_group")) and not dtype.startswith("duration"))
    ):
        return "datetime"
    if dtype in ("number", "distance") or dtype.startswith("duration") or bool(d.get("is_numeric")):
        return "number"
    return "string"


def _spikiness_stats(pairs: list[tuple[str, float]]) -> dict[str, object]:
    clean = [(p, c) for p, c in pairs if p and p != "NULL"]
    if not clean:
        return {"period_count": 0}
    vals = [c for _, c in clean]
    n = len(vals)
    mean = sum(vals) / n
    stddev = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
    peak_p, max_v = max(clean, key=lambda x: x[1])
    trough_p, min_v = min(clean, key=lambda x: x[1])
    return {
        "period_count": n,
        "min_count": round(min_v, 2),
        "max_count": round(max_v, 2),
        "mean_count": round(mean, 2),
        "stddev_count": round(stddev, 2),
        "spikiness_ratio": round(max_v / mean, 2) if mean > 0 else 0.0,
        "cv": round(stddev / mean, 2) if mean > 0 else 0.0,
        "peak_period": peak_p,
        "trough_period": trough_p,
    }


def _finalize_field_profile(
    d: dict[str, object],
    root_type: str,
    stats: dict[str, object],
    is_helper: bool,
) -> dict[str, object]:
    fname = str(d.get("name") or "")
    sname = fname.split(".", 1)[-1]
    low = sname.lower()
    dtype = str(d.get("type") or "string")
    sql_expr = str(d.get("sql") or "")
    val_fmt = str(d.get("value_format") or d.get("value_format_name") or "").lower()
    base_desc = str(d.get("description") or "").strip()
    prefix = ((base_desc if base_desc[-1] in ".!?" else base_desc + ".") + " ") if base_desc else ""
    existing_tags = _uniq(_as_strs(d.get("tags")))
    is_pk = bool(d.get("primary_key"))
    is_sys = low.startswith(("_fivetran_", "_airbyte_", "_sdc_", "_baton_", "etl_", "ingest_")) or low.endswith(("_pk", "_fk", "_sk"))

    total_rows = _to_int(stats.get("total_rows"))
    dist_cnt = _to_int(stats.get("approx_count_distinct"))
    null_cnt = _to_int(stats.get("null_count"))
    null_pct = round(100.0 * null_cnt / total_rows, 2) if total_rows > 0 else 0.0

    tags: list[str] = []
    decisions: list[str] = [f"root_type='{root_type}' from lookml_type='{dtype}'"]

    def _tag(t: str, reason: str) -> None:
        tags.append(t)
        decisions.append(reason)

    if not is_pk and low.endswith(("_id", "_fk")):
        _tag("profile:foreign_key", f"tag 'profile:foreign_key': non-PK field name '{sname}' ends with _id/_fk")
    if null_cnt > 0:
        _tag("profile:nullable", f"tag 'profile:nullable': null_count={null_cnt} ({null_pct}% of {total_rows} rows)")
    if total_rows > 0 and dist_cnt == total_rows and null_cnt == 0:
        _tag("profile:unique_key_candidate", f"tag 'profile:unique_key_candidate': approx_count_distinct={dist_cnt} == total_rows={total_rows} with 0 nulls")

    rec_hidden = bool(d.get("hidden", False)) or is_pk or is_sys or is_helper
    rec_suggestable: bool | None = None
    subtype = root_type
    rec_desc = base_desc or f"{d.get('label_short') or sname}."

    if root_type == "string":
        samples = [
            str(tv.get("value") or "").strip()
            for tv in _as_dicts(stats.get("top_values"))
            if tv.get("value") is not None and str(tv.get("value")).strip() != ""
        ]
        max_len = _to_int(stats.get("max_length"))
        avg_len = _to_float(stats.get("avg_length")) or 0.0
        json_hits = sum(1 for v in samples if (v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]")))
        uuid_hits = sum(
            1
            for v in samples
            if 32 <= len(s := (v.strip().lower().replace("-", "") if len(v.strip()) == 36 and v.strip()[8:24:5] == "----" else v.strip().lower())) <= 64
            and all(c in "0123456789abcdef" for c in s)
        )
        email_hits = sum(1 for v in samples if "@" in v and "." in v.split("@", 1)[-1])
        ex3 = ", ".join(f"'{v[:40]}'" for v in samples[:3])

        if dtype in ("tier", "location"):
            subtype, rec_hidden, rec_suggestable = dtype, is_helper, dtype == "tier"
            _tag(f"profile:{subtype}", f"subtype='{subtype}' + tag 'profile:{subtype}' from lookml_type='{dtype}' (suggestable={rec_suggestable})")
            vals_p = ", ".join(f"'{v}'" for v in samples[:8])
            rec_desc = f"{prefix}Values: {vals_p}." if vals_p else f"{prefix}{dtype.capitalize()} dimension."
        elif "JSON_" in sql_expr.upper() or any(t in low for t in ("json", "payload", "raw_event")) or (samples and json_hits * 2 >= len(samples)):
            subtype, rec_hidden, rec_suggestable = "json", True, False
            _tag("profile:json_payload", f"subtype='json' + tag 'profile:json_payload' (hidden=True, suggestable=False): SQL/name or {json_hits}/{len(samples)} sample values match JSON")
            rec_desc = f"{prefix}Raw JSON payload; hidden and filter suggestions disabled to prevent full-column scans."
        elif any(t in low for t in ("uuid", "guid", "hash", "md5", "sha256")) or (samples and uuid_hits * 5 >= len(samples) * 4):
            subtype, rec_hidden, rec_suggestable = "id_or_code", True, False
            _tag("profile:uuid_or_hash", f"subtype='id_or_code' + tag 'profile:uuid_or_hash' (hidden=True, suggestable=False): name or {uuid_hits}/{len(samples)} samples match UUID/hex")
            rec_desc = f"{prefix}High-cardinality UUID or hash identifier."
        elif is_pk or is_sys or is_helper or ((low == "id" or low.endswith("_id")) and dist_cnt > 100):
            subtype, rec_hidden, rec_suggestable = "id_or_code", True, False
            decisions.append(f"subtype='id_or_code' (hidden=True, suggestable=False): primary_key={is_pk}, system_col={is_sys}, helper={is_helper}, distinct={dist_cnt}")
            rec_desc = f"{prefix}Internal key or system metadata column not intended for end-user grouping."
        elif dist_cnt == 0 and total_rows > 0:
            subtype, rec_hidden, rec_suggestable = "empty_or_null", True, False
            _tag("profile:empty_or_null_only", f"subtype='empty_or_null' + tag 'profile:empty_or_null_only' (hidden=True, suggestable=False): approx_count_distinct=0 across {total_rows} rows")
            rec_desc = f"{prefix}Column contains only NULL or empty values in sampled data."
        elif max_len > 120 or avg_len > 60.0 or low.endswith(("comment", "comments", "note", "notes", "description", "message", "body", "transcript")):
            subtype, rec_hidden, rec_suggestable = "free_text", False, False
            _tag("profile:opaque_code_or_free_text", f"subtype='free_text' + tag 'profile:opaque_code_or_free_text' (suggestable=False): max_length={max_len} (>120), avg_length={avg_len} (>60), or free-text name suffix")
            rec_desc = f"{prefix}Free-text string ({dist_cnt}+ distinct values, max length {max_len}); filter suggestions disabled."
        elif dtype == "zipcode" or low.endswith(("sku", "code", "zip", "postal", "phone", "email", "url", "uri", "ip", "ip_address", "token", "tracking_number")):
            subtype, rec_hidden, rec_suggestable = "id_or_code", False, False
            _tag("profile:opaque_code_or_free_text", f"subtype='id_or_code' + tag 'profile:opaque_code_or_free_text' (suggestable=False): identifier/code suffix on '{sname}' with {dist_cnt} distinct values")
            rec_desc = f"{prefix}Opaque identifier or code ({dist_cnt}+ distinct values, max length {max_len}); filter suggestions disabled." + (f" Example values: {ex3}." if ex3 else "")
        elif 1 <= dist_cnt <= 15:
            subtype, rec_hidden, rec_suggestable = "enum", False, True
            _tag("profile:low_cardinality_enum", f"subtype='enum' + tag 'profile:low_cardinality_enum' (suggestable=True): approx_count_distinct={dist_cnt} is in 1..15")
            vals_str = ", ".join(f"'{v}'" for v in samples[:15])
            rec_desc = f"{prefix}Values: {vals_str}." if vals_str else f"{prefix}Low-cardinality enum ({dist_cnt} values)."
        elif dist_cnt <= 100:
            subtype, rec_hidden, rec_suggestable = "categorical", False, True
            _tag("profile:medium_cardinality_categorical", f"subtype='categorical' + tag 'profile:medium_cardinality_categorical' (suggestable=True): approx_count_distinct={dist_cnt} is in 16..100")
            vals_str = ", ".join(f"'{v}'" for v in samples[:10])
            rec_desc = f"{prefix}Top values include: {vals_str} ({dist_cnt} distinct values)." if vals_str else f"{prefix}Categorical string ({dist_cnt} distinct values)."
        else:
            subtype, rec_hidden, rec_suggestable = "entity_label", False, True
            _tag("profile:searchable_entity_label", f"subtype='entity_label' + tag 'profile:searchable_entity_label' (suggestable=True): approx_count_distinct={dist_cnt} > 100")
            rec_desc = f"{prefix}Searchable entity label ({dist_cnt}+ distinct values)." + (f" Example values: {ex3}." if ex3 else "")

        if "email" in low or (samples and email_hits * 2 >= len(samples)):
            tags.extend(["profile:pii", "profile:email"])
            decisions.append(f"tags 'profile:pii', 'profile:email': field name '{sname}' or {email_hits}/{len(samples)} sample values match email format")
        if any(t in low for t in ("phone", "mobile", "telephone")):
            tags.extend(["profile:pii", "profile:phone"])
            decisions.append(f"tags 'profile:pii', 'profile:phone': field name '{sname}' matches phone token")
        if any(t in low for t in ("ssn", "tax_id", "passport", "first_name", "last_name", "full_name", "street_address", "ip_address")):
            _tag("profile:pii", f"tag 'profile:pii': field name '{sname}' matches PII token")

    elif root_type == "number":
        min_v, max_v = _to_float(stats.get("min")), _to_float(stats.get("max"))
        avg_v, med_v = _to_float(stats.get("average")), _to_float(stats.get("median"))
        zero_cnt, neg_cnt = _to_int(stats.get("zero_count")), _to_int(stats.get("negative_count"))
        all_ints = bool(stats.get("all_integers", False))
        rng = f"(range: {min_v} to {max_v}, avg: {avg_v}, median: {med_v})"

        if dist_cnt == 0 and total_rows > 0:
            subtype, rec_hidden = "empty_or_null", True
            _tag("profile:empty_or_null_only", f"subtype='empty_or_null' + tag 'profile:empty_or_null_only' (hidden=True): approx_count_distinct=0 across {total_rows} rows")
            rec_desc = f"{prefix}Numeric column contains only NULL values."
        elif is_pk or is_sys or low == "id" or low.endswith(("_id", "_pk", "_fk", "_sk")):
            subtype, rec_hidden = "id_or_key", True
            decisions.append(f"subtype='id_or_key' (hidden=True): primary_key={is_pk} or key suffix on '{sname}'")
            rec_desc = f"{prefix}Internal numeric key not intended for direct aggregation."
        elif dist_cnt == 1 and total_rows > 0:
            subtype = "constant"
            _tag("profile:constant_value", f"subtype='constant' + tag 'profile:constant_value': approx_count_distinct=1 (value={min_v})")
            rec_desc = f"{prefix}Constant numeric value ({min_v})."
        elif dtype.startswith("duration") or any(t in low for t in ("days_", "hours_", "minutes_", "months_", "years_", "_duration", "shelf_age")):
            subtype = "duration"
            _tag("profile:duration", f"subtype='duration' + tag 'profile:duration': lookml_type='{dtype}' or duration token in '{sname}'")
            rec_desc = f"{prefix}Duration metric {rng}."
        elif "%" in val_fmt or any(t in low for t in ("pct", "percent", "rate", "ratio", "share", "z_score")) or (min_v is not None and max_v is not None and 0.0 <= min_v and max_v <= 1.0 and not all_ints):
            subtype = "percentage_or_ratio"
            _tag("profile:percentage_or_ratio", f"subtype='percentage_or_ratio' + tag 'profile:percentage_or_ratio': format='{val_fmt}', rate/pct name, or [0,1] float range ({min_v}..{max_v})")
            rec_desc = f"{prefix}Ratio or rate dimension {rng}."
        elif "$" in val_fmt or "usd" in val_fmt or any(t in low for t in ("price", "cost", "revenue", "amount", "margin", "profit", "spend", "fee")):
            subtype = "currency_or_decimal"
            _tag("profile:currency_or_decimal", f"subtype='currency_or_decimal' + tag 'profile:currency_or_decimal': format='{val_fmt}' or monetary token in '{sname}'")
            rec_desc = f"{prefix}Monetary or decimal value {rng}."
        elif all_ints:
            subtype = "discrete_integer"
            _tag("profile:discrete_integer", f"subtype='discrete_integer' + tag 'profile:discrete_integer': all sampled values are integers ({dist_cnt} distinct, range {min_v}..{max_v})")
            rec_desc = f"{prefix}Discrete integer (range: {min_v} to {max_v}, avg: {avg_v}, median: {med_v}, {dist_cnt} distinct)."
        else:
            subtype = "continuous_number"
            _tag("profile:continuous_number", f"subtype='continuous_number' + tag 'profile:continuous_number': non-integer numeric values (range {min_v}..{max_v})")
            rec_desc = f"{prefix}Continuous number {rng}."

        if neg_cnt > 0:
            _tag("profile:has_negatives", f"tag 'profile:has_negatives': negative_count={neg_cnt} > 0")
        if zero_cnt > 0:
            _tag("profile:has_zeros", f"tag 'profile:has_zeros': zero_count={zero_cnt} > 0")
        if avg_v is not None and med_v is not None and med_v != 0 and abs(avg_v - med_v) / abs(med_v) >= 0.5:
            _tag("profile:skewed_distribution", f"tag 'profile:skewed_distribution': |avg ({avg_v}) - median ({med_v})| / |median| >= 0.5")

    elif root_type == "yesno":
        t_cnt, f_cnt = _to_int(stats.get("true_count")), _to_int(stats.get("false_count"))
        t_pct, f_pct = _to_float(stats.get("true_pct")) or 0.0, _to_float(stats.get("false_pct")) or 0.0
        if t_cnt == 0 and f_cnt == 0 and total_rows > 0:
            subtype, rec_hidden = "empty_or_null", True
            _tag("profile:empty_or_null_only", f"subtype='empty_or_null' + tag 'profile:empty_or_null_only' (hidden=True): 0 non-null boolean rows out of {total_rows}")
            rec_desc = f"{prefix}Boolean flag with only NULL values."
        elif (t_cnt == 0 or f_cnt == 0) and (t_cnt + f_cnt) > 0:
            subtype = "constant_boolean"
            tags.extend(["profile:constant_boolean", "profile:constant_value"])
            decisions.append(f"subtype='constant_boolean' + tags 'profile:constant_boolean', 'profile:constant_value': single boolean state (Yes={t_cnt}, No={f_cnt})")
            rec_desc = f"{prefix}Constant boolean flag (Yes: {t_pct}%, No: {f_pct}%)."
        elif min(t_pct, f_pct) < 5.0 and (t_cnt + f_cnt) > 0:
            subtype = "rare_or_skewed_boolean"
            _tag("profile:rare_or_skewed_boolean", f"subtype='rare_or_skewed_boolean' + tag 'profile:rare_or_skewed_boolean': minority class {min(t_pct, f_pct)}% < 5.0% threshold (Yes={t_pct}%, No={f_pct}%)")
            rec_desc = f"{prefix}Skewed boolean flag (Yes: {t_pct}%, No: {f_pct}%)."
        else:
            subtype = "balanced_boolean"
            _tag("profile:balanced_boolean", f"subtype='balanced_boolean' + tag 'profile:balanced_boolean': minority class {min(t_pct, f_pct)}% >= 5.0% threshold (Yes={t_pct}%, No={f_pct}%)")
            rec_desc = f"{prefix}Boolean flag (Yes: {t_pct}%, No: {f_pct}%)."

    elif root_type == "datetime":
        min_d, max_d, span_d = stats.get("min_date"), stats.get("max_date"), stats.get("span_days")
        spikiness = _as_dict(stats.get("spikiness"))
        if dist_cnt == 0 and total_rows > 0:
            subtype, rec_hidden = "empty_or_null", True
            _tag("profile:empty_or_null_only", f"subtype='empty_or_null' + tag 'profile:empty_or_null_only' (hidden=True): 0 distinct dates across {total_rows} rows")
            rec_desc = f"{prefix}Date/time field contains only NULL values."
        elif dtype in ("date_time", "date_raw", "date_hour", "date_minute", "date_second"):
            subtype = "timestamp_or_raw"
            _tag("profile:timestamp_or_raw", f"subtype='timestamp_or_raw' + tag 'profile:timestamp_or_raw': lookml_type='{dtype}' is sub-day timestamp grain; expanded to [date, hour] with date subtotals")
        elif dtype == "date_date":
            subtype = "calendar_date"
            _tag("profile:calendar_date", "subtype='calendar_date' + tag 'profile:calendar_date': lookml_type='date_date'; expanded to [year, month, date] with [year, month] subtotals")
        elif dtype in ("date_year", "date_quarter", "date_month", "date_week", "date_fiscal_year", "date_fiscal_quarter"):
            subtype = "period_grain"
            _tag("profile:period_grain", f"subtype='period_grain' + tag 'profile:period_grain': lookml_type='{dtype}' is coarse calendar period; expanded to [year, month, date] with [year, month] subtotals")
        else:
            subtype = "calendar_cycle"
            _tag("profile:calendar_cycle", f"subtype='calendar_cycle' + tag 'profile:calendar_cycle': lookml_type='{dtype}' is a recurring calendar cycle")

        spiky_notes = []
        for g_name, g_obj in spikiness.items():
            gd = _as_dict(g_obj)
            sr, cv = _to_float(gd.get("spikiness_ratio")) or 0.0, _to_float(gd.get("cv")) or 0.0
            if sr >= 2.0 or cv >= 0.5:
                _tag(f"profile:spiky_{g_name}", f"tag 'profile:spiky_{g_name}': {g_name} spikiness_ratio={sr} (>=2.0) or cv={cv} (>=0.5), peak={gd.get('peak_period')} ({gd.get('max_count')}) vs mean={gd.get('mean_count')}")
                spiky_notes.append(f"{g_name} peak {gd.get('peak_period')} ({sr}x mean)")
            elif 0 < cv < 0.25 and "profile:steady_volume" not in tags:
                _tag("profile:steady_volume", f"tag 'profile:steady_volume': {g_name} cv={cv} < 0.25")

        if subtype != "empty_or_null":
            range_str = f"Range: {min_d} to {max_d} ({span_d} days)" if min_d and max_d else f"{dist_cnt} distinct periods"
            rec_desc = f"{prefix}{range_str}{'; spikiness: ' + ', '.join(spiky_notes) if spiky_notes else ''}."

    suggested_tags = _uniq(tags)
    rec_tags = _uniq(existing_tags + suggested_tags)
    dg_name = d.get("dimension_group")
    target_short = str(dg_name).split(".", 1)[-1] if dg_name else sname
    kw = "dimension_group" if dg_name else "dimension"
    s_lines = [f"  {kw}: {target_short} {{", f"    hidden: {'yes' if rec_hidden else 'no'}"]
    if rec_suggestable is not None and not dg_name:
        s_lines.append(f"    suggestable: {'yes' if rec_suggestable else 'no'}")
    if rec_tags:
        s_lines.append(f"    tags: [{', '.join(_json_dumps(t) for t in rec_tags)}]")
    s_lines.extend([f"    description: {_json_dumps(rec_desc)}", "  }"])

    return {
        "field": fname,
        "short_name": sname,
        "view": d.get("view"),
        "label": d.get("label"),
        "label_short": d.get("label_short"),
        "lookml_type": dtype,
        "root_type": root_type,
        "subtype": subtype,
        "dimension_group": dg_name,
        "primary_key": is_pk,
        "total_rows": total_rows,
        "approx_count_distinct": dist_cnt,
        "null_count": null_cnt,
        "null_pct": null_pct,
        "stats": stats,
        "suggested_tags": suggested_tags,
        "decisions": decisions,
        "curation": {
            "current_hidden": bool(d.get("hidden", False)),
            "current_suggestable": bool(d.get("suggestable", True)),
            "current_description": base_desc,
            "current_tags": existing_tags,
            "recommended_hidden": rec_hidden,
            "recommended_suggestable": rec_suggestable,
            "recommended_description": rec_desc,
            "suggested_tags": rec_tags,
            "lookml_snippet": "\n".join(s_lines),
        },
    }


def profile_fields(
    body: object = None,
    model: str | None = None,
    view: str | None = None,
    fields: list[str] | None = None,
    filters: dict[str, str] | None = None,
    types_only: bool = False,
    group_fields: bool = False,
    limit: int | str = 5000,
    transport_options: object = None,
) -> dict[str, object]:
    """Profile Explore fields across string, number, yesno, and datetime types with subtypes, spikiness, and LookML curation tags."""
    b_dict = _as_dict(body)
    m_name = str(model or b_dict.get("model") or "").strip()
    v_name = str(view or b_dict.get("view") or b_dict.get("explore") or "").strip()
    if not m_name or not v_name:
        raise ValueError("Both 'model' and 'view' (explore) are required")

    req_fields = list(fields if fields is not None else _as_strs(b_dict.get("fields")))
    raw_flts = filters if filters is not None else _as_dict(b_dict.get("filters"))
    base_filters = {str(k): str(v) for k, v in raw_flts.items() if k and v is not None}
    types_only = types_only or bool(b_dict.get("types_only"))
    group_fields = group_fields or bool(b_dict.get("group_fields"))
    raw_lim = b_dict.get("limit", limit) if limit == 5000 else limit
    q_limit = min(max(_to_int(raw_lim) or 5000, 1), 5000)

    exp = _as_dict(lookml_model_explore(m_name, v_name))
    base_view = str(exp.get("view_name") or v_name)
    exp_flds = _as_dict(exp.get("fields"))
    dims = _as_dicts(exp_flds.get("dimensions"))
    meas = _as_dicts(exp_flds.get("measures"))

    dims_by_name = {str(d["name"]): d for d in dims if d.get("name")}
    meas_by_name = {str(m["name"]): m for m in meas if m.get("name")}
    dgs_by_group: dict[str, dict[str, str]] = {}
    dim_by_table_col: dict[str, list[str]] = {}
    referenced_fields = {
        r
        for item in dims + meas
        for r in _extract_refs(item.get("sql"), item.get("view") or base_view)
    }

    for d in dims:
        dn = str(d.get("name") or "")
        dv = str(d.get("view") or base_view)
        dg = d.get("dimension_group")
        if dg and dn.startswith(str(dg) + "_"):
            dgs_by_group.setdefault(str(dg), {})[dn[len(str(dg)) + 1 :]] = dn
        tc = _table_col(d.get("sql"), dv)
        if dn and tc and not d.get("is_timeframe"):
            dim_by_table_col.setdefault(tc, []).append(dn)

    if not req_fields:
        req_fields = [
            str(d["name"])
            for d in dims
            if d.get("name") and not d.get("hidden") and (d.get("view") or base_view) == base_view
        ] or [str(d["name"]) for d in dims if d.get("name") and not d.get("hidden")]

    target_dims: list[str] = []
    target_measures: list[str] = []
    measure_leaf_map: dict[str, list[str]] = {}

    def _walk_measure_leaves(m_name: str) -> list[str]:
        leaves: list[str] = []
        visited = {m_name}
        m_obj = meas_by_name.get(m_name) or {}
        m_view = str(m_obj.get("view") or base_view)
        stack = list(_extract_refs(m_obj.get("sql"), m_view))
        while stack:
            ref = stack.pop(0)
            if ref in visited:
                continue
            visited.add(ref)
            if ref in meas_by_name:
                rm = meas_by_name[ref]
                stack.extend(_extract_refs(rm.get("sql"), rm.get("view") or m_view))
            elif ref in dims_by_name:
                rd = dims_by_name[ref]
                stack.extend(_extract_refs(rd.get("sql"), rd.get("view") or m_view))
                if ref not in leaves:
                    leaves.append(ref)
        if not leaves and (tc := _table_col(m_obj.get("sql"), m_view)):
            leaves.extend(dim_by_table_col.get(tc, []))
        return _uniq(leaves)

    for rf in req_fields:
        qual = rf if "." in rf else f"{base_view}.{rf}"
        if qual in dims_by_name:
            target_dims.append(qual)
        elif qual in meas_by_name:
            target_measures.append(qual)
            leaves = _walk_measure_leaves(qual)
            measure_leaf_map[qual] = leaves
            target_dims.extend(leaves)
        elif qual in dgs_by_group:
            dg_map = dgs_by_group[qual]
            if picked := (dg_map.get("date") or dg_map.get("time") or next(iter(dg_map.values()), "")):
                target_dims.append(picked)

    target_dims = _uniq(target_dims)
    target_measures = _uniq(target_measures)
    type_buckets = {
        rt: [dn for dn in target_dims if _root_field_type(dims_by_name[dn]) == rt]
        for rt in ("string", "number", "yesno", "datetime")
    }

    def _is_helper_dim(dn: str) -> bool:
        return dn in referenced_fields and dn.split(".", 1)[-1].lower().startswith(("_", "helper_", "tmp_", "raw_"))

    if types_only:
        return {
            "model": m_name,
            "view": v_name,
            "limit": q_limit,
            "types_only": True,
            "type_buckets": type_buckets,
            "profiles": {
                dn: _finalize_field_profile(dims_by_name[dn], _root_field_type(dims_by_name[dn]), {}, _is_helper_dim(dn))
                for dn in target_dims
            },
            "measures": {
                mn: {
                    "field": mn,
                    "lookml_type": (meas_by_name.get(mn) or {}).get("type"),
                    "leaf_dimensions": measure_leaf_map.get(mn, []),
                }
                for mn in target_measures
            },
        }

    def _run_detail(q_body: dict[str, object]) -> dict[str, object]:
        raw = run_inline_query("json_detail", q_body)
        return _as_dict(_json_loads(raw.strip()) if isinstance(raw, str) and raw.strip().startswith("{") else raw)

    measures_out: dict[str, dict[str, object]] = {}
    if target_measures:
        m_body: dict[str, object] = {"model": m_name, "view": v_name, "fields": target_measures, "limit": "1"}
        if base_filters:
            m_body["filters"] = base_filters
        m_rows = _as_dicts(run_inline_query("json", m_body))
        m_row0 = m_rows[0] if m_rows else {}
        for mn in target_measures:
            m_obj = meas_by_name.get(mn) or {}
            measures_out[mn] = {
                "field": mn,
                "label": m_obj.get("label"),
                "lookml_type": m_obj.get("type"),
                "sql": m_obj.get("sql"),
                "value": _cell_val(m_row0.get(mn)),
                "leaf_dimensions": measure_leaf_map.get(mn, []),
            }

    profiles: dict[str, dict[str, object]] = {}
    grouped_rows_out: list[dict[str, object]] = []
    overall_total_rows = 0

    def _build_dim_dyn(dn: str, rt: str, idx: int) -> tuple[list[dict[str, object]], list[str]]:
        ref, p = "${" + dn + "}", f"_p{idx}_"
        dyn: list[dict[str, object]] = [
            {"measure": f"{p}rows", "based_on": dn, "type": "count"},
            {"measure": f"{p}dist", "based_on": dn, "type": "count_distinct"},
            {"measure": f"{p}null", "based_on": dn, "type": "count", "filter_expression": f"is_null({ref})"},
        ]
        m_names = [f"{p}rows", f"{p}dist", f"{p}null"]
        if rt == "string":
            dyn.extend([
                {"measure": f"{p}empty", "based_on": dn, "type": "count", "filter_expression": f"length({ref}) = 0"},
                {"dimension": f"{p}len", "expression": f"length({ref})"},
                {"measure": f"{p}minlen", "based_on": f"{p}len", "type": "min"},
                {"measure": f"{p}maxlen", "based_on": f"{p}len", "type": "max"},
                {"measure": f"{p}avglen", "based_on": f"{p}len", "type": "average"},
            ])
            m_names.extend([f"{p}empty", f"{p}minlen", f"{p}maxlen", f"{p}avglen"])
        elif rt == "number":
            dyn.extend([
                {"measure": f"{p}min", "based_on": dn, "type": "min"},
                {"measure": f"{p}max", "based_on": dn, "type": "max"},
                {"measure": f"{p}avg", "based_on": dn, "type": "average"},
                {"measure": f"{p}med", "based_on": dn, "type": "median"},
                {"measure": f"{p}sum", "based_on": dn, "type": "sum"},
                {"measure": f"{p}zero", "based_on": dn, "type": "count", "filter_expression": f"{ref} = 0"},
                {"measure": f"{p}neg", "based_on": dn, "type": "count", "filter_expression": f"{ref} < 0"},
            ])
            m_names.extend([f"{p}min", f"{p}max", f"{p}avg", f"{p}med", f"{p}sum", f"{p}zero", f"{p}neg"])
        elif rt == "yesno":
            dyn.extend([
                {"measure": f"{p}true", "based_on": dn, "type": "count", "filter_expression": ref},
                {"measure": f"{p}false", "based_on": dn, "type": "count", "filter_expression": f"NOT {ref}"},
            ])
            m_names.extend([f"{p}true", f"{p}false"])
        return dyn, m_names

    def _extract_dim_stats(
        dn: str,
        rt: str,
        idx: int,
        totals: dict[str, object],
        data_rows: list[dict[str, object]],
    ) -> dict[str, object]:
        p = f"_p{idx}_"
        t_rows = _to_int(_cell_val(totals.get(f"{p}rows")))
        d_cnt = _to_int(_cell_val(totals.get(f"{p}dist")))
        n_cnt = _to_int(_cell_val(totals.get(f"{p}null")))

        val_counts: dict[str, int] = {}
        raw_vals: list[object] = []
        for r in data_rows:
            v = _cell_val(r.get(dn))
            rc = _to_int(_cell_val(r.get(f"{p}rows")) or _cell_val(r.get("_p0_rows")) or 1)
            if v is not None:
                raw_vals.append(v)
                sv = str(v)
                val_counts[sv] = val_counts.get(sv, 0) + rc

        top_values = [
            {"value": k, "count": c, "pct": round(100.0 * c / t_rows, 2) if t_rows > 0 else 0.0}
            for k, c in sorted(val_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        ]

        st: dict[str, object] = {
            "total_rows": t_rows,
            "approx_count_distinct": max(d_cnt, len(val_counts)),
            "null_count": n_cnt,
            "sample_rows_returned": len(data_rows),
        }
        if rt == "string":
            st.update({
                "empty_count": _to_int(_cell_val(totals.get(f"{p}empty"))),
                "min_length": _to_int(_cell_val(totals.get(f"{p}minlen"))),
                "max_length": _to_int(_cell_val(totals.get(f"{p}maxlen"))),
                "avg_length": round(_to_float(_cell_val(totals.get(f"{p}avglen"))) or 0.0, 2),
                "top_values": top_values,
            })
        elif rt == "number":
            num_samples = [f for x in raw_vals if (f := _to_float(x)) is not None]
            st.update({
                **{
                    k: (round(fv, 4) if (fv := _to_float(_cell_val(totals.get(f"{p}{sfx}")))) is not None else None)
                    for k, sfx in (("min", "min"), ("max", "max"), ("average", "avg"), ("median", "med"), ("sum", "sum"))
                },
                "zero_count": _to_int(_cell_val(totals.get(f"{p}zero"))),
                "negative_count": _to_int(_cell_val(totals.get(f"{p}neg"))),
                # ponytail: Monty float lacks .is_integer(); x % 1 == 0 is NaN/Inf-safe
                "all_integers": bool(num_samples) and all(x % 1 == 0 for x in num_samples),
                "top_values": top_values[:10],
            })
        elif rt == "yesno":
            t_cnt, f_cnt = _to_int(_cell_val(totals.get(f"{p}true"))), _to_int(_cell_val(totals.get(f"{p}false")))
            denom = t_cnt + f_cnt
            st.update({
                "true_count": t_cnt,
                "false_count": f_cnt,
                "true_pct": round(100.0 * t_cnt / denom, 2) if denom > 0 else 0.0,
                "false_pct": round(100.0 * f_cnt / denom, 2) if denom > 0 else 0.0,
            })
        return st

    dt_dims = type_buckets["datetime"]
    non_dt_dims = [dn for dn in target_dims if dn not in dt_dims]

    batches = [non_dt_dims] if group_fields and len(non_dt_dims) > 1 else [[dn] for dn in non_dt_dims]
    for batch in batches:
        all_dyn: list[dict[str, object]] = []
        all_m_names: list[str] = []
        for idx, dn in enumerate(batch):
            d_items, m_items = _build_dim_dyn(dn, _root_field_type(dims_by_name[dn]), idx)
            all_dyn.extend(d_items)
            all_m_names.extend(m_items)
        q_body: dict[str, object] = {
            "model": m_name,
            "view": v_name,
            "fields": batch + all_m_names,
            "dynamic_fields": _json_dumps(all_dyn),
            "sorts": ["_p0_rows desc"],
            "total": True,
            "limit": str(q_limit),
        }
        if base_filters:
            q_body["filters"] = base_filters
        detail = _run_detail(q_body)
        totals, d_rows = _as_dict(detail.get("totals_data")), _as_dicts(detail.get("data"))
        for idx, dn in enumerate(batch):
            rt = _root_field_type(dims_by_name[dn])
            st = _extract_dim_stats(dn, rt, idx, totals, d_rows)
            overall_total_rows = max(overall_total_rows, _to_int(st.get("total_rows")))
            profiles[dn] = _finalize_field_profile(dims_by_name[dn], rt, st, _is_helper_dim(dn))
        if len(batch) > 1:
            grouped_rows_out.extend(
                {**{dn: _cell_val(r.get(dn)) for dn in batch}, "count": _to_int(_cell_val(r.get("_p0_rows")))}
                for r in d_rows[:50]
            )

    def _grain_dim(
        dg_map: dict[str, str],
        dt_dyn: list[dict[str, object]],
        sfx: str,
        fallback: str,
        expr: str,
    ) -> str:
        if found := dg_map.get(sfx):
            return found
        dt_dyn.append({"dimension": fallback, "expression": expr})
        return fallback

    for dn in dt_dims:
        d_obj = dims_by_name[dn]
        dtype = str(d_obj.get("type") or "date_date")
        dg = str(d_obj.get("dimension_group") or "")
        dg_map = dgs_by_group.get(dg, {}) if dg else {}
        ref = "${" + dn + "}"

        dt_dyn: list[dict[str, object]] = [
            {"measure": "_dt_rows", "based_on": dn, "type": "count"},
            {"measure": "_dt_dist", "based_on": dn, "type": "count_distinct"},
            {"measure": "_dt_null", "based_on": dn, "type": "count", "filter_expression": f"is_null({ref})"},
        ]
        dt_m_names = ["_dt_rows", "_dt_dist", "_dt_null"]

        is_time_grain = dtype in ("date_time", "date_raw", "date_hour", "date_minute", "date_second")
        is_date_grain = dtype in ("date_date", "date_week", "date_month", "date_quarter", "date_year", "date_fiscal_year", "date_fiscal_quarter")

        if is_time_grain or is_date_grain:
            dt_dyn.extend([
                {"dimension": "_dt_epoch", "expression": f"diff_days(date(1970, 1, 1), {ref})"},
                {"measure": "_dt_min_d", "based_on": "_dt_epoch", "type": "min"},
                {"measure": "_dt_max_d", "based_on": "_dt_epoch", "type": "max"},
            ])
            dt_m_names.extend(["_dt_min_d", "_dt_max_d"])

        subtotals_list: list[str] = []
        if is_time_grain:
            day_f = _grain_dim(dg_map, dt_dyn, "date", "_dt_day_dim", f"trunc_days({ref})")
            hr_f = _grain_dim(dg_map, dt_dyn, "hour", "_dt_hour_dim", f"trunc_hours({ref})")
            expanded_dims = _uniq([day_f, hr_f])
            subtotals_list = [day_f] if len(expanded_dims) > 1 else []
            grain_map = [("day", day_f), ("hour", hr_f)]
        elif is_date_grain:
            yr_f = _grain_dim(dg_map, dt_dyn, "year", "_dt_year_dim", f"extract_years({ref})")
            mo_f = _grain_dim(dg_map, dt_dyn, "month", "_dt_month_dim", f"trunc_months({ref})")
            day_f = dg_map.get("date") or dn
            expanded_dims = _uniq([yr_f, mo_f, day_f])
            subtotals_list = expanded_dims[:-1]
            grain_map = [("year", yr_f), ("month", mo_f), ("day", day_f)]
        else:
            expanded_dims, grain_map = [dn], [("cycle", dn)]

        dt_body: dict[str, object] = {
            "model": m_name,
            "view": v_name,
            "fields": expanded_dims + dt_m_names,
            "dynamic_fields": _json_dumps(dt_dyn),
            "sorts": [f"{ef} desc" for ef in expanded_dims],
            "total": True,
            "limit": str(q_limit),
        }
        if subtotals_list:
            dt_body["subtotals"] = subtotals_list
        if base_filters:
            dt_body["filters"] = base_filters

        detail = _run_detail(dt_body)
        totals, d_rows, sub_data = _as_dict(detail.get("totals_data")), _as_dicts(detail.get("data")), _as_dict(detail.get("subtotals_data"))

        t_rows = _to_int(_cell_val(totals.get("_dt_rows")))
        d_cnt = _to_int(_cell_val(totals.get("_dt_dist")))
        n_cnt = _to_int(_cell_val(totals.get("_dt_null")))
        overall_total_rows = max(overall_total_rows, t_rows)

        min_epoch, max_epoch = _to_float(_cell_val(totals.get("_dt_min_d"))), _to_float(_cell_val(totals.get("_dt_max_d")))
        min_date = _days_to_ymd(round(min_epoch)) if min_epoch is not None else None
        max_date = _days_to_ymd(round(max_epoch)) if max_epoch is not None else None
        span_days = round(max_epoch - min_epoch) if (min_epoch is not None and max_epoch is not None) else None

        spikiness: dict[str, object] = {}
        subtotals_summary: dict[str, list[dict[str, object]]] = {}

        for depth_idx, (g_label, g_field) in enumerate(grain_map, start=1):
            depth_key = str(depth_idx)
            src_rows = _as_dicts(sub_data.get(depth_key)) if (depth_key in sub_data and depth_idx <= len(subtotals_list)) else d_rows
            agg_by_p: dict[str, float] = {}
            for r in src_rows:
                pv = _cell_val(r.get(g_field))
                rc = _to_float(_cell_val(r.get("_dt_rows"))) or 0.0
                if pv is not None:
                    ps = str(pv)
                    agg_by_p[ps] = agg_by_p.get(ps, 0.0) + rc
            spikiness[g_label] = _spikiness_stats(sorted(agg_by_p.items(), key=lambda x: x[0]))
            subtotals_summary[g_label] = [
                {"period": k, "count": round(c)}
                for k, c in sorted(agg_by_p.items(), key=lambda x: x[1], reverse=True)[:12]
            ]

        dt_stats: dict[str, object] = {
            "total_rows": t_rows,
            "approx_count_distinct": d_cnt,
            "null_count": n_cnt,
            "min_date": min_date,
            "max_date": max_date,
            "span_days": span_days,
            "expanded_fields": expanded_dims,
            "spikiness": spikiness,
            "subtotals_by_grain": subtotals_summary,
            "sample_rows_returned": len(d_rows),
        }
        profiles[dn] = _finalize_field_profile(d_obj, "datetime", dt_stats, _is_helper_dim(dn))

    res_out: dict[str, object] = {
        "model": m_name,
        "view": v_name,
        "total_rows": overall_total_rows,
        "limit": q_limit,
        "type_buckets": type_buckets,
        "profiles": profiles,
    }
    if measures_out:
        res_out["measures"] = measures_out
    if grouped_rows_out:
        res_out["grouped_rows"] = grouped_rows_out
    return res_out
