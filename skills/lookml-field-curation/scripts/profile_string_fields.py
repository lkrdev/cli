# ruff: noqa: F821, BLE001
"""Profile LookML string dimensions via Explore inline queries or SQL Runner in lkr code-mode sandbox."""

import json
import re


def _parse_rows(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return raw if isinstance(raw, list) else []


def _ensure_period(text: str) -> str:
    cleaned = text.strip()
    return (cleaned if cleaned[-1] in ".!?" else cleaned + ".") if cleaned else ""


def _is_json_value(val: str) -> bool:
    s = val.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            return isinstance(json.loads(s), (dict, list))
        except Exception:
            return False
    return False


def _is_uuid_or_hex_hash(val: str) -> bool:
    return bool(
        re.match(
            r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32,64})$",
            val.strip(),
        )
    )


def classify_string_field(
    field_meta: dict,
    sample_values: list[str],
    distinct_count: int,
    null_or_empty_count: int,
    total_rows: int,
    max_length: int,
    avg_length: float,
    enum_threshold: int = 15,
    categorical_threshold: int = 100,
    top_n: int = 10,
) -> dict:
    full_name = str(field_meta.get("field_name") or field_meta.get("name") or "")
    short_name = str(field_meta.get("short_name") or full_name.split(".")[-1])
    label = str(field_meta.get("label") or "")
    label_short = str(field_meta.get("label_short") or "")
    low_name = short_name.lower()
    sql_expr = str(field_meta.get("sql") or "")
    existing_desc = str(field_meta.get("description") or "").strip()
    is_pk = bool(field_meta.get("primary_key"))
    is_helper = bool(field_meta.get("is_helper")) or low_name.startswith(("_", "helper_", "tmp_"))
    base_prefix = (_ensure_period(existing_desc) + " ") if existing_desc else ""

    non_empty = [str(v).strip() for v in sample_values if v is not None and str(v).strip() != ""]
    json_hits = sum(1 for v in non_empty if _is_json_value(v))
    uuid_hits = sum(1 for v in non_empty if _is_uuid_or_hex_hash(v))

    is_json_col = (
        bool(re.search(r"(^|_)(json|payload|raw_event|proto|xml)($|_)", low_name))
        or "JSON_" in sql_expr.upper()
        or (bool(non_empty) and json_hits * 2 >= len(non_empty))
    )
    is_uuid_col = bool(
        re.search(r"(^|_)(uuid|guid|hash|md5|sha256|row_hash|record_hash)($|_)", low_name)
    ) or (bool(non_empty) and uuid_hits * 5 >= len(non_empty) * 4)
    is_system_col = bool(
        re.search(r"^(_fivetran_|_airbyte_|_sdc_|_baton_|etl_|ingest_)|(_pk|_fk|_sk)$", low_name)
    )
    is_internal_id = (
        is_pk
        or is_system_col
        or is_helper
        or (
            (low_name == "id" or low_name.endswith("_id"))
            and not is_uuid_col
            and distinct_count > categorical_threshold
        )
    )
    is_free_text_or_token = (
        max_length > 120
        or avg_length > 60.0
        or bool(
            re.search(
                r"(^|_)(comment|comments|note|notes|description|message|body|transcript|feedback|reason_text|free_text|url|uri|path|ip|ip_address|email|sku|tracking_number|session_id|token)$",
                low_name,
            )
        )
    )
    is_opaque_code = is_free_text_or_token or bool(
        re.search(
            r"(^|_)(code|zip|postal|phone|barcode|upc|ean|isbn|serial|key|ref|num|number)$",
            low_name,
        )
    )
    code_val_hits = sum(
        1
        for v in non_empty
        if re.match(r"^(?:https?://|\S+@\S+|[0-9.\-:/_]+|[A-Z0-9_\-]{4,})$", v)
        and re.search(r"[\d@:/_]", v)
    )
    is_code_values = bool(non_empty) and code_val_hits * 2 >= len(non_empty)

    if is_json_col:
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "json_payload",
            True,
            False,
            f"{base_prefix}Raw JSON payload; hidden and filter suggestions disabled to prevent full-column scans.",
        )
    elif is_internal_id:
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "surrogate_or_system_key",
            True,
            False,
            f"{base_prefix}Internal key or system metadata column not intended for end-user grouping.",
        )
    elif is_uuid_col:
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "uuid_or_hash",
            True,
            False,
            f"{base_prefix}High-cardinality UUID or hash identifier.",
        )
    elif distinct_count == 0:
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "empty_or_null_only",
            True,
            False,
            f"{base_prefix}Column contains only NULL or empty values in sampled data.",
        )
    elif not is_free_text_or_token and distinct_count <= enum_threshold:
        vals_str = ", ".join(f"'{v}'" for v in non_empty[:enum_threshold])
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "low_cardinality_enum",
            False,
            True,
            f"{base_prefix}Values: {vals_str}.",
        )
    elif not is_free_text_or_token and distinct_count <= categorical_threshold:
        vals_str = ", ".join(f"'{v}'" for v in non_empty[:top_n])
        classification, rec_hidden, rec_suggestable, rec_desc = (
            "medium_cardinality_categorical",
            False,
            True,
            f"{base_prefix}Top values include: {vals_str} ({distinct_count} distinct values).",
        )
    else:
        sample_preview = ", ".join(f"'{v[:40]}'" for v in non_empty[:3])
        preview_suffix = f" Example values: {sample_preview}." if sample_preview else ""
        rec_hidden = False
        rec_suggestable = not is_opaque_code and not is_code_values
        classification = "searchable_entity_label" if rec_suggestable else "opaque_code_or_free_text"
        rec_desc = (
            f"{base_prefix}Searchable entity label ({distinct_count}+ distinct values).{preview_suffix}"
            if rec_suggestable
            else f"{base_prefix}Opaque identifier or free-text string ({distinct_count}+ distinct values, max length {max_length}); filter suggestions disabled.{preview_suffix}"
        )

    escaped_desc = rec_desc.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    snippet = (
        f"  dimension: {short_name} {{\n"
        f"    hidden: {'yes' if rec_hidden else 'no'}\n"
        f"    suggestable: {'yes' if rec_suggestable else 'no'}\n"
        f'    description: "{escaped_desc}"\n'
        "  }"
    )
    return {
        "field_name": full_name,
        "short_name": short_name,
        "label": label,
        "label_short": label_short,
        "classification": classification,
        "distinct_count": distinct_count,
        "total_rows_sampled": total_rows,
        "null_or_empty_count": null_or_empty_count,
        "has_null_or_empty": null_or_empty_count > 0,
        "max_length": max_length,
        "avg_length": round(avg_length, 1),
        "sample_values": non_empty[: max(enum_threshold, top_n)],
        "current_hidden": bool(field_meta.get("hidden", False)),
        "current_suggestable": bool(field_meta.get("suggestable", True)),
        "current_description": existing_desc,
        "recommended_hidden": rec_hidden,
        "recommended_suggestable": rec_suggestable,
        "recommended_description": rec_desc,
        "lookml_snippet": snippet,
    }


