import re
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from lkr.parse.lookml import (
    DEFAULT_DURATION_INTERVALS,
    DEFAULT_TIMEFRAMES,
    LookmlAllowedValue,
    LookmlCaseWhen,
    LookmlDimension,
    LookmlDimensionGroup,
    LookmlExplore,
    LookmlFilter,
    LookmlJoin,
    LookmlMapLayer,
    LookmlMeasure,
    LookmlModel,
    LookmlNamedValueFormat,
    LookmlParameter,
    LookmlProject,
    LookmlView,
    _default_table_sql,
    parse_lookml,
)
from lkr.parse.sql_to_lookml import (
    _build_chain,
    _chain_root_pos,
    _collect_declarations,
    _expand_field_tokens,
    _extract_lookml_refs,
    _is_field_allowed_by_spec,
    _resolve_explore_base,
)

__all__ = [
    "ApiLookmlModel",
    "ApiLookmlModelExplore",
    "ApiLookmlModelExploreAlias",
    "ApiLookmlModelExploreField",
    "ApiLookmlModelExploreFieldEnumeration",
    "ApiLookmlModelExploreFieldMapLayer",
    "ApiLookmlModelExploreFieldMeasureFilters",
    "ApiLookmlModelExploreFieldSqlCase",
    "ApiLookmlModelExploreFieldTimeInterval",
    "ApiLookmlModelExploreFieldset",
    "ApiLookmlModelExploreJoins",
    "ApiLookmlModelExploreSet",
    "ApiLookmlModelExploreTurtleLook",
    "ApiLookmlModelNavExplore",
    "LookmlToApiResult",
    "lookml_to_all_lookml_models",
    "lookml_to_lookml_model_explore",
    "parse_lookml_to_api",
]

VALUE_FORMAT_MAP: dict[str, str] = {
    "usd": "$#,##0.00",
    "usd_0": "$#,##0",
    "eur": "€#,##0.00",
    "eur_0": "€#,##0",
    "gbp": "£#,##0.00",
    "gbp_0": "£#,##0",
    "decimal_0": "#,##0",
    "decimal_1": "#,##0.0",
    "decimal_2": "#,##0.00",
    "decimal_3": "#,##0.000",
    "decimal_4": "#,##0.0000",
    "percent_0": "#,##0%",
    "percent_1": "#,##0.0%",
    "percent_2": "#,##0.00%",
    "percent_3": "#,##0.000%",
    "percent_4": "#,##0.0000%",
    "id": "0",
}

DISTANCE_UNIT_FORMATS: dict[str, str] = {
    "feet": '#,##0.00" ft"',
    "kilometers": '#,##0.00" km"',
    "meters": '#,##0.00" m"',
    "miles": '#,##0.00" mi"',
    "nautical_miles": '#,##0.00" nmi"',
    "yards": '#,##0.00" yd"',
}

BUILTIN_MAP_LAYERS: dict[str, dict[str, Any]] = {
    "countries": {
        "extents_json_url": None,
        "feature_key": "world",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "countries",
        "projection": "kavrayskiy7",
        "property_key": None,
        "property_label_key": "name",
        "url": "/data/world_noantarctica.topo-545fce41cc.json",
    },
    "us_states": {
        "extents_json_url": None,
        "feature_key": "usa",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "us_states",
        "projection": "albersUsa",
        "property_key": None,
        "property_label_key": None,
        "url": "/data/us_states.topo-402e425f99.json",
    },
    "uk_postcode_areas": {
        "extents_json_url": None,
        "feature_key": "Areas",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "uk_postcode_areas",
        "projection": "mercator",
        "property_key": None,
        "property_label_key": None,
        "url": "/data/uk_postcode_areas.topo-9e651b39d2.json",
    },
    "us_zipcode_tabulation_areas": {
        "extents_json_url": "https://maps-tiles-b.lookercdn.com/us_zcta510/extents.json",
        "feature_key": "tl_2016_us_zcta510geojson",
        "format": "vector_tile_region",
        "max_zoom_level": 12,
        "min_zoom_level": None,
        "name": "us_zipcode_tabulation_areas",
        "projection": None,
        "property_key": "ZCTA5CE10",
        "property_label_key": None,
        "url": "https://maps-tiles-a.lookercdn.com/us_zcta510/{z}/{x}/{y}.pbf",
    },
}

_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
DEFAULT_ENUMS: dict[str, list[dict[str, str]]] = {
    "date_day_of_week": [{"label": d, "value": d} for d in _DAYS],
    "date_day_of_week_index": [
        {"label": f"{i} - {d}", "value": str(i)} for i, d in enumerate(_DAYS)
    ],
    "date_month_name": [{"label": m, "value": m} for m in _MONTHS],
    "date_quarter_of_year": [
        {"label": f"Q{i}", "value": f"Q{i}"} for i in range(1, 5)
    ],
    "date_fiscal_quarter_of_year": [
        {"label": f"Q{i}", "value": f"Q{i}"} for i in range(1, 5)
    ],
    "yesno": [{"label": "Yes", "value": "Yes"}, {"label": "No", "value": "No"}],
}

TIMEFRAME_INTERVALS: dict[str, dict[str, Any]] = {
    "date": {"name": "day", "count": 1},
    "date_date": {"name": "day", "count": 1},
    "date_fiscal_quarter": {"name": "month", "count": 3},
    "date_fiscal_year": {"name": "year", "count": 1},
    "date_hour": {"name": "hour", "count": 1},
    **{f"date_hour{n}": {"name": "hour", "count": n} for n in (2, 3, 4, 6, 8, 12)},
    "date_microsecond": {"name": "microsecond", "count": 1},
    "date_millisecond": {"name": "millisecond", "count": 1},
    **{
        f"date_millisecond{n}": {"name": "millisecond", "count": n}
        for n in (2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, 500)
    },
    "date_minute": {"name": "minute", "count": 1},
    **{
        f"date_minute{n}": {"name": "minute", "count": n}
        for n in (2, 3, 4, 5, 6, 10, 12, 15, 20, 30)
    },
    "date_month": {"name": "month", "count": 1},
    "date_quarter": {"name": "month", "count": 3},
    "date_second": {"name": "second", "count": 1},
    "date_time": {"name": "second", "count": 1},
    "date_week": {"name": "week", "count": 1},
    "date_year": {"name": "year", "count": 1},
}

NUMERIC_DIMENSION_TYPES = frozenset(
    {
        "number",
        "int",
        "date_day_of_month",
        "date_day_of_week_index",
        "date_day_of_year",
        "date_fiscal_month_num",
        "date_hour_of_day",
        "date_month_num",
        "date_week_of_year",
        "distance",
        "duration_day",
        "duration_hour",
        "duration_minute",
        "duration_month",
        "duration_quarter",
        "duration_second",
        "duration_week",
        "duration_year",
    }
)

NON_NUMERIC_MEASURE_TYPES = frozenset({"list", "string", "yesno", "zipcode", "date"})

RANGE_FILL_TYPES = frozenset(
    {
        "date",
        "date_date",
        "date_fiscal_quarter",
        "date_fiscal_year",
        "date_hour",
        "date_minute",
        "date_month",
        "date_quarter",
        "date_week",
        "date_year",
    }
)

ENUM_FILL_TYPES = frozenset(
    {
        "date_day_of_month",
        "date_day_of_week",
        "date_day_of_week_index",
        "date_day_of_year",
        "date_fiscal_month_num",
        "date_fiscal_quarter_of_year",
        "date_hour_of_day",
        "date_month_name",
        "date_month_num",
        "date_quarter_of_year",
        "date_time_of_day",
        "date_week_of_year",
        "tier",
        "yesno",
    }
)

SUGGESTABLE_TYPES = frozenset(
    {
        "string",
        "tier",
        "yesno",
        "zipcode",
        "unquoted",
        "date_day_of_week",
        "date_fiscal_quarter_of_year",
        "date_month_name",
        "date_quarter_of_year",
    }
)

LOWERCASE_TITLE_WORDS = frozenset(
    {"of", "in", "to", "with", "for", "and", "or", "on", "at"}
)


class ApiLookmlModelNavExplore(BaseModel):
    description: str | None = None
    label: str | None = None
    hidden: bool = False
    group_label: str | None = None
    name: str


