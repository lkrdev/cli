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
