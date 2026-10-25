# ruff: noqa: F821, BLE001
"""Query INFORMATION_SCHEMA in lkr code-mode sandbox to detect partition columns (with min date) and clustering columns."""

import json
import re


def _parse_rows(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return raw if isinstance(raw, list) else []


def _get_ci(row: dict, key: str):
    target = key.lower()
    for k, v in row.items():
        if str(k).lower().split(".")[-1] == target:
            return v
    return None


def format_partition_id_to_date(partition_id) -> str | None:
    s = str(partition_id or "").strip()
    if not s or s in ("__NULL__", "__UNPARTITIONED__", "NULL", "None"):
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    if re.match(r"^\d{8,10}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.match(r"^\d{6}$", s):
        return f"{s[:4]}-{s[4:6]}-01"
    if re.match(r"^\d{4}$", s):
        return f"{s[:4]}-01-01"
    return s


def _humanize_label(name: str) -> str:
    words = [w for w in name.split(".")[-1].split("_") if w]
    return " ".join("ID" if w.lower() == "id" else w.capitalize() for w in words)


def _dedupe_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        s = str(t).strip()
        if s and s not in out:
            out.append(s)
    return out


def _fmt_snippet(construct: str, lname: str, tags: list[str], desc: str) -> str:
    escaped = desc.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    tags_str = ", ".join(json.dumps(t) for t in tags)
    return f'  {construct}: {lname} {{\n    tags: [{tags_str}]\n    description: "{escaped}"\n  }}'


def resolve_lookml_field_for_column(
    col_name: str, fields_meta: list[dict], is_time_partition: bool = False
) -> dict:
    low_col = col_name.lower()
    for f in fields_meta:
        sql_col = str(f.get("sql_column") or "").lower()
        short = str(f.get("short_name") or f.get("name", "").split(".")[-1]).lower()
        if sql_col == low_col or short == low_col:
            dg = f.get("dimension_group")
            is_dg = bool(dg) or f.get("category") == "dimension_group"
            name = str(dg).split(".")[-1] if dg else str(f.get("short_name") or short)
            filter_field = f"{name}_date" if is_dg else name
            raw_lbl = str(f.get("label_short") or "").strip()
            return {
                "lookml_construct": "dimension_group" if is_dg else "dimension",
                "lookml_name": name,
                "filter_field": filter_field,
                "filter_label": raw_lbl or _humanize_label(filter_field),
                "existing_description": str(f.get("description") or "").strip(),
                "existing_tags": _dedupe_tags(list(f.get("tags") or [])),
            }

    name = (
        (re.sub(r"_(timestamp|datetime|date|time|at|ts)$", "", low_col) or low_col)
        if is_time_partition
        else low_col
    )
    filter_field = f"{name}_date" if is_time_partition else name
    return {
        "lookml_construct": "dimension_group" if is_time_partition else "dimension",
        "lookml_name": name,
        "filter_field": filter_field,
        "filter_label": _humanize_label(filter_field),
        "existing_description": "",
        "existing_tags": [],
    }


def _run_sql(m_name: str, conn_name: str, sql_text: str) -> list[dict]:
    body = {"sql": sql_text}
    if m_name:
        body["model_name"] = m_name
    elif conn_name:
        body["connection_name"] = conn_name
    try:
        slug = (create_sql_query(body=body) or {}).get("slug") or ""  # ty: ignore[unresolved-reference]
        return _parse_rows(run_sql_query(slug=slug, result_format="json")) if slug else []  # ty: ignore[unresolved-reference]
    except Exception:
        return []


def main():
    try:
        t_name = str(table_name).strip('`" ')  # ty: ignore[unresolved-reference]
    except NameError:
        return None
    try:
        m_name = str(model_name)  # ty: ignore[unresolved-reference]
    except NameError:
        m_name = ""
    try:
        conn_name = str(connection_name)  # ty: ignore[unresolved-reference]
    except NameError:
        conn_name = ""
    try:
        p_id = str(project_id).strip('`" ')  # ty: ignore[unresolved-reference]
    except NameError:
        p_id = ""
    try:
        d_name = str(dataset_name).strip('`" ')  # ty: ignore[unresolved-reference]
    except NameError:
        d_name = ""
    try:
        v_name = str(view_name).strip()  # ty: ignore[unresolved-reference]
    except NameError:
        v_name = ""
    try:
        def_window = str(default_filter_window).strip()  # ty: ignore[unresolved-reference]
    except NameError:
        def_window = "7 days"
    try:
        raw_fields = fields_json  # ty: ignore[unresolved-reference]
        fields_meta = (
            json.loads(raw_fields) if isinstance(raw_fields, str) else (raw_fields or [])
        )
    except (NameError, ValueError):
        fields_meta = []

    parts = [p.strip('`" ') for p in t_name.split(".") if p.strip('`" ')]
    cat, sch, tbl = [None, None, None, *parts][-3:]
    p_id = p_id or cat or ""
    d_name = d_name or sch or ""
    bare_table = tbl or t_name

    target_view = v_name or bare_table
    schema_prefix = f"`{p_id}.{d_name}`." if (p_id and d_name) else (f"`{d_name}`." if d_name else "")

    cols_sql = (
        "SELECT column_name, data_type, is_partitioning_column, clustering_ordinal_position "
        f"FROM {schema_prefix}INFORMATION_SCHEMA.COLUMNS "
        f"WHERE table_name = '{bare_table}' "
        "AND (is_partitioning_column = 'YES' OR clustering_ordinal_position IS NOT NULL) "
        "ORDER BY clustering_ordinal_position ASC, column_name ASC"
    )

    partition_col = None
    partition_data_type = None
    clustering_cols = []
    for r in _run_sql(m_name, conn_name, cols_sql):
        if not isinstance(r, dict):
            continue
        cname = str(_get_ci(r, "column_name") or "")
        dtype = str(_get_ci(r, "data_type") or "TIMESTAMP")
        if str(_get_ci(r, "is_partitioning_column") or "").upper() == "YES" and cname:
            partition_col, partition_data_type = cname, dtype
        clust_pos = _get_ci(r, "clustering_ordinal_position")
        if clust_pos is not None and str(clust_pos).strip() not in ("", "None", "null") and cname:
            clustering_cols.append({
                "column_name": cname,
                "data_type": dtype,
                "ordinal_position": int(clust_pos),
            })

    clustering_cols.sort(key=lambda x: x["ordinal_position"])

    min_partition_date = max_partition_date = None
    partition_count = 0
    if partition_col:
        parts_sql = (
            "SELECT MIN(partition_id) AS min_partition_id, "
            "MAX(partition_id) AS max_partition_id, "
            "COUNT(DISTINCT partition_id) AS partition_count "
            f"FROM {schema_prefix}INFORMATION_SCHEMA.PARTITIONS "
            f"WHERE table_name = '{bare_table}' "
            "AND partition_id NOT IN ('__NULL__', '__UNPARTITIONED__')"
        )
        part_rows = _run_sql(m_name, conn_name, parts_sql)
        if part_rows and isinstance(part_rows[0], dict):
            pr = part_rows[0]
            min_partition_date = format_partition_id_to_date(_get_ci(pr, "min_partition_id"))
            max_partition_date = format_partition_id_to_date(_get_ci(pr, "max_partition_id"))
            partition_count = int(_get_ci(pr, "partition_count") or 0)

    refinement_snippets = []
    partition_recommendation = None
    filter_timeframe_ref = "partition_date"
    filter_timeframe_label = "Partition Date"

    if partition_col:
        is_time = any(
            tok in (partition_data_type or "").upper() for tok in ("DATE", "TIME", "TIMESTAMP")
        )
        mapped = resolve_lookml_field_for_column(
            partition_col, fields_meta, is_time_partition=is_time
        )
        construct, lname = mapped["lookml_construct"], mapped["lookml_name"]
        filter_timeframe_ref = mapped["filter_field"]
        filter_timeframe_label = mapped["filter_label"]
        existing_desc = mapped["existing_description"]
        prefix = (existing_desc.rstrip(".") + ". ") if existing_desc else ""
        min_date_str = f" Min date available: {min_partition_date}." if min_partition_date else ""
        rec_desc = f"{prefix}Physical partition column (required).{min_date_str} Do not use 'is any value'."
        rec_tags = _dedupe_tags([*mapped["existing_tags"], "partition_key"])
        snippet = _fmt_snippet(construct, lname, rec_tags, rec_desc)
        refinement_snippets.append(snippet)
        partition_recommendation = {
            "column_name": partition_col,
            "data_type": partition_data_type,
            "min_partition_date": min_partition_date,
            "max_partition_date": max_partition_date,
            "partition_count": partition_count,
            "lookml_construct": construct,
            "lookml_field_name": lname,
            "filter_timeframe_field": f"{target_view}.{filter_timeframe_ref}",
            "filter_timeframe_label": filter_timeframe_label,
            "recommended_description": rec_desc,
            "recommended_tags": rec_tags,
            "lookml_snippet": snippet,
        }

    clustering_recommendations = []
    for cinfo in clustering_cols:
        cname, pos = str(cinfo["column_name"]), cinfo["ordinal_position"]
        mapped = resolve_lookml_field_for_column(cname, fields_meta, is_time_partition=False)
        construct, lname = mapped["lookml_construct"], mapped["lookml_name"]
        existing_desc = mapped["existing_description"]
        prefix = (existing_desc.rstrip(".") + ". ") if existing_desc else ""
        target = f"alongside {filter_timeframe_label}" if partition_col else "on this field"
        rec_desc = (
            f"{prefix}Clustering column (order {pos}). Filtering {target} enables block pruning."
        )
        rec_tags = _dedupe_tags([*mapped["existing_tags"], "cluster_key"])
        snippet = _fmt_snippet(construct, lname, rec_tags, rec_desc)
        refinement_snippets.append(snippet)
        clustering_recommendations.append({
            "column_name": cname,
            "data_type": cinfo["data_type"],
            "ordinal_position": pos,
            "lookml_construct": construct,
            "lookml_field_name": lname,
            "lookml_label": mapped["filter_label"],
            "recommended_description": rec_desc,
            "recommended_tags": rec_tags,
            "lookml_snippet": snippet,
        })

    header_parts = [
        p
        for p in (
            f"PARTITION_COLUMN: {partition_col} ({partition_data_type})" if partition_col else "",
            f"MIN_DATE: {min_partition_date}" if min_partition_date else "",
            f"CLUSTERED_BY: {', '.join(str(c['column_name']) for c in clustering_cols)}"
            if clustering_cols
            else "",
        )
        if p
    ]
    header_comment = f"# {' | '.join(header_parts)}" if header_parts else ""
    header_line = f"{header_comment}\n" if header_comment else ""
    refinement_lookml = (
        f'{header_line}include: "{target_view}.view.lkml"\n\n'
        f"view: +{target_view} {{\n" + "\n\n".join(refinement_snippets) + "\n}\n"
    )

    base_explore_lookml = (
        f"explore: {target_view}_base {{\n"
        "  extension: required\n"
        f"  view_name: {target_view}\n\n"
        "  always_filter: {\n"
        f'    filters: [{partition_recommendation["filter_timeframe_field"]}: "{def_window}"]\n'
        "  }\n"
        "}\n"
        if partition_recommendation
        else ""
    )

    return {
        "table_name": bare_table,
        "project_id": p_id or None,
        "dataset_name": d_name or None,
        "view_name": target_view,
        "is_partitioned": partition_recommendation is not None,
        "is_clustered": bool(clustering_recommendations),
        "header_comment": header_comment,
        "partition_column": partition_recommendation,
        "clustering_columns": clustering_recommendations,
        "refinement_lookml": refinement_lookml,
        "base_explore_lookml": base_explore_lookml,
    }


main()