class ApiLookmlModel(BaseModel):
    has_content: bool = False
    label: str | None = None
    name: str
    project_name: str | None = None
    unlimited_db_connections: bool = False
    allowed_db_connection_names: list[str] = Field(default_factory=list)
    explores: list[ApiLookmlModelNavExplore] = Field(default_factory=list)


class ApiLookmlModelExploreFieldTimeInterval(BaseModel):
    name: str
    count: int


class ApiLookmlModelExploreFieldEnumeration(BaseModel):
    label: str
    value: str


class ApiLookmlModelExploreFieldSqlCase(BaseModel):
    value: str
    condition: str


class ApiLookmlModelExploreFieldMeasureFilters(BaseModel):
    field: str
    condition: str


class ApiLookmlModelExploreFieldMapLayer(BaseModel):
    extents_json_url: str | None = None
    feature_key: str | None = None
    format: str | None = None
    max_zoom_level: int | None = None
    min_zoom_level: int | None = None
    name: str | None = None
    projection: str | None = None
    property_key: str | None = None
    property_label_key: str | None = None
    url: str | None = None


class ApiLookmlModelExploreField(BaseModel):
    align: str = "left"
    available_custom_timeframes: list[str] | None = None
    can_filter: bool = True
    category: str
    default_filter_value: str | None = None
    description: str | None = ""
    enumerations: list[ApiLookmlModelExploreFieldEnumeration] | None = None
    field_group_label: str | None = None
    fill_style: str | None = None
    fiscal_month_offset: int = 0
    has_allowed_values: bool = False
    hidden: bool = False
    is_filter: bool = False
    is_numeric: bool = False
    label: str
    label_from_parameter: str | None = None
    label_short: str
    map_layer: ApiLookmlModelExploreFieldMapLayer | None = None
    name: str
    strict_value_format: bool = False
    requires_refresh_on_sort: bool = False
    sortable: bool = True
    suggestions: list[str] | None = None
    synonyms: list[str] | None = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    type: str
    user_attribute_filter_types: list[str] = Field(default_factory=list)
    value_format: str | None = None
    value_format_name: str | None = None
    view: str
    view_label: str
    dynamic: bool = False
    week_start_day: str = "monday"
    original_view: str
    dimension_group: str | None = None
    error: str | None = None
    field_group_variant: str | None = None
    measure: bool = False
    parameter: bool = False
    primary_key: bool = False
    project_name: str | None = None
    scope: str
    suggest_dimension: str | None = None
    suggest_explore: str | None = None
    suggestable: bool = False
    liquid_expression: str | None = None
    lookml_expression: str | None = None
    is_fiscal: bool = False
    is_timeframe: bool = False
    can_time_filter: bool = False
    time_interval: ApiLookmlModelExploreFieldTimeInterval | None = None
    lookml_link: str | None = None
    period_over_period_params: dict[str, Any] | None = None
    permanent: bool | None = None
    source_file: str | None = None
    source_file_path: str | None = None
    sql: str | None = None
    sql_case: list[ApiLookmlModelExploreFieldSqlCase] | None = None
    filters: list[ApiLookmlModelExploreFieldMeasureFilters] | None = None


class ApiLookmlModelExploreFieldset(BaseModel):
    dimensions: list[ApiLookmlModelExploreField] = Field(default_factory=list)
    measures: list[ApiLookmlModelExploreField] = Field(default_factory=list)
    filters: list[ApiLookmlModelExploreField] = Field(default_factory=list)
    parameters: list[ApiLookmlModelExploreField] = Field(default_factory=list)


class ApiLookmlModelExploreAlias(BaseModel):
    name: str
    value: str


class ApiLookmlModelExploreSet(BaseModel):
    name: str
    value: list[str] = Field(default_factory=list)


class ApiLookmlModelExploreJoins(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dependent_fields: list[str] = Field(default_factory=list)
    fields: list[str] | None = None
    foreign_key: str | None = None
    from_: str | None = Field(default=None, alias="from", serialization_alias="from")
    outer_only: bool | None = None
    relationship: str = ""
    required_joins: list[str] | None = None
    sql_foreign_key: str | None = None
    sql_on: str | None = None
    sql_table_name: str | None = None
    type: str | None = None
    view_label: str | None = None
    name: str


class ApiLookmlModelExploreTurtleLook(BaseModel):
    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    pivots: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int | str | None = None
    sorts: list[dict[str, Any]] = Field(default_factory=list)
    name: str
    label: str
    label_short: str
    can_turtle: bool = False
    type: str = "query"
    description: str | None = None
    lookml_link: str | None = None


class ApiLookmlModelExplore(BaseModel):
    id: str
    name: str
    description: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connection_name: str | None = None
    null_sort_treatment: str | None = "low"
    files: list[str] = Field(default_factory=list)
    source_file: str | None = None
    model_name: str
    view_name: str
    hidden: bool = False
    sql_table_name: str | None = None
    access_filters: list[dict[str, Any]] = Field(default_factory=list)
    aliases: list[ApiLookmlModelExploreAlias] = Field(default_factory=list)
    always_filter: list[dict[str, Any]] = Field(default_factory=list)
    conditionally_filter: list[dict[str, Any]] = Field(default_factory=list)
    index_fields: list[str] = Field(default_factory=list)
    sets: list[ApiLookmlModelExploreSet] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] | None = None
    fields: ApiLookmlModelExploreFieldset = Field(
        default_factory=ApiLookmlModelExploreFieldset
    )
    joins: list[ApiLookmlModelExploreJoins] = Field(default_factory=list)
    group_label: str | None = None
    always_join: list[str] = Field(default_factory=list)
    label: str | None = None
    project_name: str | None = None
    title: str | None = None
    lookml_link: str | None = None
    access_filter_fields: list[str] = Field(default_factory=list)
    turtle_looks: list[ApiLookmlModelExploreTurtleLook] = Field(default_factory=list)


class LookmlToApiResult(BaseModel):
    all_lookml_models: list[ApiLookmlModel] = Field(default_factory=list)
    lookml_model_explores: dict[str, ApiLookmlModelExplore] = Field(
        default_factory=dict
    )


def _titleize(name: str) -> str:
    words = name.replace("_", " ").split(" ")
    out: list[str] = []
    for i, w in enumerate(words):
        low = w.lower()
        if i > 0 and low in LOWERCASE_TITLE_WORDS:
            out.append(low)
        elif low == "id":
            out.append("ID")
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _lookml_link(project_name: str | None, file_path: str, line: int) -> str | None:
    if not file_path:
        return None
    proj = project_name or ""
    encoded = quote(file_path, safe="")
    return f"/projects/{proj}/files/{encoded}?line={line}"


def _resolve_project_name(project: LookmlProject) -> str | None:
    if project.manifest and project.manifest.project_name:
        return project.manifest.project_name
    if (
        isinstance(project.file, BaseModel)
        and isinstance(project.file.manifest, BaseModel)
        and project.file.manifest.project_name
    ):
        return project.file.manifest.project_name
    return None


def _ordered_model_explore_names(
    model_name: str,
    model_obj: LookmlModel,
    project: LookmlProject,
) -> list[str]:
    assembled = list((model_obj.explore or {}).keys())
    if not isinstance(project.file, BaseModel) or not isinstance(
        project.file.model, dict
    ):
        return assembled
    raw_model = project.file.model.get(model_name)
    own_keys = set(
        (raw_model.explore or {}).keys()
        if isinstance(raw_model, (LookmlModel, BaseModel))
        and getattr(raw_model, "explore", None)
        else ()
    )
    own = [k for k in assembled if k in own_keys]
    included = [k for k in reversed(assembled) if k not in own_keys]
    return [*included, *own]


def _qualify_field_ref(ref: str, default_alias: str) -> str:
    clean = ref.strip()
    return clean if "." in clean else f"{default_alias}.{clean}"


def _extract_measure_filters(
    raw_filters: Any,
    default_alias: str,
) -> list[ApiLookmlModelExploreFieldMeasureFilters] | None:
    if not raw_filters:
        return None
    out: list[ApiLookmlModelExploreFieldMeasureFilters] = []
    for item in raw_filters if isinstance(raw_filters, list) else [raw_filters]:
        d = (
            item.model_dump(exclude_none=True)
            if isinstance(item, BaseModel)
            else item
        )
        if not isinstance(d, dict):
            continue
        pairs = (
            [(d["field"], d["value"])]
            if "field" in d and "value" in d
            else [(k, v) for k, v in d.items() if not k.startswith("$")]
        )
        for k, v in pairs:
            fk = k[0] if isinstance(k, list) and k else k
            fv = v[0] if isinstance(v, list) and v else v
            out.append(
                ApiLookmlModelExploreFieldMeasureFilters(
                    field=_qualify_field_ref(str(fk), default_alias),
                    condition=str(fv),
                )
            )
    return out or None


