"""Extract LookML field curation metadata and code-mode sandbox variables from local LookML via lkr parse lookml-to-api."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from lkr.parse.lookml import LookmlExplore, LookmlView, parse_lookml
from lkr.parse.lookml_to_api import LookmlToApiResult, parse_lookml_to_api


def parse_sql_table_name(raw_sql_table_name: str | None) -> dict[str, str | None]:
    if not raw_sql_table_name:
        return {"raw": None, "table_expr": None, "catalog": None, "schema": None, "table": None}
    cleaned = re.sub(
        r"\s+AS\s+[a-zA-Z0-9_]+\s*$", "", raw_sql_table_name.strip(), flags=re.IGNORECASE
    ).strip()
    parts = [p.strip('`" ') for p in cleaned.split(".") if p.strip('`" ')]
    catalog, schema, table = [None, None, None, *parts][-3:]
    return {
        "raw": raw_sql_table_name,
        "table_expr": cleaned,
        "catalog": catalog,
        "schema": schema,
        "table": table,
    }


def extract_sql_column(sql_expr: str | None, view_alias: str) -> str | None:
    pattern = rf"^(?:\$\{{\s*TABLE\s*\}}|{re.escape(view_alias)})\.[`\"]?([a-zA-Z0-9_]+)[`\"]?\s*$"
    m = re.match(pattern, (sql_expr or "").strip())
    return m.group(1) if m else None


def extract_lookml_refs(sql_expr: str | None, default_view: str) -> list[str]:
    refs = (
        raw_ref if "." in raw_ref else f"{default_view}.{raw_ref}"
        for raw_ref in re.findall(r"\$\{\s*([a-zA-Z0-9_.]+)\s*\}", sql_expr or "")
        if raw_ref.upper() not in ("TABLE", "EXTENDED")
        and not raw_ref.endswith(".SQL_TABLE_NAME")
    )
    return list(dict.fromkeys(refs))


def _ensure_view(
    views_map: dict[str, dict[str, Any]], v_alias: str, orig_view: str
) -> dict[str, Any]:
    return views_map.setdefault(
        v_alias,
        {
            "view_alias": v_alias,
            "original_view": orig_view,
            "dimensions": [],
            "dimension_groups": [],
            "measures": [],
            "string_fields": [],
            "string_columns": [],
            "all_columns_for_enrichment": [],
            "static_curation_candidates": [],
        },
    )


def build_api_result_from_lookml(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    model: str | None = None,
    explore: str | None = None,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> LookmlToApiResult:
    proj = parse_lookml(
        path=path, file=file, lookml=lookml, manifest=manifest, constants=constants
    )
    for m_obj in (proj.model or {}).values():
        m_obj.explore = m_obj.explore or {}
        explored_views = {
            (e_obj.from_ or e_obj.view_name or e_name)
            for e_name, e_obj in m_obj.explore.items()
            if isinstance(e_obj, LookmlExplore)
        }
        for v_name, v_obj in (m_obj.view or {}).items():
            if (
                isinstance(v_obj, LookmlView)
                and not v_obj.extension
                and v_name not in m_obj.explore
                and v_name not in explored_views
            ):
                m_obj.explore[v_name] = LookmlExplore(view_name=v_name)
    return parse_lookml_to_api(project=proj, model=model, explore=explore)


def extract_curation_metadata(
    api_payload: dict[str, Any] | LookmlToApiResult,
    view_filter: str | None = None,
) -> dict[str, Any]:
    data = (
        api_payload.model_dump(by_alias=True)
        if isinstance(api_payload, LookmlToApiResult)
        else api_payload
    )
    models_out = [
        {
            "name": m.get("name"),
            "project_name": m.get("project_name"),
            "allowed_db_connection_names": m.get("allowed_db_connection_names") or [],
            "explores": [e.get("name") for e in (m.get("explores") or []) if isinstance(e, dict)],
        }
        for m in (data.get("all_lookml_models") or [])
    ]

    explores_out: dict[str, Any] = {}
    for exp_id, exp in (data.get("lookml_model_explores") or {}).items():
        if not isinstance(exp, dict):
            continue
        model_name = str(exp.get("model_name") or "")
        explore_name = str(exp.get("name") or "")
        base_view = str(exp.get("view_name") or explore_name)
        conn_name = exp.get("connection_name")
        parsed_tbl = parse_sql_table_name(exp.get("sql_table_name"))

        fields_block = exp.get("fields") or {}
        all_dims = fields_block.get("dimensions") or []
        all_meas = fields_block.get("measures") or []
        all_filts = fields_block.get("filters") or []

        referenced_by: dict[str, list[str]] = {}
        field_labels: dict[str, dict[str, str]] = {}
        for f in (*all_dims, *all_meas, *all_filts):
            if isinstance(f, dict):
                f_name = str(f.get("name") or "")
                f_view = str(f.get("view") or base_view)
                if f_name:
                    field_labels[f_name] = {
                        "label": str(f.get("label") or ""),
                        "label_short": str(f.get("label_short") or ""),
                    }
                for ref in extract_lookml_refs(f.get("sql"), f_view):
                    if f_name not in referenced_by.setdefault(ref, []):
                        referenced_by[ref].append(f_name)

        views_map: dict[str, dict[str, Any]] = {}
        seen_dgs: set[tuple[str, str]] = set()

        for d in all_dims:
            if not isinstance(d, dict):
                continue
            v_alias = str(d.get("view") or base_view)
            orig_view = str(d.get("original_view") or v_alias)
            if view_filter and view_filter not in (v_alias, orig_view):
                continue
            v_entry = _ensure_view(views_map, v_alias, orig_view)

            full_name = str(d.get("name") or "")
            short_name = full_name.split(".", 1)[-1]
            label = str(d.get("label") or "")
            label_short = str(d.get("label_short") or "")
            dtype = str(d.get("type") or "string")
            desc = str(d.get("description") or "")
            hidden = bool(d.get("hidden", False))
            suggestable = bool(d.get("suggestable", False))
            pk = bool(d.get("primary_key", False))
            dg = d.get("dimension_group")
            sql_raw = d.get("sql")
            sql_str = sql_raw.strip() if isinstance(sql_raw, str) else None
            sql_col = extract_sql_column(sql_str, v_alias)
            sql_refs = extract_lookml_refs(sql_str, v_alias)
            refs_to_this = referenced_by.get(full_name, [])
            is_helper = bool(refs_to_this) and short_name.lower().startswith(
                ("_", "helper_", "tmp_", "raw_")
            )

            if dg:
                dg_str = str(dg)
                if (v_alias, dg_str) not in seen_dgs:
                    seen_dgs.add((v_alias, dg_str))
                    tf_labels = field_labels.get(f"{dg_str}_date") or {}
                    dg_label_short = str(
                        tf_labels.get("label_short")
                        or d.get("field_group_label")
                        or label_short
                    )
                    dg_label = str(tf_labels.get("label") or label or dg_label_short)
                    dg_entry = {
                        "name": dg_str,
                        "short_name": dg_str.split(".", 1)[-1],
                        "label": dg_label,
                        "label_short": dg_label_short,
                        "category": "dimension_group",
                        "dimension_group": dg_str,
                        "sql_column": sql_col,
                        "description": desc,
                        "synonyms": list(d.get("synonyms") or []),
                        "tags": list(d.get("tags") or []),
                    }
                    v_entry["dimension_groups"].append(dg_entry)
                    v_entry["all_columns_for_enrichment"].append(dg_entry)
                continue

            f_tags = list(d.get("tags") or [])
            v_entry["dimensions"].append({
                "name": full_name,
                "short_name": short_name,
                "label": label,
                "label_short": label_short,
                "type": dtype,
                "description": desc,
                "synonyms": list(d.get("synonyms") or []),
                "tags": f_tags,
                "hidden": hidden,
                "suggestable": suggestable,
                "primary_key": pk,
                "sql": sql_str,
                "sql_column": sql_col,
                "referenced_fields": [
                    {"name": r, **field_labels.get(r, {})} for r in sql_refs
                ],
                "referenced_by": refs_to_this,
                "referenced_by_labels": [
                    field_labels.get(r, {}).get("label_short") or r for r in refs_to_this
                ],
                "is_helper": is_helper,
            })
            v_entry["all_columns_for_enrichment"].append({
                "name": full_name,
                "short_name": short_name,
                "label": label,
                "label_short": label_short,
                "category": "dimension",
                "dimension_group": None,
                "sql_column": sql_col or short_name,
                "description": desc,
                "tags": f_tags,
            })

            if dtype == "string" and not d.get("sql_case") and not d.get("enumerations"):
                v_entry["string_fields"].append(full_name)
                v_entry["string_columns"].append({
                    "field_name": full_name,
                    "short_name": short_name,
                    "label": label,
                    "label_short": label_short,
                    "sql_column": sql_col or short_name,
                    "primary_key": pk,
                    "hidden": hidden,
                    "suggestable": suggestable,
                    "description": desc,
                    "tags": f_tags,
                    "sql": sql_str or "",
                    "is_helper": is_helper,
                })

            low_s = short_name.lower()
            is_fk_cand = not pk and low_s.endswith(("_id", "_fk"))
            reason = (
                "primary_key_visible"
                if pk and not hidden
                else "intermediate_helper_dimension"
                if is_helper and not hidden
                else "raw_json_or_payload_column"
                if re.search(r"(^|_)(json|payload|raw_event)($|_)", low_s)
                and (not hidden or suggestable)
                else "system_or_etl_audit_column"
                if re.search(r"^(_fivetran_|_airbyte_|_sdc_|_baton_|etl_|ingest_)", low_s)
                and not hidden
                else "foreign_key_visible"
                if is_fk_cand and (not hidden or "foreign_key" not in f_tags)
                else None
            )
            if reason:
                cand_entry: dict[str, Any] = {
                    "field_name": full_name,
                    "label_short": label_short,
                    "reason": reason,
                    "recommended_hidden": True,
                    "recommended_suggestable": False,
                }
                if reason == "foreign_key_visible":
                    cand_entry["recommended_tags"] = list(dict.fromkeys([*f_tags, "foreign_key"]))
                v_entry["static_curation_candidates"].append(cand_entry)

        for m in all_meas:
            if not isinstance(m, dict):
                continue
            v_alias = str(m.get("view") or base_view)
            orig_view = str(m.get("original_view") or v_alias)
            if view_filter and view_filter not in (v_alias, orig_view):
                continue
            v_entry = _ensure_view(views_map, v_alias, orig_view)

            full_name = str(m.get("name") or "")
            label = str(m.get("label") or "")
            label_short = str(m.get("label_short") or "")
            desc = str(m.get("description") or "")
            hidden = bool(m.get("hidden", False))
            sql_raw = m.get("sql")
            sql_str = sql_raw.strip() if isinstance(sql_raw, str) else None
            sql_refs = extract_lookml_refs(sql_str, v_alias)
            v_entry["measures"].append({
                "name": full_name,
                "short_name": full_name.split(".", 1)[-1],
                "label": label,
                "label_short": label_short,
                "type": str(m.get("type") or "string"),
                "description": desc,
                "synonyms": list(m.get("synonyms") or []),
                "tags": list(m.get("tags") or []),
                "hidden": hidden,
                "sql": sql_str,
                "referenced_fields": [
                    {"name": r, **field_labels.get(r, {})} for r in sql_refs
                ],
                "filters": [
                    {
                        **flt,
                        "field_label_short": field_labels.get(
                            str(flt.get("field") or ""), {}
                        ).get("label_short", ""),
                    }
                    if isinstance(flt, dict)
                    else flt
                    for flt in (m.get("filters") or [])
                ],
            })
            if not desc.strip() and not hidden:
                v_entry["static_curation_candidates"].append({
                    "field_name": full_name,
                    "label_short": label_short,
                    "reason": "measure_missing_description",
                    "recommended_hidden": False,
                })

        target_v = view_filter if (view_filter and view_filter in views_map) else base_view
        target_v_obj = views_map.get(target_v) or (
            next(iter(views_map.values())) if views_map else {}
        )
        resolved_view = target_v_obj.get("original_view") or target_v

        explores_out[exp_id] = {
            "id": exp_id,
            "model_name": model_name,
            "explore_name": explore_name,
            "view_name": base_view,
            "connection_name": conn_name,
            "sql_table_name": exp.get("sql_table_name"),
            "parsed_table": parsed_tbl,
            "views": views_map,
            "sandbox_vars": {
                "profile_string_fields": {
                    "model_name": model_name,
                    "connection_name": conn_name or "",
                    "explore_name": explore_name,
                    "view_name": resolved_view,
                    "table_name": parsed_tbl.get("table_expr") or "",
                    "fields_json": json.dumps(target_v_obj.get("string_columns") or []),
                },
                "enrich_partition_clustering": {
                    "model_name": model_name,
                    "connection_name": conn_name or "",
                    "project_id": parsed_tbl.get("catalog") or "",
                    "dataset_name": parsed_tbl.get("schema") or "",
                    "table_name": parsed_tbl.get("table") or parsed_tbl.get("table_expr") or "",
                    "view_name": resolved_view,
                    "fields_json": json.dumps(
                        target_v_obj.get("all_columns_for_enrichment") or []
                    ),
                },
            },
        }

    return {"models": models_out, "explores": explores_out}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local LookML metadata via lkr parse lookml-to-api for field curation."
    )
    parser.add_argument("--path", "-p", type=Path, help="Path to LookML project directory")
    parser.add_argument("--file", "-f", type=Path, help="Path to a single LookML file")
    parser.add_argument("--lookml", "-l", type=str, help="Inline LookML string")
    parser.add_argument(
        "--api-json",
        type=str,
        help="Path to JSON output from 'lkr parse lookml-to-api' (or '-' for stdin)",
    )
    parser.add_argument("--model", "-m", type=str, help="Optional LookML model filter")
    parser.add_argument("--explore", "-e", type=str, help="Optional LookML explore filter")
    parser.add_argument("--view", "-v", type=str, help="Optional LookML view filter")
    parser.add_argument("--manifest", type=Path, help="Optional explicit manifest.lkml file path")
    parser.add_argument(
        "--constant",
        "-C",
        action="append",
        help="Constant override KEY=VALUE (repeatable)",
    )
    parser.add_argument("--output", "-o", type=Path, help="Optional output JSON file path")
    args = parser.parse_args(argv)

    if args.api_json:
        raw_text = (
            sys.stdin.read()
            if args.api_json == "-"
            else Path(args.api_json).read_text(encoding="utf-8")
        )
        api_payload = json.loads(raw_text)
    else:
        if sum(x is not None for x in (args.path, args.file, args.lookml)) != 1:
            parser.error("Specify either --api-json or exactly one of --path, --file, or --lookml")
        if any("=" not in c or not c.split("=", 1)[0].strip() for c in (args.constant or [])):
            parser.error("Invalid --constant; expected KEY=VALUE")
        const_overrides = (
            {k.strip(): v for k, v in (c.split("=", 1) for c in args.constant)}
            if args.constant
            else None
        )
        api_payload = build_api_result_from_lookml(
            path=args.path,
            file=args.file,
            lookml=args.lookml,
            model=args.model,
            explore=args.explore,
            manifest=args.manifest,
            constants=const_overrides,
        )

    out_text = json.dumps(extract_curation_metadata(api_payload, view_filter=args.view), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out_text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(out_text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
