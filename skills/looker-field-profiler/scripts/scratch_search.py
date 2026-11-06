"""Main orchestrator to profile LookML string columns, generate each Explore query via run_inline_query(result_format="sql"), and write per-model _field_value_search_<model> PDT views and hidden Explores."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dialects import bigquery, databricks, duckdb, postgres, snowflake  # noqa: E402

DIALECT_MODULES = (bigquery, snowflake, postgres, databricks, duckdb)
SEARCHABLE_SUBTYPES = {"enum", "categorical", "entity_label", "tier"}
EXCLUDED_TAGS = {
    "profile:pii",
    "profile:email",
    "profile:phone",
    "profile:json_payload",
    "profile:uuid_or_hash",
    "profile:empty_or_null_only",
    "pii",
    "email",
    "phone",
}
TAG_TO_SUBTYPE = {
    "profile:low_cardinality_enum": "enum",
    "low_cardinality_enum": "enum",
    "profile:medium_cardinality_categorical": "categorical",
    "medium_cardinality_categorical": "categorical",
    "profile:searchable_entity_label": "entity_label",
    "searchable_entity_label": "entity_label",
    "profile:tier": "tier",
}
SUBTYPE_TO_TAG = {
    "enum": "profile:low_cardinality_enum",
    "categorical": "profile:medium_cardinality_categorical",
    "entity_label": "profile:searchable_entity_label",
    "tier": "profile:tier",
    "id_or_code": "profile:opaque_code_or_free_text",
    "free_text": "profile:opaque_code_or_free_text",
}


def view_name_for_model(model_name: str) -> str:
    return f"_field_value_search_{re.sub(r'[^a-zA-Z0-9_]', '_', model_name.strip())}"


def resolve_dialect_module(dialect_name: str) -> Any:
    low = dialect_name.strip().lower()
    for mod in DIALECT_MODULES:
        if low in mod.DIALECT_NAMES or low == mod.__name__.split(".")[-1]:
            return mod
    for mod in DIALECT_MODULES:
        if any(d in low or low in d for d in mod.DIALECT_NAMES):
            return mod
    raise ValueError(
        f"Unsupported dialect '{dialect_name}'. Supported: "
        + ", ".join(m.__name__.split(".")[-1] for m in DIALECT_MODULES)
    )


def strip_looker_order_and_limit(sql: str, limit_per_field: int = 0) -> str:
    # ponytail: Looker's run_inline_query(result_format="sql") with limit="-1" still appends LIMIT 100000 (or FETCH FIRST); strip Limit and ORDER BY independently
    cleaned = re.sub(
        r"\s*(?:LIMIT\s+\d+|FETCH\s+FIRST\s+\d+\s+ROWS\s+ONLY)\s*;?\s*$",
        "",
        sql.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*ORDER\s+BY\s+[\w.,\s`\"']+\s*;?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if limit_per_field and int(limit_per_field) > 0:
        cleaned = f"{cleaned}\nLIMIT {int(limit_per_field)}"
    if re.match(r"^WITH\b", cleaned, flags=re.IGNORECASE) or (limit_per_field and int(limit_per_field) > 0):
        return f"SELECT * FROM (\n{cleaned}\n)"
    return cleaned


def generate_inline_branch_sql(
    sdk: Any,
    model_name: str,
    explore_name: str,
    field_name: str,
    subtype: str,
    limit_per_field: int = 0,
) -> str:
    raw_sql = sdk.run_inline_query(
        result_format="sql",
        body={
            "model": model_name,
            "view": explore_name,
            "fields": ["model_name", "explore_name", "field_name", "subtype", "field_value"],
            "filters": {field_name: "-NULL, -EMPTY"},
            "limit": "-1",
            "dynamic_fields": json.dumps([
                {"dimension": "model_name", "label": "model_name", "expression": json.dumps(model_name)},
                {"dimension": "explore_name", "label": "explore_name", "expression": json.dumps(explore_name)},
                {"dimension": "field_name", "label": "field_name", "expression": json.dumps(field_name)},
                {"dimension": "subtype", "label": "subtype", "expression": json.dumps(subtype)},
                {"dimension": "field_value", "label": "field_value", "expression": f"${{{field_name}}}"},
            ]),
        },
    )
    return strip_looker_order_and_limit(str(raw_sql), limit_per_field=limit_per_field)


def build_union_all_sql(branch_sqls: list[str]) -> str:
    return "\nUNION ALL\n".join(b.strip() for b in branch_sqls if b and b.strip())


def build_hidden_explore_lookml(
    pdt_steps: list[str],
    model_name: str = "model",
    sql_trigger_value: str = "SELECT CURRENT_DATE",
) -> str:
    v_name = view_name_for_model(model_name)
    steps_block = "\n".join(
        "      sql_step:\n"
        + "\n".join(f"        {ln}" for ln in stmt.strip().splitlines())
        + " ;;"
        for stmt in pdt_steps
    )
    return f"""view: {v_name} {{
  derived_table: {{
    sql_trigger_value: {sql_trigger_value.strip()} ;;
    create_process: {{
{steps_block}
    }}
  }}

  dimension: pk {{
    primary_key: yes
    hidden: yes
    type: string
    sql: CONCAT(${{explore_name}}, '::', ${{field_name}}, '::', ${{field_value}}) ;;
  }}

  dimension: model_name {{
    type: string
    sql: ${{TABLE}}.model_name ;;
  }}

  dimension: explore_name {{
    type: string
    sql: ${{TABLE}}.explore_name ;;
  }}

  dimension: field_name {{
    type: string
    sql: ${{TABLE}}.field_name ;;
  }}

  dimension: subtype {{
    type: string
    sql: ${{TABLE}}.subtype ;;
    description: "Profiled string subtype: enum, categorical, entity_label, or tier."
  }}

  dimension: field_value {{
    type: string
    sql: ${{TABLE}}.field_value ;;
  }}

  measure: count {{
    type: count
    description: "Count of distinct matching string values."
  }}
}}