def _build_tier_metadata(
    dim: LookmlDimension | LookmlMeasure,
) -> tuple[
    list[str] | None,
    list[ApiLookmlModelExploreFieldEnumeration] | None,
    list[ApiLookmlModelExploreFieldSqlCase] | None,
    str | None,
]:
    if dim.case is not None:
        whens = (
            dim.case.when
            if isinstance(dim.case.when, list)
            else ([dim.case.when] if dim.case.when else [])
        )
        raw_cases = [
            (w.label or "", (w.sql or "").lstrip(" "))
            for w in whens
            if isinstance(w, LookmlCaseWhen)
        ]
        if not raw_cases:
            return None, None, None, None
        else_val = str(dim.case.else_) if isinstance(dim.case.else_, str) else None
    else:
        raw_tiers = (
            getattr(dim, "tiers", None)
            or getattr(dim, "bins", None)
            or getattr(dim, "tier", None)
        )
        if not isinstance(raw_tiers, list) or not raw_tiers:
            return None, None, None, None
        nums = [float(x) for x in raw_tiers]
        style = (dim.style or "classic").lower()
        sql_expr = (dim.sql or f"${{TABLE}}.{dim.name_}").lstrip(" ")

        if style == "integer":
            ints = [int(x) for x in nums]
            raw_cases = [
                (f"Below {ints[0]}", f"{sql_expr} < {ints[0]}"),
                *(
                    (f"{lo}", f"{sql_expr} = {lo}")
                    if hi - lo == 1
                    else (
                        f"{lo} to {hi - 1}",
                        f"{sql_expr} >= {lo} AND {sql_expr} < {hi}",
                    )
                    for lo, hi in pairwise(ints)
                ),
                (f"{ints[-1]} or Above", f"{sql_expr} >= {ints[-1]}"),
            ]
            else_val = "Undefined"
        elif style == "relational":
            raw_cases = [
                (f"< {nums[0]}", f"{sql_expr} < {nums[0]}"),
                *(
                    (
                        f">= {lo} and < {hi}",
                        f"{sql_expr} >= {lo} AND {sql_expr} < {hi}",
                    )
                    for lo, hi in pairwise(nums)
                ),
                (f">= {nums[-1]}", f"{sql_expr} >= {nums[-1]}"),
            ]
            else_val = "Undefined"
        else:
            raw_cases = [
                (f"(-inf,{nums[0]})", f"{sql_expr} < {nums[0]}"),
                *(
                    (f"[{lo},{hi})", f"{sql_expr} >= {lo} AND {sql_expr} < {hi}")
                    for lo, hi in pairwise(nums)
                ),
                (f"[{nums[-1]},inf)", f"{sql_expr} >= {nums[-1]}"),
            ]
            if style == "classic":
                raw_cases = [
                    (f"T{i:02d} {v}", c) for i, (v, c) in enumerate(raw_cases)
                ]
                else_val = "TXX Undefined"
            else:
                else_val = "Undefined"

    cases = [
        *[
            ApiLookmlModelExploreFieldSqlCase(value=v, condition=c)
            for v, c in raw_cases
        ],
        *(
            [ApiLookmlModelExploreFieldSqlCase(value=else_val, condition="else")]
            if else_val is not None
            else []
        ),
    ]
    when_lines = [f"WHEN {c} THEN '{v}'" for v, c in raw_cases]
    else_part = f"ELSE '{else_val}'" if else_val is not None else ""
    tier_sql = "CASE\n" + "\n".join([*when_lines, else_part, "END"])
    suggestions = [c.value for c in cases]
    enums = [
        ApiLookmlModelExploreFieldEnumeration(label=c.value, value=c.value)
        for c in cases
    ]
    return suggestions, enums, cases, tier_sql


def _user_attribute_filter_types(category: str, ftype: str) -> list[str]:
    if category == "measure":
        if ftype in (
            "list",
            "percent_of_total",
            "percent_of_previous",
            "running_total",
        ):
            return []
        if ftype not in NON_NUMERIC_MEASURE_TYPES and (
            not ftype.startswith("date_") or ftype in NUMERIC_DIMENSION_TYPES
        ):
            return ["number", "advanced_filter_number"]
    if ftype in ("date_raw", "location"):
        return []
    if ftype in NUMERIC_DIMENSION_TYPES:
        return ["number", "advanced_filter_number"]
    if ftype in TIMEFRAME_INTERVALS:
        return ["datetime", "advanced_filter_datetime"]
    return ["string", "advanced_filter_string"]


def _resolve_field_source(
    chain: list[tuple[str, Any, dict[str, Any]]],
    ftype: str,
    fname: str,
    fallback_file: str,
    fallback_line: int,
) -> tuple[int, int, str, int]:
    src_file = fallback_file
    src_line = fallback_line
    first_idx = 0
    first_line = fallback_line
    found = False
    for idx, (fpath, _, p_dict) in enumerate(chain):
        type_pos = p_dict.get(ftype, {})
        if isinstance(type_pos, dict) and fname in type_pos:
            f_pos = type_pos[fname]
            if isinstance(f_pos, dict) and "$p" in f_pos and f_pos["$p"]:
                src_file = fpath
                src_line = int(f_pos["$p"][0]) + 1
                if not found:
                    first_idx = idx
                    first_line = src_line
                    found = True
    return first_idx, first_line, src_file, src_line


def _find_primary_key_sql(view_obj: LookmlView, view_alias: str) -> str:
    for dname, dobj in (view_obj.dimension or {}).items():
        if dobj.primary_key:
            raw_sql = (dobj.sql or _default_table_sql(dname)).lstrip(" ")
            return re.sub(r"\$\{\s*TABLE\s*\}\.", f"{view_alias}.", raw_sql)
    return f"{view_alias}.id"


