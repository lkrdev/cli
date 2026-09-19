from typing import Any

NUMERIC_FIELD_TYPES = frozenset(
    {
        "number",
        "int",
        "count",
        "count_distinct",
        "sum",
        "sum_distinct",
        "average",
        "average_distinct",
        "min",
        "max",
        "median",
        "percentile",
    }
)

FILTER_EXPRESSION_DEFS: dict[str, Any] = {
    "StringFilterExpression": {
        "type": "string",
        "description": (
            "Looker string filter expression (https://docs.cloud.google.com/looker/docs/filter-expressions#string). "
            "Supports exact ('FOO'), OR list ('FOO,BAR'), wildcards ('%FOO%', 'FOO%', '%FOO', '_UF'), "
            "negation ('-FOO', '-%FOO%'), and null/empty checks ('EMPTY', 'NULL', '-EMPTY', '-NULL')."
        ),
        "examples": [
            "FOO",
            "FOO,BAR",
            "%FOO%",
            "FOO%",
            "%FOO",
            "-FOO",
            "EMPTY",
            "NULL",
            "-EMPTY",
            "-NULL",
        ],
    },
    "DateTimeFilterExpression": {
        "type": "string",
        "description": (
            "Looker date and time filter expression (https://docs.cloud.google.com/looker/docs/filter-expressions#date_and_time). "
            "Supports relative dates ('today', 'yesterday', 'tomorrow', '7 days', '3 days ago', "
            "'7 days ago for 7 days', 'this week', 'this month', 'this quarter', 'this year', "
            "'last week', 'next month'), ranges ('before 2024-01-01', 'after 2024-01-01', "
            "'2024-01-01 to 2024-01-31'), and absolute dates ('2024/05/29', '2024/05', '2024', 'FY2024', 'FY2024-Q1', 'NULL', '-NULL')."
        ),
        "pattern": (
            r"^(?:|today(?:\s+for\s+\d+\s+(?:second|minute|hour|day|week|month|quarter|year)s?)?|yesterday|tomorrow|NULL|-NULL|NOT NULL"
            r"|(?:this|last|next)\s+(?:(?:\d+\s+)?(?:second|minute|hour|day|week|month|quarter|fiscal\s+quarter|year|fiscal\s+year)s?)(?:\s+to\s+(?:second|minute|hour|day|week|month|quarter|year))?"
            r"|(?:before|after)\s+.+"
            r"|\d+\s+(?:second|minute|hour|day|week|month|quarter|fiscal\s+quarter|year|fiscal\s+year)s?(?:\s+(?:ago|from\s+now))?(?:\s+for\s+\d+\s+(?:second|minute|hour|day|week|month|quarter|fiscal\s+quarter|year|fiscal\s+year)s?)?"
            r"|(?:FY)?\d{4}(?:[-/]\d{2}(?:[-/]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)?|-Q[1-4])?(?:\s+(?:to\s+.+|for\s+\d+\s+(?:second|minute|hour|day|week|month|quarter|year)s?))?"
            r"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
            r")(?:,\s*.+)*$"
        ),
        "examples": [
            "today",
            "yesterday",
            "7 days",
            "7 days ago for 7 days",
            "this month",
            "last quarter",
            "before 2024-01-01",
            "after 2024-01-01",
            "2024-01-01 to 2024-01-31",
            "2024/05",
            "NULL",
            "-NULL",
        ],
    },
    "BooleanFilterExpression": {
        "type": "string",
        "description": (
            "Looker boolean / yesno filter expression (https://docs.cloud.google.com/looker/docs/filter-expressions#boolean)."
        ),
        "enum": [
            "",
            "yes",
            "no",
            "Yes",
            "No",
            "TRUE",
            "FALSE",
            "true",
            "false",
            "NULL",
            "-NULL",
            "NOT NULL",
        ],
    },
    "NumberFilterExpression": {
        "type": "string",
        "description": (
            "Looker number filter expression (https://docs.cloud.google.com/looker/docs/filter-expressions#number). "
            "Supports exact numbers ('5', '1, 3, 5'), relational operators ('>10', '>=5.5 AND <=10', '!=5', '<>5', 'NOT 5'), "
            "natural ranges ('5.5 to 10', '1 to', 'to 10'), algebraic intervals ('[5, 90]', '(1, 7)', '(500, inf)', '(-inf, 10]'), "
            "and null checks ('NULL', 'NOT NULL')."
        ),
        "pattern": (
            r"^(?:|NULL|-NULL|NOT NULL"
            r"|(?:NOT\s+)?(?:(?:<>|!=|>=|<=|>|<|=)\s*-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?(?:\s+to(?:\s+-?\d+(?:\.\d+)?)?)?|to\s+-?\d+(?:\.\d+)?|[\[\(](?:-?inf|-?\d+(?:\.\d+)?)?\s*,\s*(?:-?inf|-?\d+(?:\.\d+)?)?[\]\)])"
            r"(?:\s+(?:AND|OR)\s+(?:NOT\s+)?(?:(?:<>|!=|>=|<=|>|<|=)\s*-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?(?:\s+to(?:\s+-?\d+(?:\.\d+)?)?)?|to\s+-?\d+(?:\.\d+)?|[\[\(](?:-?inf|-?\d+(?:\.\d+)?)?\s*,\s*(?:-?inf|-?\d+(?:\.\d+)?)?[\]\)]))*)"
            r"(?:,\s*(?:NOT\s+)?[^,]+)*$"
        ),
        "examples": [
            "5",
            "NOT 5",
            "!=5",
            ">1 AND <100",
            ">=5.5 AND <=10",
            "5.5 to 10",
            "[5, 90]",
            "(1, 7)",
            "NULL",
            "NOT NULL",
        ],
    },
    "LocationFilterExpression": {
        "type": "string",
        "description": (
            "Looker location filter expression (https://docs.cloud.google.com/looker/docs/filter-expressions#location). "
            "Supports exact coordinates ('36.97, -122.03'), circle radius ('40 miles from 36.97, -122.03' with meters/feet/kilometers/miles), "
            "bounding box ('inside box from 72.33, -173.14 to 14.39, -61.70'), and null checks ('NULL', '-NULL', 'NOT NULL')."
        ),
        "pattern": (
            r"^(?:|NULL|-NULL|NOT NULL"
            r"|-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?"
            r"|(?:within\s+)?\d+(?:\.\d+)?\s+(?:meters|feet|kilometers|miles)\s+(?:from|of)\s+-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?"
            r"|inside\s+box\s+from\s+-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s+to\s+-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?)$"
        ),
        "examples": [
            "36.97, -122.03",
            "40 miles from 36.97, -122.03",
            "inside box from 72.33, -173.14 to 14.39, -61.70",
            "NULL",
            "-NULL",
            "NOT NULL",
        ],
    },
}