explore: {v_name} {{
  hidden: yes
  label: "Field Value Search Index ({model_name})"
  description: "Hidden search index over profiled string values for model {model_name}."
}}
"""


def _get_attr(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def discover_model_string_candidates(
    sdk: Any | None,
    model_name: str,
    lookml_path: Path | None = None,
    explore_filter: list[str] | None = None,
    include_calculated: bool = False,
) -> list[dict[str, Any]]:
    """Collect candidate string dimensions per (explore_name, field_name) across the model."""
    explores_payloads: list[tuple[str, Any]] = []
    if lookml_path is not None:
        from lkr.parse.lookml_to_api import parse_lookml_to_api

        api_res = parse_lookml_to_api(lookml_path, model=model_name)
        for key, exp_obj in (api_res.lookml_model_explores or {}).items():
            m_part, e_name = key.split("::", 1) if "::" in key else (model_name, key)
            if m_part != model_name:
                continue
            if explore_filter and e_name not in explore_filter:
                continue
            if not explore_filter and (_get_attr(exp_obj, "hidden") or e_name.startswith("_field_value_search")):
                continue
            explores_payloads.append((e_name, exp_obj))
    else:
        if sdk is None:
            raise ValueError("SDK is required when --path is not provided.")
        m_obj = sdk.lookml_model(lookml_model_name=model_name)
        for e in _get_attr(m_obj, "explores") or []:
            e_name = str(_get_attr(e, "name") or "")
            if not e_name:
                continue
            if explore_filter and e_name not in explore_filter:
                continue
            if not explore_filter and (_get_attr(e, "hidden") or e_name.startswith("_field_value_search")):
                continue
            try:
                explores_payloads.append(
                    (e_name, sdk.lookml_model_explore(lookml_model_name=model_name, explore_name=e_name))
                )
            except Exception:
                continue

    candidates: list[dict[str, Any]] = []
    for e_name, exp_obj in explores_payloads:
        fields_obj = _get_attr(exp_obj, "fields")
        dims = (_get_attr(fields_obj, "dimensions") if fields_obj else None) or []
        conn_name = str(_get_attr(exp_obj, "connection_name") or "")
        for d in dims:
            if _get_attr(d, "type") != "string" or _get_attr(d, "hidden") or _get_attr(d, "primary_key"):
                continue
            if _get_attr(d, "dimension_group"):
                continue
            full_name = str(_get_attr(d, "name") or "")
            sql_expr = str(_get_attr(d, "sql") or "").strip()
            # ponytail: default to physical ${TABLE}.<col> dimensions; CASE WHEN literals are already visible in LookML
            if not full_name or (not include_calculated and not re.match(r"^\$\{TABLE\}\.[a-zA-Z0-9_`\"$]+$", sql_expr)):
                continue
            tags = [str(t) for t in (_get_attr(d, "tags") or [])]
            if any(t in EXCLUDED_TAGS for t in tags):
                continue
            candidates.append({
                "model_name": model_name,
                "explore_name": e_name,
                "field_name": full_name,
                "sql": sql_expr,
                "tags": tags,
                "connection_name": conn_name,
            })
    return candidates


def profile_and_filter_searchable_columns(
    sdk: Any,
    model_name: str,
    candidates: list[dict[str, Any]],
    include_codes: bool = False,
    include_free_text: bool = False,
    force_profile: bool = False,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    allowed_subtypes = (
        set(SEARCHABLE_SUBTYPES)
        | ({"id_or_code"} if include_codes else set())
        | ({"free_text"} if include_free_text else set())
    )
    searchable: list[dict[str, Any]] = []
    by_explore: dict[str, list[dict[str, Any]]] = {}

    for col in candidates:
        matched_sub = next((TAG_TO_SUBTYPE[t] for t in col["tags"] if t in TAG_TO_SUBTYPE), None)
        if matched_sub and not force_profile:
            col["subtype"] = matched_sub
            col["suggested_tag"] = SUBTYPE_TO_TAG[matched_sub]
            searchable.append(col)
        else:
            by_explore.setdefault(col["explore_name"], []).append(col)

    for exp_name, cols in by_explore.items():
        for i in range(0, len(cols), batch_size):
            batch = cols[i : i + batch_size]
            try:
                prof_res = sdk.profile_fields(
                    model=model_name,
                    view=exp_name,
                    fields=[c["field_name"] for c in batch],
                )
            except Exception:
                continue
            profiles = (prof_res.get("profiles") if isinstance(prof_res, dict) else None) or {}
            for c in batch:
                p = profiles.get(c["field_name"]) or {}
                sub = str(p.get("subtype") or "")
                s_tags = [str(t) for t in (p.get("suggested_tags") or [])]
                if any(t in EXCLUDED_TAGS for t in s_tags):
                    continue
                short_low = c["field_name"].split(".")[-1].lower()
                is_named_label = short_low in ("name", "title") or short_low.endswith(("_name", "_title"))
                if sub in allowed_subtypes or (sub == "free_text" and is_named_label):
                    c["subtype"] = sub
                    c["suggested_tag"] = SUBTYPE_TO_TAG.get(sub, s_tags[0] if s_tags else "")
                    c["approx_count_distinct"] = p.get("approx_count_distinct")
                    searchable.append(c)

    return sorted(searchable, key=lambda x: (x["explore_name"], x["field_name"]))


def detect_dialect(sdk: Any, candidates: list[dict[str, Any]]) -> str:
    for c in candidates:
        conn_name = c.get("connection_name")
        if conn_name:
            try:
                conn = sdk.connection(conn_name)
                d_obj = _get_attr(conn, "dialect")
                d_name = _get_attr(d_obj, "name") if d_obj else _get_attr(conn, "dialect_name")
                if d_name:
                    return str(d_name)
            except Exception:
                break
    return "bigquery"


def cli_main(default_dialect: str | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Profile LookML string fields, compile Explore queries via run_inline_query(result_format='sql'), and generate per-model _field_value_search_<model> PDT views & hidden Explores."
    )
    parser.add_argument("--model", required=True, help="Comma-separated LookML model name(s) (e.g. agentic_thelook,streaming_platform_analytics)")
    parser.add_argument("--explore", default="", help="Optional comma-separated Explore names (defaults to all visible Explores)")
    parser.add_argument("--path", default="", help="Optional local LookML directory path for offline model/explore discovery")
    parser.add_argument("--dialect", default=default_dialect or "", help="Dialect (bigquery, snowflake, postgres, databricks, duckdb)")
    parser.add_argument("--limit-per-field", type=int, default=0, help="Optional cap on distinct values persisted per field (default: 0 = unlimited)")
    parser.add_argument("--include-codes", action="store_true", help="Include non-PII id_or_code fields (e.g. SKU, postal_code)")
    parser.add_argument("--include-free-text", action="store_true", help="Include all free_text fields in addition to named labels")
    parser.add_argument("--include-calculated", action="store_true", help="Include calculated SQL dimensions in addition to ${TABLE}.col")
    parser.add_argument("--force-profile", action="store_true", help="Re-run profile_fields even when LookML already has profile:* tags")
    parser.add_argument("--search", default="", help="Optional search term to generate a search query against _field_value_search_<model>")
    parser.add_argument("--search-limit", type=int, default=25, help="Max search results to return (default: 25)")
    parser.add_argument("--sql-trigger", default="SELECT CURRENT_DATE", help="SQL trigger value for the PDT view (default: SELECT CURRENT_DATE)")
    parser.add_argument("--write-lookml", default="", help="Optional file or directory path to write _field_value_search_<model>.explore.lkml")
    parser.add_argument("--oauth-account", default=None, help="Optional lkr OAuth account name (e.g. dev-argolis)")
    parser.add_argument("--dev", action="store_true", help="Use Looker developer workspace session")
    args = parser.parse_args()

    from lkr.auth_service import get_auth
    from lkr.classes import LkrCtxObj

    ctx = LkrCtxObj(
        force_oauth=bool(args.oauth_account),
        use_production=not args.dev,
        oauth_account=args.oauth_account,
    )
    sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=True)

    model_names = [m.strip() for m in args.model.split(",") if m.strip()]
    explore_filter = [e.strip() for e in args.explore.split(",") if e.strip()] or None
    lookml_path = Path(args.path).resolve() if args.path else None
    multi_model = len(model_names) > 1
    results: list[dict[str, Any]] = []

    for model_name in model_names:
        candidates = discover_model_string_candidates(
            sdk=sdk,
            model_name=model_name,
            lookml_path=lookml_path,
            explore_filter=explore_filter,
            include_calculated=args.include_calculated,
        )
        searchable_cols = profile_and_filter_searchable_columns(
            sdk=sdk,
            model_name=model_name,
            candidates=candidates,
            include_codes=args.include_codes,
            include_free_text=args.include_free_text,
            force_profile=args.force_profile,
        )
        if not searchable_cols:
            raise RuntimeError(f"No searchable string columns found for model '{model_name}'.")

        branch_sqls = [
            generate_inline_branch_sql(
                sdk=sdk,
                model_name=model_name,
                explore_name=col["explore_name"],
                field_name=col["field_name"],
                subtype=col["subtype"],
                limit_per_field=args.limit_per_field,
            )
            for col in searchable_cols
        ]
        dialect_key = args.dialect.strip() or detect_dialect(sdk, candidates)
        dialect_mod = resolve_dialect_module(dialect_key)
        pdt_steps = dialect_mod.build_persist_sql(build_union_all_sql(branch_sqls))
        v_name = view_name_for_model(model_name)
        lookml_text = build_hidden_explore_lookml(
            pdt_steps=pdt_steps,
            model_name=model_name,
            sql_trigger_value=args.sql_trigger,
        )

        out: dict[str, Any] = {
            "model": model_name,
            "view_name": v_name,
            "explore_name": v_name,
            "dialect": dialect_key,
            "dialect_script": f"dialects/{dialect_mod.__name__.split('.')[-1]}.py",
            "searchable_column_count": len(searchable_cols),
            "searchable_columns": [
                {
                    "explore_name": c["explore_name"],
                    "field_name": c["field_name"],
                    "subtype": c["subtype"],
                    "suggested_tag": c["suggested_tag"],
                    "approx_count_distinct": c.get("approx_count_distinct"),
                }
                for c in searchable_cols
            ],
            "pdt_create_process_steps": pdt_steps,
        }
        if args.search.strip():
            out["search_sql"] = dialect_mod.build_search_sql(
                search_query=args.search.strip(),
                table_ref=f"${{{v_name}.SQL_TABLE_NAME}}",
                limit=args.search_limit,
            )
        if args.write_lookml.strip():
            raw_target = Path(args.write_lookml).resolve()
            if multi_model or raw_target.is_dir() or not raw_target.name.endswith(".lkml"):
                raw_target.mkdir(parents=True, exist_ok=True)
                target = raw_target / f"{v_name}.explore.lkml"
            else:
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                target = raw_target
            target.write_text(lookml_text, encoding="utf-8")
            out["lookml_written_to"] = str(target)
        else:
            out["hidden_explore_lookml"] = lookml_text
        results.append(out)

    print(json.dumps({"models": results} if multi_model else results[0], indent=2, default=str))


if __name__ == "__main__":
    cli_main()