def _build_field(
    *,
    category: str,
    ftype: str,
    name: str,
    label: str,
    label_short: str,
    view_alias: str,
    view_label: str,
    original_view: str,
    explore_name: str,
    project_name: str | None,
    source_file: str,
    source_line: int,
    description: str | None = None,
    hidden: bool = False,
    primary_key: bool = False,
    sql: str | None = None,
    value_format: str | None = None,
    value_format_name: str | None = None,
    synonyms: list[str] | None = None,
    tags: list[str] | None = None,
    dimension_group: str | None = None,
    field_group_label: str | None = None,
    field_group_variant: str | None = None,
    map_layer_name: str | None = None,
    enumerations: list[ApiLookmlModelExploreFieldEnumeration] | None = None,
    suggestions: list[str] | None = None,
    sql_case: list[ApiLookmlModelExploreFieldSqlCase] | None = None,
    filters: list[ApiLookmlModelExploreFieldMeasureFilters] | None = None,
    default_filter_value: str | None = None,
    has_allowed_values: bool = False,
    label_from_parameter: str | None = None,
    allow_fill: bool | None = None,
    can_filter_override: bool | None = None,
    suggestable_override: bool | None = None,
    suggest_dimension_override: str | None = None,
    suggest_explore_override: str | None = None,
    fiscal_month_offset: int = 0,
    week_start_day: str = "monday",
    model_named_value_formats: dict[str, LookmlNamedValueFormat] | None = None,
    model_map_layers: dict[str, LookmlMapLayer] | None = None,
) -> ApiLookmlModelExploreField:
    is_num = (
        category == "measure"
        and ftype not in NON_NUMERIC_MEASURE_TYPES
        and (not ftype.startswith("date_") or ftype in NUMERIC_DIMENSION_TYPES)
    ) or ftype in NUMERIC_DIMENSION_TYPES
    align = "right" if is_num else "left"
    sortable = not (category == "measure" and ftype == "list")
    default_can_filter = ftype not in (
        "date_raw",
        "list",
        "percent_of_total",
        "percent_of_previous",
        "running_total",
    )
    can_filter = (
        can_filter_override if can_filter_override is not None else default_can_filter
    )
    requires_refresh_on_sort = ftype in ("percent_of_previous", "running_total")
    fill_style = (
        None
        if allow_fill is False
        else (
            "range"
            if ftype in RANGE_FILL_TYPES
            else ("enumeration" if ftype in ENUM_FILL_TYPES or sql_case else None)
        )
    )
    ti_raw = TIMEFRAME_INTERVALS.get(ftype)
    time_interval = (
        ApiLookmlModelExploreFieldTimeInterval(**ti_raw) if ti_raw else None
    )
    is_timeframe = time_interval is not None
    is_fiscal = ftype.startswith("date_fiscal_")
    can_time_filter = category == "dimension" and bool(
        ti_raw
        and ti_raw["name"]
        in ("hour", "minute", "second", "millisecond", "microsecond")
    )

    eff_vfn = value_format_name
    nvf = (model_named_value_formats or {}).get(eff_vfn) if eff_vfn else None
    strict_vf = (
        bool(nvf.strict_value_format)
        if isinstance(nvf, LookmlNamedValueFormat)
        else False
    )
    eff_vf = (
        value_format
        or (nvf.value_format if isinstance(nvf, LookmlNamedValueFormat) else None)
        or (VALUE_FORMAT_MAP.get(eff_vfn) if eff_vfn else None)
        or (
            '#,##0"%"'
            if ftype in ("percent_of_total", "percent_of_previous")
            else None
        )
        or ("0" if ftype.startswith("duration_") else None)
    )

    eff_map_layer_key = map_layer_name or (
        "us_zipcode_tabulation_areas" if ftype == "zipcode" else None
    )
    custom_ml = (
        (model_map_layers or {}).get(eff_map_layer_key) if eff_map_layer_key else None
    )
    if isinstance(custom_ml, LookmlMapLayer) and eff_map_layer_key:
        map_layer = ApiLookmlModelExploreFieldMapLayer(
            extents_json_url=custom_ml.extents_json_url,
            feature_key=custom_ml.feature_key,
            format=custom_ml.format,
            max_zoom_level=custom_ml.max_zoom_level,
            min_zoom_level=custom_ml.min_zoom_level,
            name=eff_map_layer_key,
            projection=custom_ml.projection,
            property_key=custom_ml.property_key,
            property_label_key=custom_ml.property_label_key,
            url=custom_ml.url or custom_ml.file,
        )
    elif eff_map_layer_key and eff_map_layer_key in BUILTIN_MAP_LAYERS:
        map_layer = ApiLookmlModelExploreFieldMapLayer(
            **BUILTIN_MAP_LAYERS[eff_map_layer_key]
        )
    elif eff_map_layer_key:
        map_layer = ApiLookmlModelExploreFieldMapLayer(name=eff_map_layer_key)
    else:
        map_layer = None

    if enumerations is None and ftype in DEFAULT_ENUMS:
        if ftype in ("date_day_of_week", "date_day_of_week_index"):
            w_idx = next(
                (i for i, d in enumerate(_DAYS) if d.lower() == week_start_day), 0
            )
            rot_days = _DAYS[w_idx:] + _DAYS[:w_idx]
            enumerations = (
                [
                    ApiLookmlModelExploreFieldEnumeration(label=d, value=d)
                    for d in rot_days
                ]
                if ftype == "date_day_of_week"
                else [
                    ApiLookmlModelExploreFieldEnumeration(
                        label=f"{i} - {d}", value=str(i)
                    )
                    for i, d in enumerate(rot_days)
                ]
            )
        else:
            enumerations = [
                ApiLookmlModelExploreFieldEnumeration(**e)
                for e in DEFAULT_ENUMS[ftype]
            ]

    src_path = (
        f"{project_name}/{source_file}"
        if project_name and source_file
        else (source_file or None)
    )

    return ApiLookmlModelExploreField(
        align=align,
        can_filter=can_filter,
        category=category,
        default_filter_value=default_filter_value,
        description=description if description is not None else "",
        enumerations=enumerations,
        field_group_label=field_group_label,
        fill_style=fill_style,
        fiscal_month_offset=fiscal_month_offset,
        has_allowed_values=has_allowed_values,
        hidden=hidden,
        is_filter=category in ("filter", "parameter"),
        is_numeric=is_num,
        label=label,
        label_from_parameter=label_from_parameter,
        label_short=label_short,
        map_layer=map_layer,
        name=name,
        strict_value_format=strict_vf,
        requires_refresh_on_sort=requires_refresh_on_sort,
        sortable=sortable,
        suggestions=suggestions,
        synonyms=list(synonyms or []),
        tags=list(tags or []),
        type=ftype,
        user_attribute_filter_types=_user_attribute_filter_types(category, ftype),
        value_format=eff_vf,
        value_format_name=eff_vfn,
        view=view_alias,
        view_label=view_label,
        week_start_day=week_start_day,
        original_view=original_view,
        dimension_group=dimension_group,
        field_group_variant=field_group_variant,
        measure=category == "measure",
        parameter=category == "parameter",
        primary_key=primary_key,
        project_name=project_name,
        scope=name.split(".", 1)[0] if "." in name else view_alias,
        suggest_dimension=suggest_dimension_override or name,
        suggest_explore=suggest_explore_override or explore_name,
        suggestable=(
            suggestable_override
            if suggestable_override is not None
            else (
                bool(sql_case)
                or (ftype in SUGGESTABLE_TYPES and category != "measure")
            )
        ),
        is_fiscal=is_fiscal,
        is_timeframe=is_timeframe,
        can_time_filter=can_time_filter,
        time_interval=time_interval,
        lookml_link=_lookml_link(project_name, source_file, source_line),
        source_file=source_file or None,
        source_file_path=src_path,
        sql=sql.lstrip(" ") if isinstance(sql, str) else None,
        sql_case=sql_case,
        filters=filters,
    )


