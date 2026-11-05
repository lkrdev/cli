import copy
import re
from typing import Any

from lkr.codemode.type import _get_swagger_data
from lkr.schema.dynamic_fields import build_dynamic_fields_schema
from lkr.schema.fields import (
    build_fields_schema,
    build_fill_fields_schema,
    build_pivots_schema,
    build_sorts_schema,
    build_subtotals_schema,
    extract_visible_explore_fields,
)
from lkr.schema.filter_expressions import (
    FILTER_EXPRESSION_DEFS,
    build_filters_schema,
)


def build_query_body_schema(
    model: str,
    explore: str,
    explore_data: dict[str, Any],
    base_query_def: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the strongly-typed `body` (`WriteQuery`) object schema for `<model> <explore>`."""
    if isinstance(m := explore_data.get("lookml_model_explores"), dict):
        v = m.get(f"{model}::{explore}")
        explore_data = v if v is not None else next(iter(m.values()), {})
    visible = extract_visible_explore_fields(explore_data)
    dim_names = visible.dimension_names
    measure_names = visible.measure_names

    raw_props = (base_query_def or {}).get("properties") or {}
    body_props = {
        k: copy.deepcopy(v)
        for k, v in raw_props.items()
        if not v.get("readOnly") and k != "client_id"
    }

    body_props["model"] = {
        "type": "string",
        "const": model,
        "default": model,
        "description": f"LookML Model name (pinned to '{model}')",
    }
    body_props["view"] = {
        "type": "string",
        "const": explore,
        "default": explore,
        "description": f"LookML Explore name (pinned to '{explore}')",
    }
    body_props["fields"] = build_fields_schema(dim_names, measure_names)
    body_props["pivots"] = build_pivots_schema(dim_names)
    body_props["fill_fields"] = build_fill_fields_schema(dim_names)
    body_props["subtotals"] = build_subtotals_schema(dim_names)
    body_props["sorts"] = build_sorts_schema(visible.selectable_field_names)
    body_props["filters"] = build_filters_schema(
        dimensions=visible.dimensions,
        measures=visible.measures,
        filters=visible.filters,
        parameters=visible.parameters,
    )
    body_props["limit"] = {
        "type": "string",
        "default": "500",
        "description": "Row limit (default 500). Set to -1 for unlimited results.",
    }
    body_props["dynamic_fields"] = build_dynamic_fields_schema(
        visible.selectable_field_names
    )

    return {
        "type": "object",
        "description": "inline query",
        "properties": body_props,
        "required": ["model", "view"],
        "additionalProperties": False,
    }


def build_explore_query_schema(
    model: str,
    explore: str,
    explore_data: dict[str, Any],
    swagger_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rewrite `run_inline_query` into a strongly typed JSON Schema for `<model> <explore>`."""
    swagger = swagger_data if swagger_data is not None else _get_swagger_data()
    op = (
        swagger.get("paths", {})
        .get("/queries/run/{result_format}", {})
        .get("post", {})
    )
    query_def = swagger.get("definitions", {}).get("Query", {"properties": {}})
    body_schema = build_query_body_schema(
        model, explore, explore_data, query_def
    )

    format_rows = [
        (fmt, fmt_desc)
        for fmt, fmt_desc in re.findall(
            r"^\|\s*([a-z0-9_]+)\s*\|\s*(.+?)\s*$",
            op.get("description", ""),
            re.MULTILINE,
        )
        if fmt != "result_format"
    ]

    param_defaults: dict[str, Any] = {
        "limit": 500,
        "apply_formatting": True,
        "apply_vis": True,
        "cache": True,
        "server_table_calcs": True,
        "generate_drill_links": False,
        "force_production": False,
        "cache_only": False,
        "rebuild_pdts": False,
    }
    top_props: dict[str, Any] = {}
    required_top: list[str] = []
    for param in op.get("parameters", []):
        p_name = param["name"]
        if param.get("required"):
            required_top.append(p_name)
        if p_name == "body":
            body_with_desc = dict(body_schema)
            if "description" in param:
                body_with_desc["description"] = param["description"]
            top_props["body"] = body_with_desc
        else:
            p_schema: dict[str, Any] = {"type": param.get("type", "string")}
            if "description" in param:
                p_schema["description"] = param["description"]
            if "format" in param:
                p_schema["format"] = param["format"]
            if p_name == "result_format" and format_rows:
                p_schema["enum"] = [fmt for fmt, _ in format_rows]
                p_schema["default"] = "json"
                fmt_summary = "; ".join(
                    f"{fmt}: {desc}" for fmt, desc in format_rows
                )
                p_schema["description"] = f"Format of result ({fmt_summary})"
            elif p_name in param_defaults:
                p_schema["default"] = param_defaults[p_name]
            top_props[p_name] = p_schema

    if not top_props:
        top_props = {
            "result_format": {"type": "string", "default": "json"},
            "body": body_schema,
            "limit": {"type": "integer", "default": 500},
        }
        required_top = ["result_format", "body"]

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"run_inline_query_{model}_{explore}",
        "description": f"Strongly typed run_inline_query schema for {model}::{explore}",
        "type": "object",
        "$defs": copy.deepcopy(FILTER_EXPRESSION_DEFS),
        "properties": top_props,
        "required": required_top,
    }