def extract_enum_values(field: dict[str, Any]) -> list[Any] | None:
    """Extract allowed values from `allowed_values` or `enumerations` on a LookML field."""
    raw_allowed = field.get("allowed_values")
    if isinstance(raw_allowed, list) and raw_allowed:
        return [
            item["value"] if isinstance(item, dict) and "value" in item else item
            for item in raw_allowed
        ]
    enums = field.get("enumerations")
    if isinstance(enums, list) and enums:
        return [
            item["value"]
            for item in enums
            if isinstance(item, dict) and "value" in item
        ]
    return None


def classify_filter_expression_ref(field: dict[str, Any]) -> str:
    """Map a LookML field definition to its corresponding `$defs` FilterExpression reference."""
    ftype = (field.get("type") or "").lower()
    if ftype == "yesno":
        return "#/$defs/BooleanFilterExpression"
    if ftype == "location":
        return "#/$defs/LocationFilterExpression"
    if (
        field.get("is_timeframe")
        or field.get("can_time_filter")
        or ftype.startswith(("date", "time", "duration"))
    ):
        return "#/$defs/DateTimeFilterExpression"
    if field.get("is_numeric") or ftype in NUMERIC_FIELD_TYPES:
        return "#/$defs/NumberFilterExpression"
    return "#/$defs/StringFilterExpression"


def build_filter_property_schema(
    field: dict[str, Any], *, is_parameter: bool = False
) -> dict[str, Any]:
    """Return a strongly typed JSON Schema for a single filter property."""
    meta: dict[str, Any] = {}
    if field.get("description"):
        meta["description"] = field["description"]
    if field.get("default_filter_value") is not None:
        meta["default"] = field["default_filter_value"]

    allowed = extract_enum_values(field)
    is_param = is_parameter or bool(field.get("parameter"))
    if is_param and (field.get("has_allowed_values") or allowed):
        return {
            "type": "string",
            "enum": allowed,
            **meta,
        }

    ref = classify_filter_expression_ref(field)
    if allowed and ref != "#/$defs/BooleanFilterExpression":
        return {
            "anyOf": [
                {"type": "string", "enum": allowed},
                {"$ref": ref},
            ],
            **meta,
        }

    return {
        "$ref": ref,
        **meta,
    }


def build_filters_schema(
    dimensions: list[dict[str, Any]],
    measures: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the `body.filters` object schema across all visible filterable fields."""
    filter_properties: dict[str, Any] = {}
    for f in dimensions + measures + filters:
        filter_properties[f["name"]] = build_filter_property_schema(
            f, is_parameter=False
        )
    for p in parameters:
        filter_properties[p["name"]] = build_filter_property_schema(
            p, is_parameter=True
        )

    return {
        "type": "object",
        "properties": filter_properties,
        "additionalProperties": False,
        "description": (
            "Filter expressions keyed by dimension, measure, filter, or parameter .name. "
            "Values follow Looker filter expression rules (https://docs.cloud.google.com/looker/docs/filter-expressions)."
        ),
    }