def _expand_view_for_explore(
    *,
    view_alias: str,
    original_view_name: str,
    view_obj: LookmlView,
    view_chain: list[tuple[str, Any, dict[str, Any]]],
    default_view_label: str,
    is_symmetric_join: bool,
    explore_name: str,
    explore_fields_spec: list[str] | None,
    join_fields_spec: list[str] | None,
    views_by_alias: dict[str, LookmlView],
    base_alias: str,
    project_name: str | None,
    model_obj: LookmlModel,
) -> tuple[
    list[ApiLookmlModelExploreField],
    list[ApiLookmlModelExploreField],
    list[ApiLookmlModelExploreField],
    list[ApiLookmlModelExploreField],
    list[str],
    list[ApiLookmlModelExploreAlias],
]:
    dims: list[ApiLookmlModelExploreField] = []
    meas: list[ApiLookmlModelExploreField] = []
    filts: list[ApiLookmlModelExploreField] = []
    params: list[ApiLookmlModelExploreField] = []
    view_set_fields: list[str] = []
    aliases: list[ApiLookmlModelExploreAlias] = []

    fiscal_offset = (
        model_obj.fiscal_month_offset
        if model_obj.fiscal_month_offset is not None
        else 0
    )
    wk_start = (model_obj.week_start_day or "monday").lower()

    view_file, view_pos = _chain_root_pos(view_chain, original_view_name)
    view_line = int(view_pos[0]) + 1

    def _allowed(cands: set[str]) -> bool:
        return _is_field_allowed_by_spec(
            join_fields_spec, view_alias, cands, views_by_alias, view_alias
        ) and _is_field_allowed_by_spec(
            explore_fields_spec, view_alias, cands, views_by_alias, base_alias
        )

    def _record_aliases(raw_alias: list[str] | str | None, full_name: str) -> None:
        if not raw_alias:
            return
        for a in raw_alias if isinstance(raw_alias, list) else [raw_alias]:
            if a:
                aliases.append(ApiLookmlModelExploreAlias(name=str(a), value=full_name))

    decl_items: list[tuple[int, int, int, int, str, str, str, Any]] = []
    seq = 0
    for ftype, fdict in (
        ("dimension", view_obj.dimension or {}),
        ("dimension_group", view_obj.dimension_group or {}),
        ("measure", view_obj.measure or {}),
        ("filter", view_obj.filter if isinstance(view_obj.filter, dict) else {}),
        ("parameter", view_obj.parameter or {}),
    ):
        for fname, fobj in fdict.items():
            seq += 1
            c_idx, f_first_line, ffile, fline = _resolve_field_source(
                view_chain, ftype, fname, view_file, view_line
            )
            decl_items.append(
                (c_idx, f_first_line, seq, fline, ffile, ftype, fname, fobj)
            )

    decl_items.sort(key=lambda x: (x[0], x[1], x[2]))
    pk_sql = _find_primary_key_sql(view_obj, view_alias)

    for _, _, _, src_line, src_file, ftype, fname, fobj in decl_items:
        eff_view_label = getattr(fobj, "view_label", None) or default_view_label
        is_hidden = bool(
            getattr(fobj, "hidden", False) or view_obj.fields_hidden_by_default
        )
        raw_syn = getattr(fobj, "synonyms", None)
        f_synonyms = (
            [raw_syn]
            if isinstance(raw_syn, str)
            else (list(raw_syn) if isinstance(raw_syn, list) else None)
        )
        eff_sug_override = (
            fobj.suggestable
            if fobj.suggestable is not None
            else (False if view_obj.suggestions is False else None)
        )
        eff_sug_dim = (
            _qualify_field_ref(fobj.suggest_dimension, view_alias)
            if fobj.suggest_dimension
            else None
        )

        def _mk(
            *,
            category: str,
            ft: str,
            name: str,
            short: str,
            hidden: bool = is_hidden,
            sql: str | None = None,
            tags: list[str] | None = fobj.tags,
            synonyms: list[str] | None = f_synonyms,
            **kw: Any,
        ) -> ApiLookmlModelExploreField:
            return _build_field(
                category=category,
                ftype=ft,
                name=name,
                label=f"{eff_view_label} {short}",
                label_short=short,
                view_alias=view_alias,
                view_label=eff_view_label,
                original_view=original_view_name,
                explore_name=explore_name,
                project_name=project_name,
                source_file=src_file,
                source_line=src_line,
                description=fobj.description,
                hidden=hidden,
                sql=sql,
                synonyms=synonyms,
                tags=tags,
                label_from_parameter=fobj.label_from_parameter,
                allow_fill=fobj.allow_fill,
                suggestable_override=eff_sug_override,
                suggest_dimension_override=eff_sug_dim,
                suggest_explore_override=fobj.suggest_explore,
                fiscal_month_offset=fiscal_offset,
                week_start_day=wk_start,
                model_named_value_formats=model_obj.named_value_format,
                model_map_layers=model_obj.map_layer,
                **kw,
            )

        if ftype == "dimension" and isinstance(fobj, LookmlDimension):
            if not _allowed({fname.lower()}):
                continue
            full_name = _qualify_field_ref(fname, view_alias)
            _record_aliases(fobj.alias, full_name)
            dim_type = "tier" if fobj.type in ("tier", "bin") else (fobj.type or "string")
            base_short = fobj.label or _titleize(fname.split(".", 1)[-1])
            if dim_type == "yesno":
                base_short = f"{base_short} (Yes / No)"

            if dim_type == "location":
                lat = (fobj.sql_latitude or "").lstrip(" ")
                lon = (fobj.sql_longitude or "").lstrip(" ")
                dims.append(
                    _mk(
                        category="dimension",
                        ft="location",
                        name=full_name,
                        short=base_short,
                        primary_key=bool(fobj.primary_key),
                        sql=f"Latitude:\n{lat}\n\nLongitude:\n{lon}",
                        value_format=fobj.value_format,
                        value_format_name=fobj.value_format_name,
                        field_group_label=fobj.group_label,
                        field_group_variant=fobj.group_item_label or base_short,
                        map_layer_name=fobj.map_layer_name,
                    )
                )
                view_set_fields.extend(
                    [
                        full_name,
                        f"{full_name}_bin_level",
                        f"{full_name}_latitude_min",
                        f"{full_name}_latitude_max",
                        f"{full_name}_longitude_min",
                        f"{full_name}_longitude_max",
                    ]
                )
                for suffix, m_type in (
                    ("latitude_min", "min"),
                    ("latitude_max", "max"),
                    ("longitude_min", "min"),
                    ("longitude_max", "max"),
                ):
                    m_fname = f"{fname}_{suffix}"
                    m_full = _qualify_field_ref(m_fname, view_alias)
                    m_short = fobj.label or _titleize(m_fname.split(".", 1)[-1])
                    meas.append(
                        _mk(
                            category="measure",
                            ft=m_type,
                            name=m_full,
                            short=m_short,
                            hidden=True,
                            sql=m_full,
                            tags=None,
                            synonyms=None,
                            field_group_variant=m_short,
                        )
                    )
            else:
                sug, enums, cases, tier_sql = (
                    _build_tier_metadata(fobj)
                    if dim_type == "tier" or fobj.case is not None
                    else (
                        fobj.suggestions
                        if isinstance(fobj.suggestions, list)
                        else None,
                        None,
                        None,
                        None,
                    )
                )
                if tier_sql is not None:
                    eff_dim_sql = tier_sql
                elif dim_type.startswith("duration_") and (
                    fobj.sql_start is not None
                    or fobj.sql_end is not None
                    or fobj.sql is None
                ):
                    eff_dim_sql = (
                        f"Start:\n{(fobj.sql_start or '').lstrip(' ')}\n\n"
                        f"End:\n{(fobj.sql_end or '').lstrip(' ')}"
                    )
                elif fobj._sql_defaulted or fobj.sql is None:
                    eff_dim_sql = re.sub(
                        r"^\$\{\s*TABLE\s*\}\.",
                        f"{view_alias}.",
                        fobj.sql or _default_table_sql(fname),
                    )
                else:
                    eff_dim_sql = fobj.sql
                eff_vf = fobj.value_format or (
                    DISTANCE_UNIT_FORMATS.get(fobj.units)
                    if dim_type == "distance" and fobj.units
                    else None
                )
                dims.append(
                    _mk(
                        category="dimension",
                        ft=dim_type,
                        name=full_name,
                        short=base_short,
                        primary_key=bool(fobj.primary_key),
                        sql=eff_dim_sql,
                        value_format=eff_vf,
                        value_format_name=fobj.value_format_name,
                        field_group_label=fobj.group_label,
                        field_group_variant=fobj.group_item_label or base_short,
                        map_layer_name=fobj.map_layer_name,
                        enumerations=enums,
                        suggestions=sug,
                        sql_case=cases,
                        can_filter_override=fobj.can_filter,
                    )
                )
                view_set_fields.append(full_name)
                if dim_type == "tier" or (
                    fobj.case is not None and not fobj.alpha_sort
                ):
                    view_set_fields.append(f"{full_name}__sort_")

        elif ftype == "dimension_group" and isinstance(fobj, LookmlDimensionGroup):
            dg_type = fobj.type or "time"
            if dg_type == "duration":
                ivs = [
                    iv.removesuffix("s")
                    for iv in (fobj.intervals or DEFAULT_DURATION_INTERVALS)
                ]
                if not _allowed(
                    {fname.lower()} | {f"{iv}s_{fname}".lower() for iv in ivs}
                ):
                    continue
                dg_id = _qualify_field_ref(fname, view_alias)
                base_dg_title = fobj.label or _titleize(fname.split(".", 1)[-1])
                fg_label = fobj.group_label or f"Duration {base_dg_title}"
                dg_sql = (
                    f"Start:\n{(fobj.sql_start or '').lstrip(' ')}\n\n"
                    f"End:\n{(fobj.sql_end or '').lstrip(' ')}"
                )
                for iv in ivs:
                    tf_fname = f"{iv}s_{fname}"
                    if not _allowed({fname.lower(), tf_fname.lower()}):
                        continue
                    full_name = _qualify_field_ref(tf_fname, view_alias)
                    tf_variant = _titleize(f"{iv}s")
                    dims.append(
                        _mk(
                            category="dimension",
                            ft=f"duration_{iv}",
                            name=full_name,
                            short=f"{tf_variant} {base_dg_title}",
                            hidden=is_hidden,
                            sql=dg_sql,
                            value_format=fobj.value_format,
                            value_format_name=fobj.value_format_name,
                            dimension_group=dg_id,
                            field_group_label=fg_label,
                            field_group_variant=tf_variant,
                            map_layer_name=fobj.map_layer_name,
                            can_filter_override=fobj.can_filter,
                        )
                    )
                    view_set_fields.append(full_name)
                continue

            tfs = list(fobj.timeframes or DEFAULT_TIMEFRAMES)
            if not _allowed(
                {fname.lower()}
                | {(fname if tf == "yesno" else f"{fname}_{tf}").lower() for tf in tfs}
            ):
                continue
            dg_id = _qualify_field_ref(fname, view_alias)
            base_dg_title = _titleize(fname.split(".", 1)[-1])
            fg_label = (
                fobj.group_label
                or fobj.label
                or (f"{base_dg_title} Date" if dg_type == "time" else base_dg_title)
            )
            for tf in tfs:
                tf_fname = fname if tf == "yesno" else f"{fname}_{tf}"
                if not _allowed({fname.lower(), tf_fname.lower()}):
                    continue
                full_name = _qualify_field_ref(tf_fname, view_alias)
                tf_variant = "Yes / No" if tf == "yesno" else _titleize(tf)
                short_lbl = fobj.label or (
                    f"{base_dg_title} (Yes / No)"
                    if tf == "yesno"
                    else f"{base_dg_title} {tf_variant}"
                )
                tf_type = (
                    "yesno"
                    if tf == "yesno"
                    else (f"date_{tf}" if dg_type == "time" else f"{dg_type}_{tf}")
                )
                dims.append(
                    _mk(
                        category="dimension",
                        ft=tf_type,
                        name=full_name,
                        short=short_lbl,
                        hidden=is_hidden or tf == "raw",
                        sql=fobj.sql or _default_table_sql(fname),
                        value_format=fobj.value_format,
                        value_format_name=fobj.value_format_name,
                        dimension_group=dg_id,
                        field_group_label=fg_label,
                        field_group_variant=tf_variant,
                        map_layer_name=fobj.map_layer_name,
                        can_filter_override=fobj.can_filter,
                    )
                )
                view_set_fields.append(full_name)
                if tf == "day_of_week" and "day_of_week_index" not in tfs:
                    view_set_fields.append(
                        _qualify_field_ref(f"{fname}_day_of_week_index", view_alias)
                    )

        elif ftype == "measure" and isinstance(fobj, LookmlMeasure):
            raw_mtype = fobj.type or "string"
            if raw_mtype == "time":
                tfs = list(fobj.timeframes or DEFAULT_TIMEFRAMES)
                if not _allowed(
                    {fname.lower()}
                    | {
                        (fname if tf == "yesno" else f"{fname}_{tf}").lower()
                        for tf in tfs
                    }
                ):
                    continue
                base_m_title = _titleize(fname.split(".", 1)[-1])
                fg_label = fobj.group_label or fobj.label or f"{base_m_title} Date"
                m_filters = _extract_measure_filters(fobj.filters, view_alias)
                for tf in tfs:
                    tf_fname = fname if tf == "yesno" else f"{fname}_{tf}"
                    if not _allowed({fname.lower(), tf_fname.lower()}):
                        continue
                    m_full = _qualify_field_ref(tf_fname, view_alias)
                    tf_variant = "Yes / No" if tf == "yesno" else _titleize(tf)
                    short_lbl = fobj.label or (
                        f"{base_m_title} (Yes / No)"
                        if tf == "yesno"
                        else f"{base_m_title} {tf_variant}"
                    )
                    tf_type = "yesno" if tf == "yesno" else f"date_{tf}"
                    meas.append(
                        _mk(
                            category="measure",
                            ft=tf_type,
                            name=m_full,
                            short=short_lbl,
                            hidden=is_hidden or tf == "raw",
                            sql=fobj.sql or _default_table_sql(fname),
                            value_format=fobj.value_format,
                            value_format_name=fobj.value_format_name,
                            field_group_label=fg_label,
                            field_group_variant=tf_variant,
                            map_layer_name=fobj.map_layer_name,
                            filters=m_filters,
                            can_filter_override=fobj.can_filter,
                        )
                    )
                    view_set_fields.append(m_full)
                    if tf == "day_of_week" and "day_of_week_index" not in tfs:
                        view_set_fields.append(
                            _qualify_field_ref(f"{fname}_day_of_week_index", view_alias)
                        )
                continue

            if not _allowed({fname.lower()}):
                continue
            full_name = _qualify_field_ref(fname, view_alias)
            _record_aliases(fobj.alias, full_name)
            m_sug, m_enums, m_cases, m_tier_sql = (
                _build_tier_metadata(fobj)
                if fobj.case is not None
                else (
                    fobj.suggestions
                    if isinstance(fobj.suggestions, list)
                    else None,
                    None,
                    None,
                    None,
                )
            )
            eff_mtype = raw_mtype
            eff_sql = m_tier_sql if m_tier_sql is not None else fobj.sql
            if raw_mtype == "count" and is_symmetric_join:
                eff_mtype, eff_sql = "count_distinct", pk_sql
            elif is_symmetric_join and raw_mtype in (
                "sum",
                "average",
                "median",
                "percentile",
            ):
                eff_mtype = f"{raw_mtype}_distinct"
            elif raw_mtype == "list" and fobj.list_field:
                eff_sql = f"${{{fobj.list_field}::string}}"

            base_short = fobj.label or _titleize(fname.split(".", 1)[-1])
            if eff_mtype == "yesno":
                base_short = f"{base_short} (Yes / No)"
            meas.append(
                _mk(
                    category="measure",
                    ft=eff_mtype,
                    name=full_name,
                    short=base_short,
                    sql=eff_sql,
                    value_format=fobj.value_format,
                    value_format_name=fobj.value_format_name,
                    field_group_label=fobj.group_label,
                    field_group_variant=fobj.group_item_label or base_short,
                    map_layer_name=fobj.map_layer_name,
                    enumerations=m_enums,
                    suggestions=m_sug,
                    sql_case=m_cases,
                    filters=_extract_measure_filters(fobj.filters, view_alias),
                    can_filter_override=fobj.can_filter,
                )
            )
            view_set_fields.append(full_name)
            if fobj.case is not None and not fobj.alpha_sort:
                view_set_fields.append(f"{full_name}__sort_")

        elif ftype in ("filter", "parameter") and isinstance(
            fobj, (LookmlFilter, LookmlParameter)
        ):
            if not _allowed({fname.lower()}):
                continue
            full_name = _qualify_field_ref(fname, view_alias)
            base_short = fobj.label or _titleize(fname.split(".", 1)[-1])
            ptype = fobj.type or "string"
            esc = (
                (lambda v: v.replace("_", "^_"))
                if ptype in ("string", "unquoted")
                else (lambda v: v)
            )
            raw_avs = (
                fobj.allowed_value
                if isinstance(fobj, LookmlParameter)
                and isinstance(fobj.allowed_value, list)
                else (
                    [fobj.allowed_value]
                    if isinstance(fobj, LookmlParameter) and fobj.allowed_value
                    else []
                )
            )
            p_enums = [
                ApiLookmlModelExploreFieldEnumeration(
                    label=av.label if av.label is not None else av.value,
                    value=esc(av.value),
                )
                for av in raw_avs
                if isinstance(av, LookmlAllowedValue) and av.value is not None
            ]
            def_val = (
                esc(fobj.default_value) if fobj.default_value is not None else None
            )
            (filts if ftype == "filter" else params).append(
                _mk(
                    category=ftype,
                    ft=ptype,
                    name=full_name,
                    short=base_short,
                    sql=fobj.sql if isinstance(fobj, LookmlParameter) else None,
                    field_group_label=fobj.group_label,
                    field_group_variant=fobj.group_item_label or base_short,
                    default_filter_value=def_val,
                    has_allowed_values=bool(p_enums),
                    enumerations=p_enums or None,
                    suggestions=(
                        fobj.suggestions
                        if isinstance(fobj.suggestions, list)
                        else None
                    ),
                )
            )
            view_set_fields.append(full_name)

    return dims, meas, filts, params, view_set_fields, aliases