_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "list", "of", "on", "or", "show", "that",
    "the", "their", "to", "top", "what", "which", "with",
})


def _tokenize(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]


def normalize_explores_map(
    model: str, explores_data: dict[str, Any] | list[Any]
) -> dict[str, dict[str, Any]]:
    raw_map: dict[str, Any] = (
        {str(i["name"]): i for i in explores_data if isinstance(i, dict) and i.get("name")}
        if isinstance(explores_data, list)
        else (
            explores_data["lookml_model_explores"]
            if isinstance(explores_data.get("lookml_model_explores"), dict)
            else explores_data
        )
    )
    return {
        k.split("::")[-1]: v
        for k, v in raw_map.items()
        if isinstance(v, dict)
        and not v.get("hidden")
        and ("::" not in k or k.startswith(f"{model}::"))
    }


def build_schema_context(
    model: str,
    explores_data: dict[str, Any] | list[Any],
    prompt: str | None = None,
    top_explores: int = 3,
    max_fields_per_view: int = 35,
) -> dict[str, Any]:
    """Build a pruned LookML catalog with base_view, joins, candidate_merge_keys, and BM25-ranked fields."""
    explores_by_name = normalize_explores_map(model, explores_data)
    q_tokens = set(_tokenize(prompt or ""))

    def _score_field(f: dict[str, Any]) -> float:
        if not q_tokens:
            return 0.0
        syns = " ".join(str(x) for x in (f.get("synonyms") or []))
        tags = " ".join(str(x) for x in (f.get("tags") or []))
        blob = " ".join([
            str(f.get("name") or "").replace(".", " ").replace("_", " "),
            str(f.get("label") or ""),
            syns,
            str(f.get("description") or ""),
            tags,
            str(f.get("sql") or ""),
        ])
        return float(len(q_tokens & set(_tokenize(blob))))

    vis_by_exp = {e: extract_visible_explore_fields(d) for e, d in explores_by_name.items()}
    exp_scores: dict[str, float] = {}
    exp_field_scores: dict[str, dict[str, float]] = {}
    for ename, edata in explores_by_name.items():
        vis = vis_by_exp[ename]
        fscores = {f["name"]: _score_field(f) for f in vis.dimensions + vis.measures}
        exp_field_scores[ename] = fscores
        top10 = sum(sorted(fscores.values(), reverse=True)[:10])
        bview = str(edata.get("view_name") or ename)
        b_tokens = set(_tokenize(f"{bview.replace('_', ' ')} {edata.get('label') or ''} {edata.get('description') or ''}"))
        exp_scores[ename] = top10 + (2.0 if (q_tokens and (q_tokens & b_tokens)) else 0.0)

    ranked = sorted(explores_by_name, key=lambda e: (-exp_scores.get(e, 0.0), e))
    if top_explores > 0 and len(ranked) > top_explores:
        selected, covered = [ranked[0]], set(exp_field_scores[ranked[0]])
        for cand in ranked[1:]:
            if len(selected) < top_explores and any(sc > 0 and fn not in covered for fn, sc in exp_field_scores[cand].items()):
                selected.append(cand)
                covered |= set(exp_field_scores[cand])
        selected = (selected + [c for c in ranked if c not in selected])[:top_explores]
    else:
        selected = ranked

    view_explores: dict[str, set[str]] = {}
    field_explores: dict[str, set[str]] = {}
    for ename in selected:
        vis = vis_by_exp[ename]
        for f in vis.dimensions + vis.measures:
            view_explores.setdefault(f["name"].split(".", 1)[0], set()).add(ename)
            field_explores.setdefault(f["name"], set()).add(ename)

    candidate_merge_keys: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for i, e1 in enumerate(selected):
        for e2 in selected[i + 1 :]:
            for d1 in vis_by_exp[e1].dimensions:
                sql1 = " ".join(str(d1.get("sql") or "").split())
                t1 = str(d1.get("type") or "")
                for d2 in vis_by_exp[e2].dimensions:
                    n1, n2 = d1["name"], d2["name"]
                    if (n1, n2) in seen_pairs:
                        continue
                    sql2 = " ".join(str(d2.get("sql") or "").split())
                    t2 = str(d2.get("type") or "")
                    if n1 == n2 or (sql1 and sql1 == sql2 and "${TABLE}" not in sql1) or (t1.startswith("date_") and t1 == t2):
                        seen_pairs.add((n1, n2))
                        candidate_merge_keys.append({"field_name": n1, "source_field_name": n2})

    explores_out: dict[str, Any] = {}
    views_raw: dict[str, dict[str, list[tuple[float, str, dict[str, Any]]]]] = {}
    for ename in selected:
        edata, vis = explores_by_name[ename], vis_by_exp[ename]
        explores_out[ename] = {
            "base_view": edata.get("view_name") or ename,
            "label": edata.get("label") or ename,
            "description": edata.get("description") or "",
            "views": sorted({f["name"].split(".", 1)[0] for f in vis.dimensions + vis.measures}),
            "joins": {
                j["name"]: {
                    "type": j.get("type") or "left_outer",
                    "relationship": j.get("relationship") or "many_to_one",
                    "sql_on": j.get("sql_on") or "",
                }
                for j in (edata.get("joins") or [])
                if isinstance(j, dict) and isinstance(j.get("name"), str)
            },
        }
        for kind, items in (("dimensions", vis.dimensions), ("measures", vis.measures)):
            for item in items:
                fname = item["name"]
                vname = fname.split(".", 1)[0]
                bucket = views_raw.setdefault(vname, {"dimensions": [], "measures": []})[kind]
                if any(existing_name == fname for _, existing_name, _ in bucket):
                    continue
                fmeta: dict[str, Any] = {
                    "type": item.get("type") or "string",
                    "label": item.get("description") or item.get("label") or fname,
                }
                if item.get("synonyms"):
                    fmeta["synonyms"] = item["synonyms"]
                if sql_s := " ".join(str(item.get("sql") or "").split()):
                    fmeta["sql"] = sql_s[:220]
                if item.get("filters"):
                    fmeta["filters"] = item["filters"]
                if field_explores[fname] < view_explores[vname]:
                    fmeta["explores"] = sorted(field_explores[fname])
                bucket.append((exp_field_scores[ename].get(fname, 0.0), fname, fmeta))

    views_out = {
        vname: {
            kind: {
                fname: fmeta
                for _, fname, fmeta in (
                    sorted(entries, key=lambda x: (-x[0], x[1]))[:max_fields_per_view]
                    if q_tokens and max_fields_per_view > 0 and len(entries) > max_fields_per_view
                    else entries
                )
            }
            for kind, entries in kinds.items()
        }
        for vname, kinds in sorted(views_raw.items())
    }

    return {
        "model": model,
        "explores": explores_out,
        "candidate_merge_keys": candidate_merge_keys,
        "views": views_out,
    }
