from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lkr.parse.sql import ParsedQuery


# LookML to API models
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


# SQL to LookML comparison models
class LookmlSourceLocation(BaseModel):
    file: str
    line: int
    end_line: int
    position: list[int]


class LookmlExploreFieldMatch(BaseModel):
    model_name: str
    explore_name: str
    field: str
    view_alias: str
    view_name: str
    join_name: str | None = None
    file: str
    line: int
    end_line: int
    position: list[int]
    join_location: LookmlSourceLocation | None = None


class LookmlTestMatch(BaseModel):
    model_name: str
    test_name: str
    explore_name: str
    field: str
    file: str
    line: int
    end_line: int
    position: list[int]
    fields: list[str] = Field(default_factory=list)


class LookmlFieldMatch(BaseModel):
    sql_column: str
    field_type: str
    field_name: str
    sql: str | None = None
    via: list[str] = Field(default_factory=list)
    file: str
    line: int
    end_line: int
    position: list[int]
    sql_location: LookmlSourceLocation | None = None
    explores: list[LookmlExploreFieldMatch] = Field(default_factory=list)
    tests: list[LookmlTestMatch] = Field(default_factory=list)


class LookmlViewMatch(BaseModel):
    sql_table: str
    view_name: str
    sql_table_name: str | None = None
    model_name: str | None = None
    file: str
    line: int
    end_line: int
    position: list[int]
    sql_table_name_location: LookmlSourceLocation | None = None
    fields: list[LookmlFieldMatch] = Field(default_factory=list)
    unmodeled_db_columns: list[str] = Field(default_factory=list)
    missing_db_columns: list[str] = Field(default_factory=list)


class QueryLookmlMapping(BaseModel):
    raw_sql: str
    parsed_query: ParsedQuery
    views: list[LookmlViewMatch] = Field(default_factory=list)
    explores: list[LookmlExploreFieldMatch] = Field(default_factory=list)
    tests: list[LookmlTestMatch] = Field(default_factory=list)


class SqlToLookmlResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    doc_: dict[str, str] | None = Field(default=None, alias="_doc")
    queries: list[QueryLookmlMapping] = Field(default_factory=list)
    dialect: str | None = None

    @property
    def doc(self) -> dict[str, str] | None:
        return self.doc_


# Alias SqlLookmlCompareResult to SqlToLookmlResult
SqlLookmlCompareResult = SqlToLookmlResult

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
    "LookmlExploreFieldMatch",
    "LookmlFieldMatch",
    "LookmlSourceLocation",
    "LookmlTestMatch",
    "LookmlToApiResult",
    "LookmlViewMatch",
    "QueryLookmlMapping",
    "SqlLookmlCompareResult",
    "SqlToLookmlResult",
]