def _build_turtle_looks(
    exp_obj: LookmlExplore,
    exp_chain: list[tuple[str, Any, dict[str, Any]]],
    base_alias: str,
    project_name: str | None,
    fallback_file: str,
    fallback_line: int,
) -> list[ApiLookmlModelExploreTurtleLook]:
    raw_q = exp_obj.query
    if not raw_q or not isinstance(raw_q, dict):
        return []
    out: list[ApiLookmlModelExploreTurtleLook] = []
    for q_name, q_val in raw_q.items():
        if not isinstance(q_val, dict):
            continue
        _, _, q_file, q_line = _resolve_field_source(
            exp_chain, "query", q_name, fallback_file, fallback_line
        )
        dims = [
            _qualify_field_ref(str(d), base_alias)
            for d in (q_val.get("dimensions") or [])
        ]
        meas = [
            _qualify_field_ref(str(m), base_alias)
            for m in (q_val.get("measures") or [])
        ]
        pivots = [
            _qualify_field_ref(str(p), base_alias)
            for p in (q_val.get("pivots") or [])
        ]
        filters_dict: dict[str, str] = {}
        raw_filters = q_val.get("filters") or []
        for f_item in (
            raw_filters if isinstance(raw_filters, list) else [raw_filters]
        ):
            if isinstance(f_item, dict):
                for fk, fv in f_item.items():
                    if not fk.startswith("$"):
                        filters_dict[_qualify_field_ref(str(fk), base_alias)] = str(
                            fv
                        )
        sorts_list: list[dict[str, Any]] = []
        raw_sorts = q_val.get("sorts") or []
        for s_item in raw_sorts if isinstance(raw_sorts, list) else [raw_sorts]:
            if isinstance(s_item, dict):
                for sk, sv in s_item.items():
                    if not sk.startswith("$"):
                        sorts_list.append(
                            {
                                "field": _qualify_field_ref(str(sk), base_alias),
                                "desc": str(sv).lower() == "desc",
                            }
                        )
        lbl = q_val.get("label") or _titleize(q_name)
        can_turtle = len(dims) == 1 and len(meas) == 1 and not pivots
        out.append(
            ApiLookmlModelExploreTurtleLook(
                dimensions=dims,
                measures=meas,
                pivots=pivots,
                filters=filters_dict,
                limit=q_val.get("limit"),
                sorts=sorts_list,
                name=f"turtle::{q_name}",
                label=lbl,
                label_short=lbl,
                can_turtle=can_turtle,
                type="query",
                description=q_val.get("description"),
                lookml_link=_lookml_link(project_name, q_file, q_line),
            )
        )
    return out


