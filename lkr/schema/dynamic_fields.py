from typing import Any

COMMON_DYNAMIC_FIELD_PROPERTIES: dict[str, Any] = {
    "category": {
        "type": "string",
        "enum": ["dimension", "measure", "table_calculation"],
    },
    "label": {"type": ["string", "null"]},
    "description": {"type": ["string", "null"]},
    "value_format": {"type": ["string", "null"]},
    "value_format_name": {"type": ["string", "null"]},
    "_kind_hint": {"type": ["string", "null"]},
    "_type_hint": {"type": ["string", "null"]},
    "is_disabled": {"type": ["boolean", "null"]},
    "__PARAMETER_LINE_NUMS": {"type": ["object", "null"]},
}


def build_custom_dimension_schema() -> dict[str, Any]:
    """Build JSON Schema for a Looker CustomDimension dynamic field (`dimension_like`).
    Supports both formula custom dimensions (`expression`) and custom groupings/bins (`calculation_type` + `args`).
    """
    return {
        "title": "CustomDimension",
        "type": "object",
        "properties": {
            **COMMON_DYNAMIC_FIELD_PROPERTIES,
            "dimension": {
                "type": "string",
                "description": "Unique .name for this custom dimension (dimension_like; valid in fields and pivots).",
            },
            "expression": {"type": ["string", "null"]},
            "calculation_type": {"type": ["string", "null"]},
            "args": {"type": ["array", "null"]},
        },
        "required": ["dimension"],
        "additionalProperties": False,
    }


def build_custom_measure_schema(
    selectable_field_names: list[str],
) -> dict[str, Any]:
    """Build JSON Schema for a Looker CustomMeasure dynamic field (valid in fields, not pivots)."""
    return {
        "title": "CustomMeasure",
        "type": "object",
        "properties": {
            **COMMON_DYNAMIC_FIELD_PROPERTIES,
            "measure": {
                "type": "string",
                "description": "Unique .name for this custom measure (valid in fields, not pivots).",
            },
            "based_on": {
                "type": "string",
                "enum": selectable_field_names,
            },
            "type": {"type": ["string", "null"]},
            "expression": {"type": ["string", "null"]},
            "filter_expression": {"type": ["string", "null"]},
            "filters": {
                "type": ["object", "null"],
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["measure", "based_on"],
        "additionalProperties": False,
    }


def build_table_calculation_schema() -> dict[str, Any]:
    """Build JSON Schema for a Looker TableCalculation dynamic field (valid in fields, not pivots).
    Supports both formula table calculations (`expression`) and shortcut calculations (`calculation_type` + `args`).
    """
    return {
        "title": "TableCalculation",
        "type": "object",
        "properties": {
            **COMMON_DYNAMIC_FIELD_PROPERTIES,
            "table_calculation": {
                "type": "string",
                "description": "Unique .name for this table calculation (valid in fields, not pivots).",
            },
            "expression": {"type": ["string", "null"]},
            "calculation_type": {"type": ["string", "null"]},
            "args": {"type": ["array", "null"]},
            "based_on": {"type": ["string", "null"]},
            "source_field": {"type": ["string", "null"]},
        },
        "required": ["table_calculation"],
        "additionalProperties": False,
    }


def build_dynamic_fields_schema(
    selectable_field_names: list[str],
) -> dict[str, Any]:
    """Build JSON Schema for `body.dynamic_fields`."""
    return {
        "type": "array",
        "description": (
            "Dynamic fields (custom dimensions, custom measures, table calculations). "
            "Custom dimensions (.dimension) are dimension_like and may be used in fields and pivots; "
            "custom measures (.measure) and table calculations (.table_calculation) may only be used in fields."
        ),
        "items": {
            "oneOf": [
                build_custom_dimension_schema(),
                build_custom_measure_schema(selectable_field_names),
                build_table_calculation_schema(),
            ]
        },
    }