def main():
    try:
        m_name = str(model_name)  # ty: ignore[unresolved-reference]
    except NameError:
        m_name = ""
    try:
        c_name = str(connection_name)  # ty: ignore[unresolved-reference]
    except NameError:
        c_name = ""
    if not m_name and not c_name:
        return None
    try:
        e_name = str(explore_name)  # ty: ignore[unresolved-reference]
    except NameError:
        e_name = ""
    try:
        v_name = str(view_name)  # ty: ignore[unresolved-reference]
    except NameError:
        v_name = e_name
    try:
        t_name = str(table_name)  # ty: ignore[unresolved-reference]
    except NameError:
        t_name = ""
    try:
        q_mode = str(query_mode).lower()  # ty: ignore[unresolved-reference]
    except NameError:
        q_mode = "sql" if t_name else "explore"
    try:
        raw_fields = fields_json  # ty: ignore[unresolved-reference]
        field_list = json.loads(raw_fields) if isinstance(raw_fields, str) else (raw_fields or [])
    except (NameError, ValueError):
        field_list = []
    if not field_list:
        try:
            raw_names = str(field_names)  # ty: ignore[unresolved-reference]
            field_list = [
                {
                    "field_name": fn.strip() if "." in fn.strip() else f"{v_name}.{fn.strip()}",
                    "short_name": fn.strip().split(".")[-1],
                    "sql_column": fn.strip().split(".")[-1],
                    "primary_key": False,
                }
                for fn in raw_names.split(",")
                if fn.strip()
            ]
        except NameError:
            field_list = []

    if not field_list and m_name and e_name:
        exp_meta = lookml_model_explore(m_name, e_name) or {}  # ty: ignore[unresolved-reference]
        for d in (exp_meta.get("fields") or {}).get("dimensions") or []:
            if d.get("type") == "string" and (
                not v_name or d.get("view") == v_name or d.get("original_view") == v_name
            ):
                fname = str(d.get("name") or "")
                sname = fname.split(".")[-1]
                field_list.append({
                    "field_name": fname,
                    "short_name": sname,
                    "label": str(d.get("label") or ""),
                    "label_short": str(d.get("label_short") or ""),
                    "sql_column": sname,
                    "primary_key": bool(d.get("primary_key")),
                    "hidden": bool(d.get("hidden")),
                    "suggestable": bool(d.get("suggestable", True)),
                    "description": str(d.get("description") or ""),
                    "sql": str(d.get("sql") or ""),
                })

    try:
        enum_max = int(enum_threshold)  # ty: ignore[unresolved-reference]
    except (NameError, ValueError):
        enum_max = 15
    try:
        cat_max = int(categorical_threshold)  # ty: ignore[unresolved-reference]
    except (NameError, ValueError):
        cat_max = 100
    try:
        top_k = int(top_n)  # ty: ignore[unresolved-reference]
    except (NameError, ValueError):
        top_k = 10
    try:
        q_limit = int(query_limit)  # ty: ignore[unresolved-reference]
    except (NameError, ValueError):
        q_limit = 500
    try:
        raw_filters = filters_json  # ty: ignore[unresolved-reference]
        explore_filters = (
            json.loads(raw_filters) if isinstance(raw_filters, str) else (raw_filters or {})
        )
    except (NameError, ValueError):
        explore_filters = {}

    recommendations = []
    for fmeta in field_list:
        fname = str(fmeta.get("field_name") or fmeta.get("name") or "")
        sname = str(fmeta.get("short_name") or fname.split(".")[-1])
        col_name = str(fmeta.get("sql_column") or sname)

        if q_mode == "sql" and t_name:
            sql_stmt = (
                f"SELECT CAST({col_name} AS VARCHAR) AS val, COUNT(1) AS cnt, "
                f"COUNT(1) OVER () AS total_groups, MAX(LENGTH(CAST({col_name} AS VARCHAR))) OVER () AS max_len "
                f"FROM {t_name} GROUP BY 1 ORDER BY cnt DESC, val ASC LIMIT {q_limit}"
            )
            sql_body = {"sql": sql_stmt}
            if m_name:
                sql_body["model_name"] = m_name
            elif c_name:
                sql_body["connection_name"] = c_name
            slug = (create_sql_query(body=sql_body) or {}).get("slug") or ""  # ty: ignore[unresolved-reference]
            rows = _parse_rows(run_sql_query(slug=slug, result_format="json")) if slug else []  # ty: ignore[unresolved-reference]
            val_key, cnt_key = "val", "cnt"
        else:
            body = {
                "model": m_name,
                "view": e_name or v_name,
                "fields": [fname],
                "sorts": [f"{fname} asc"],
                "limit": str(q_limit),
            }
            if explore_filters:
                body["filters"] = explore_filters
            rows = _parse_rows(run_inline_query(result_format="json", body=body))  # ty: ignore[unresolved-reference]
            val_key, cnt_key = fname, ""

        dict_rows = [r for r in rows if isinstance(r, dict)]
        first = dict_rows[0] if dict_rows else {}
        reported_total_groups = int(first.get("total_groups") or 0)
        reported_max_len = int(first.get("max_len") or 0)

        sample_vals, lengths = [], []
        null_empty_cnt = null_empty_groups = total_cnt = 0
        for r in dict_rows:
            v = r.get(val_key)
            row_cnt = int(r[cnt_key]) if cnt_key and r.get(cnt_key) is not None else 1
            total_cnt += row_cnt
            if v is None or str(v).strip() == "":
                null_empty_cnt += row_cnt
                null_empty_groups += 1
            else:
                sv = str(v).strip()
                sample_vals.append(sv)
                lengths.append(len(sv))

        recommendations.append(
            classify_string_field(
                field_meta=fmeta,
                sample_values=sample_vals,
                distinct_count=max(len(sample_vals), reported_total_groups - null_empty_groups),
                null_or_empty_count=null_empty_cnt,
                total_rows=total_cnt,
                max_length=max(max(lengths, default=0), reported_max_len),
                avg_length=(sum(lengths) / len(lengths)) if lengths else 0.0,
                enum_threshold=enum_max,
                categorical_threshold=cat_max,
                top_n=top_k,
            )
        )

    target_view = v_name or (
        str(field_list[0].get("field_name", "")).split(".")[0] if field_list else "view_name"
    )
    snippets = "\n\n".join(r["lookml_snippet"] for r in recommendations)
    return {
        "model_name": m_name,
        "explore_name": e_name,
        "view_name": target_view,
        "query_mode": q_mode,
        "field_count": len(recommendations),
        "recommendations": recommendations,
        "refinement_lookml": f'include: "{target_view}.view.lkml"\n\nview: +{target_view} {{\n{snippets}\n}}\n',
    }


main()