def _build_explore_from_assembled(
    model_name: str,
    model_obj: LookmlModel,
    explore_name: str,
    exp_obj: LookmlExplore,
    view_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    view_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    project_name: str | None,
) -> ApiLookmlModelExplore:
    model_views = {
        k: v for k, v in (model_obj.view or {}).items() if isinstance(v, LookmlView)
    }
    exp_chain = _build_chain(explore_name, exp_base_decls, exp_ref_decls)
    base_view_name, base_alias, exp_file, exp_pos = _resolve_explore_base(
        explore_name, exp_obj, exp_chain, model_views
    )
    exp_line = int(exp_pos[0]) + 1 if exp_pos else 1

    views_by_alias: dict[str, LookmlView] = {}
    base_view = model_views.get(base_view_name)
    if isinstance(base_view, LookmlView):
        views_by_alias[base_alias] = base_view

    join_entries: list[tuple[str, LookmlJoin, str, LookmlView]] = []
    for j_name, j_obj in (exp_obj.join or {}).items():
        jv_name = j_obj.from_ or j_obj.view_name or j_name
        jv = model_views.get(jv_name)
        if isinstance(jv, LookmlView):
            views_by_alias[j_name] = jv
            join_entries.append((j_name, j_obj, jv_name, jv))

    all_dims: list[ApiLookmlModelExploreField] = []
    all_meas: list[ApiLookmlModelExploreField] = []
    all_filts: list[ApiLookmlModelExploreField] = []
    all_params: list[ApiLookmlModelExploreField] = []
    all_aliases: list[ApiLookmlModelExploreAlias] = []
    view_sets_by_alias: dict[str, list[str]] = {}

    if isinstance(base_view, LookmlView):
        b_chain = _build_chain(base_view_name, view_base_decls, view_ref_decls)
        b_vlabel = (
            exp_obj.view_label
            or base_view.view_label
            or base_view.label
            or _titleize(base_alias)
        )
        d, m, fl, pa, vset, al = _expand_view_for_explore(
            view_alias=base_alias,
            original_view_name=base_view_name,
            view_obj=base_view,
            view_chain=b_chain,
            default_view_label=b_vlabel,
            is_symmetric_join=False,
            explore_name=explore_name,
            explore_fields_spec=exp_obj.fields,
            join_fields_spec=None,
            views_by_alias=views_by_alias,
            base_alias=base_alias,
            project_name=project_name,
            model_obj=model_obj,
        )
        all_dims.extend(d)
        all_meas.extend(m)
        all_filts.extend(fl)
        all_params.extend(pa)
        all_aliases.extend(al)
        view_sets_by_alias[base_alias] = vset

    api_joins: list[ApiLookmlModelExploreJoins] = []
    for j_name, j_obj, jv_name, jv in join_entries:
        j_chain = _build_chain(jv_name, view_base_decls, view_ref_decls)
        j_vlabel = (
            j_obj.view_label
            or jv.view_label
            or jv.label
            or _titleize(j_name)
        )
        rel = j_obj.relationship or ""
        is_sym = (rel or "many_to_one") != "one_to_one"
        d, m, fl, pa, vset, al = _expand_view_for_explore(
            view_alias=j_name,
            original_view_name=jv_name,
            view_obj=jv,
            view_chain=j_chain,
            default_view_label=j_vlabel,
            is_symmetric_join=is_sym,
            explore_name=explore_name,
            explore_fields_spec=exp_obj.fields,
            join_fields_spec=j_obj.fields,
            views_by_alias=views_by_alias,
            base_alias=base_alias,
            project_name=project_name,
            model_obj=model_obj,
        )
        all_dims.extend(d)
        all_meas.extend(m)
        all_filts.extend(fl)
        all_params.extend(pa)
        all_aliases.extend(al)
        view_sets_by_alias[j_name] = vset

        dep_fields: list[str] = []
        for sql_snippet in (
            j_obj.sql_where,
            j_obj.sql_on,
            j_obj.sql,
            j_obj.sql_having,
            j_obj.foreign_key,
        ):
            for ref in _extract_lookml_refs(sql_snippet):
                dep_fields.append(_qualify_field_ref(ref, j_name))
            if sql_snippet is j_obj.foreign_key and sql_snippet and not _extract_lookml_refs(sql_snippet):
                dep_fields.append(_qualify_field_ref(sql_snippet, base_alias))

        api_joins.append(
            ApiLookmlModelExploreJoins(
                dependent_fields=dep_fields,
                fields=j_obj.fields,
                foreign_key=j_obj.foreign_key,
                from_=j_obj.from_,
                outer_only=j_obj.outer_only,
                relationship=rel,
                required_joins=j_obj.required_joins,
                sql_foreign_key=None,
                sql_on=j_obj.sql_on.lstrip(" ") if j_obj.sql_on else None,
                sql_table_name=j_obj.sql_table_name,
                type=j_obj.type,
                view_label=j_obj.view_label,
                name=j_name,
            )
        )

    for lst in (all_dims, all_meas, all_filts, all_params):
        lst.sort(key=lambda f: (f.view_label, f.label_short))
    all_aliases = sorted(
        {a.name: a for a in all_aliases}.values(), key=lambda a: a.name
    )

    scopes = list(
        dict.fromkeys(
            [
                explore_name,
                *(f.scope for f in (*all_dims, *all_meas, *all_filts, *all_params)),
                base_alias,
                *(j_name for j_name, _, _, _ in join_entries),
            ]
        )
    )

    # Sets: user-defined sets on [joins..., base_view], then view sets [joins..., base_view], then ALL_FIELDS
    sets_list: list[ApiLookmlModelExploreSet] = []
    view_order_for_sets = [*(j_name for j_name, _, _, _ in join_entries), base_alias]
    all_fields_flat = [
        f
        for v_alias in (base_alias, *(j_name for j_name, _, _, _ in join_entries))
        for f in view_sets_by_alias.get(v_alias, [])
    ]
    for v_alias in view_order_for_sets:
        v_obj = views_by_alias.get(v_alias)
        if not v_obj or not v_obj.set:
            continue
        for s_name, s_obj in v_obj.set.items():
            toks = _expand_field_tokens(s_obj.fields, views_by_alias, v_alias)
            excl = {
                f
                for op, a, fn in toks
                if op == "-"
                for f in (
                    all_fields_flat
                    if (a, fn) == ("*", "*")
                    else view_sets_by_alias.get(a, [])
                    if fn == "*"
                    else [f"{a}.{fn}"]
                )
            }
            sets_list.append(
                ApiLookmlModelExploreSet(
                    name=f"{v_alias}.{s_name}",
                    value=list(
                        dict.fromkeys(
                            f
                            for op, a, fn in toks
                            if op == "+"
                            for f in (
                                all_fields_flat
                                if (a, fn) == ("*", "*")
                                else view_sets_by_alias.get(a, [])
                                if fn == "*"
                                else [f"{a}.{fn}"]
                            )
                            if f not in excl
                        )
                    ),
                )
            )
    for v_alias in view_order_for_sets:
        if v_alias in view_sets_by_alias:
            sets_list.append(
                ApiLookmlModelExploreSet(
                    name=v_alias,
                    value=view_sets_by_alias[v_alias],
                )
            )
    sets_list.append(
        ApiLookmlModelExploreSet(name="ALL_FIELDS", value=all_fields_flat)
    )

    raw_tbl = (
        exp_obj.sql_table_name
        or (base_view.sql_table_name if isinstance(base_view, LookmlView) else None)
    )
    sql_table_name = (
        f"{raw_tbl.strip()}  AS {base_alias}" if raw_tbl else None
    )

    model_label = model_obj.label or _titleize(model_name)
    exp_label = (
        exp_obj.label
        or (base_view.label if isinstance(base_view, LookmlView) else None)
        or _titleize(explore_name)
    )

    turtle_looks = _build_turtle_looks(
        exp_obj, exp_chain, base_alias, project_name, exp_file, exp_line
    )

    cond_filters = [
        {"name": f.field, "value": f.condition}
        for f in (
            _extract_measure_filters(
                (exp_obj.conditionally_filter or {}).get("filters"), base_alias
            )
            or []
        )
    ]
    index_fields: list[str] = []
    if exp_obj.conditionally_filter:
        raw_unless = exp_obj.conditionally_filter.get("unless") or []
        unless_fields = [
            _qualify_field_ref(str(u), base_alias)
            for u in (raw_unless if isinstance(raw_unless, list) else [raw_unless])
            if u
        ]
        dims_by_name = {d.name: d for d in all_dims}
        for u_f in unless_fields:
            if u_f in dims_by_name or not any(
                d.dimension_group == u_f for d in all_dims
            ):
                index_fields.append(u_f)
        for ref_f in [*unless_fields, *(cf["name"] for cf in cond_filters)]:
            d_match = dims_by_name.get(ref_f)
            dg_id = d_match.dimension_group if d_match is not None else ref_f
            if dg_id:
                index_fields.extend(
                    sorted(
                        d.name
                        for d in all_dims
                        if d.dimension_group == dg_id and d.type != "date_raw"
                    )
                )
        index_fields = list(dict.fromkeys(index_fields))

    return ApiLookmlModelExplore(
        id=f"{model_name}::{explore_name}",
        name=explore_name,
        description=exp_obj.description,
        scopes=scopes,
        connection_name=model_obj.connection,
        source_file=Path(exp_file).name if exp_file else f"{model_name}.model.lkml",
        model_name=model_name,
        view_name=base_alias,
        hidden=bool(exp_obj.hidden),
        sql_table_name=sql_table_name,
        aliases=all_aliases,
        always_filter=[
            {"name": f.field, "value": f.condition}
            for f in (
                _extract_measure_filters(
                    (exp_obj.always_filter or {}).get("filters"), base_alias
                )
                or []
            )
        ],
        conditionally_filter=cond_filters,
        index_fields=index_fields,
        sets=sets_list,
        tags=list(exp_obj.tags or []),
        fields=ApiLookmlModelExploreFieldset(
            dimensions=all_dims,
            measures=all_meas,
            filters=all_filts,
            parameters=all_params,
        ),
        joins=api_joins,
        group_label=exp_obj.group_label or model_label,
        always_join=list(exp_obj.always_join or []),
        label=exp_label,
        project_name=project_name,
        title=exp_label,
        lookml_link=_lookml_link(project_name, exp_file, exp_line),
        turtle_looks=turtle_looks,
    )


