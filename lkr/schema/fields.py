import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VisibleExploreFields:
    dimensions: list[dict[str, Any]]
    measures: list[dict[str, Any]]
    filters: list[dict[str, Any]]
    parameters: list[dict[str, Any]]

    @property
    def dimension_names(self) -> list[str]:
        return [f["name"] for f in self.dimensions]

    @property
    def measure_names(self) -> list[str]:
        return [f["name"] for f in self.measures]

    @property
    def selectable_field_names(self) -> list[str]:
        return self.dimension_names + self.measure_names


def is_visible_field(field: dict[str, Any]) -> bool:
    """Return True if a LookML explore field has a name and is not hidden."""
    return bool(field.get("name")) and not bool(field.get("hidden"))


def extract_visible_explore_fields(
    explore_data: dict[str, Any],
) -> VisibleExploreFields:
    """Extract non-hidden dimensions, measures, filters, and parameters from explore JSON."""
    fields_obj = explore_data.get("fields") or {}
    return VisibleExploreFields(
        dimensions=[
            f
            for f in (fields_obj.get("dimensions") or [])
            if is_visible_field(f)
        ],
        measures=[
            f for f in (fields_obj.get("measures") or []) if is_visible_field(f)
        ],
        filters=[
            f for f in (fields_obj.get("filters") or []) if is_visible_field(f)
        ],
        parameters=[
            f
            for f in (fields_obj.get("parameters") or [])
            if is_visible_field(f)
        ],
    )


def _string_enum_array(names: list[str], description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": names},
        "description": description,
    }


def build_fields_schema(
    dimension_names: list[str], measure_names: list[str]
) -> dict[str, Any]:
    """Build JSON Schema for `body.fields` (dimensions, measures, or dynamic_fields .name)."""
    return _string_enum_array(
        dimension_names + measure_names,
        "Dimensions, measures, or dynamic_fields .name values to include in the query.",
    )


def build_pivots_schema(dimension_names: list[str]) -> dict[str, Any]:
    """Build JSON Schema for `body.pivots` (dimensions or dimension_like dynamic_fields .name; no measures or table calcs)."""
    return _string_enum_array(
        dimension_names,
        "Dimensions or dimension_like dynamic_fields .name values to pivot on "
        "(measures and table calculations are not allowed).",
    )


def build_fill_fields_schema(dimension_names: list[str]) -> dict[str, Any]:
    """Build JSON Schema for `body.fill_fields` (constrained to dimensions or dimension_like dynamic_fields .name)."""
    return _string_enum_array(
        dimension_names,
        "Dimensions or dimension_like dynamic_fields .name values for dimension fill.",
    )


def build_subtotals_schema(dimension_names: list[str]) -> dict[str, Any]:
    """Build JSON Schema for `body.subtotals` (grouping dimensions on which to run subtotals)."""
    return _string_enum_array(
        dimension_names,
        "Fields on which to run subtotals.",
    )


def build_sorts_schema(selectable_field_names: list[str]) -> dict[str, Any]:
    """Build JSON Schema for `body.sorts` constrained by a regex derived from selectable fields.
    Supports `<field>`, `<field> asc|desc`, `<field> <pivot_idx>`, `<field> asc|desc <pivot_idx>`, or `__UNSORTED__`.
    """
    if selectable_field_names:
        escaped = "|".join(re.escape(name) for name in selectable_field_names)
        pattern = rf"^(?:__UNSORTED__|(?:{escaped})(?:__sort_)?(?:\s+(?:asc|desc))?(?:\s+\d+)?)$"
    else:
        pattern = r"^__UNSORTED__$"

    return {
        "type": "array",
        "items": {
            "type": "string",
            "pattern": pattern,
        },
        "description": (
            "Sorting for the query results (`['view.field']`, `['view.field desc']`, "
            "`['view.field 0']`, `['view.field desc 0']`, or `['__UNSORTED__']`)."
        ),
    }