def lookml_to_all_lookml_models(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    *,
    project: LookmlProject | None = None,
    model: str | None = None,
) -> list[ApiLookmlModel]:
    """Generate the `all_lookml_models` SDK payload from LookML."""
    proj = (
        project.with_defaults()
        if project
        else parse_lookml(path=path, file=file, lookml=lookml).apply_defaults()
    )
    project_name = _resolve_project_name(proj)
    out: list[ApiLookmlModel] = []

    for m_name, m_obj in (proj.model or {}).items():
        if model and m_name != model:
            continue
        m_label = m_obj.label or _titleize(m_name)
        m_views = m_obj.view or {}
        nav_explores: list[ApiLookmlModelNavExplore] = []
        for e_name in _ordered_model_explore_names(m_name, m_obj, proj):
            e_obj = (m_obj.explore or {}).get(e_name)
            if not isinstance(e_obj, LookmlExplore):
                continue
            bv_name = e_obj.from_ or e_obj.view_name or e_name
            bv = m_views.get(bv_name)
            e_label = (
                e_obj.label
                or (bv.label if isinstance(bv, LookmlView) else None)
                or _titleize(e_name)
            )
            nav_explores.append(
                ApiLookmlModelNavExplore(
                    description=e_obj.description,
                    label=e_label,
                    hidden=bool(e_obj.hidden),
                    group_label=e_obj.group_label or m_label,
                    name=e_name,
                )
            )
        out.append(
            ApiLookmlModel(
                has_content=bool(nav_explores),
                label=m_label,
                name=m_name,
                project_name=project_name,
                unlimited_db_connections=False,
                allowed_db_connection_names=(
                    [m_obj.connection] if m_obj.connection else []
                ),
                explores=nav_explores,
            )
        )
    return out


def lookml_to_lookml_model_explore(
    model: str,
    explore: str,
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    *,
    project: LookmlProject | None = None,
) -> ApiLookmlModelExplore:
    """Generate the `lookml_model_explore` SDK payload for `<model>::<explore>` from LookML."""
    proj = (
        project.with_defaults()
        if project
        else parse_lookml(path=path, file=file, lookml=lookml).apply_defaults()
    )
    models = proj.model or {}
    m_obj = models.get(model)
    if m_obj is None and len(models) == 1 and "inline" in models:
        m_obj = models["inline"]
    if m_obj is None:
        raise ValueError(f"LookML model not found: {model}")

    exp_obj = (m_obj.explore or {}).get(explore)
    if not isinstance(exp_obj, LookmlExplore):
        raise ValueError(f"LookML explore '{explore}' not found in model '{model}'")

    view_base_decls, view_ref_decls = _collect_declarations(proj, "view", LookmlView)
    exp_base_decls, exp_ref_decls = _collect_declarations(
        proj, "explore", LookmlExplore
    )
    project_name = _resolve_project_name(proj)
    return _build_explore_from_assembled(
        model,
        m_obj,
        explore,
        exp_obj,
        view_base_decls,
        view_ref_decls,
        exp_base_decls,
        exp_ref_decls,
        project_name,
    )


def parse_lookml_to_api(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    *,
    model: str | None = None,
    explore: str | None = None,
    project: LookmlProject | None = None,
) -> LookmlToApiResult:
    """Parse LookML and build both `all_lookml_models` and `lookml_model_explores` API payloads."""
    proj = (
        project.with_defaults()
        if project
        else parse_lookml(path=path, file=file, lookml=lookml).apply_defaults()
    )
    all_models = lookml_to_all_lookml_models(project=proj, model=model)
    view_base_decls, view_ref_decls = _collect_declarations(proj, "view", LookmlView)
    exp_base_decls, exp_ref_decls = _collect_declarations(
        proj, "explore", LookmlExplore
    )
    project_name = _resolve_project_name(proj)

    explores_map: dict[str, ApiLookmlModelExplore] = {}
    for m_name, m_obj in (proj.model or {}).items():
        if model and m_name != model:
            continue
        for e_name in _ordered_model_explore_names(m_name, m_obj, proj):
            if explore and e_name != explore:
                continue
            e_obj = (m_obj.explore or {}).get(e_name)
            if not isinstance(e_obj, LookmlExplore):
                continue
            explores_map[f"{m_name}::{e_name}"] = _build_explore_from_assembled(
                m_name,
                m_obj,
                e_name,
                e_obj,
                view_base_decls,
                view_ref_decls,
                exp_base_decls,
                exp_ref_decls,
                project_name,
            )

    return LookmlToApiResult(
        all_lookml_models=all_models,
        lookml_model_explores=explores_map,
    )
