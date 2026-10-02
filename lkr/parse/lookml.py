import json
from pathlib import Path
from typing import Any, Self

import nodejs_wheel
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

LOOKML_PARSER_VERSION = "9.0.0"
LOOKML_CACHE_DIR = Path.home() / ".lkr" / "lookml-parser"

DEFAULT_TIMEFRAMES: tuple[str, ...] = (
    "date",
    "day_of_month",
    "day_of_week",
    "day_of_week_index",
    "day_of_year",
    "hour",
    "hour_of_day",
    "minute",
    "month",
    "month_num",
    "month_name",
    "quarter",
    "quarter_of_year",
    "raw",
    "time",
    "time_of_day",
    "week",
    "week_of_year",
    "year",
)

DEFAULT_DURATION_INTERVALS: tuple[str, ...] = (
    "year",
    "quarter",
    "month",
    "week",
    "day",
    "hour",
    "minute",
    "second",
)


def _default_table_sql(name: str) -> str:
    col = f"`{name}`" if "." in name else name
    return f"${{TABLE}}.{col}"


class _LookmlBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def apply_defaults(self) -> Self:
        return self

    def with_defaults(self) -> Self:
        return self.model_copy(deep=True).apply_defaults()


class LookmlPosition(_LookmlBase):
    p: tuple[int, int, int, int] | list[int] | None = Field(default=None, alias="$p")


class LookmlViewPositions(LookmlPosition):
    type_: LookmlPosition | None = Field(default=None, alias="$type")
    name_: LookmlPosition | None = Field(default=None, alias="$name")
    sql_table_name: LookmlPosition | None = None
    drill_fields: dict[str, Any] | LookmlPosition | None = None
    set: dict[str, Any] | LookmlPosition | None = None
    dimension: dict[str, Any] | LookmlPosition | None = None
    dimension_group: dict[str, Any] | LookmlPosition | None = None
    measure: dict[str, Any] | LookmlPosition | None = None
    derived_table: dict[str, Any] | LookmlPosition | None = None


class LookmlPositions(_LookmlBase):
    file: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)


class LookmlParserValues(_LookmlBase):
    name_: str | None = Field(default=None, alias="$name")
    type_: str | None = Field(default=None, alias="$type")
    strings_: Any = Field(default=None, alias="$strings")


class LookmlFileAttributes(LookmlParserValues):
    file_name: str | list[str] | None = Field(default=None, alias="$file_name")
    file_path: str | list[str] | None = Field(default=None, alias="$file_path")
    file_rel: str | list[str] | None = Field(default=None, alias="$file_rel")
    file_type: str | list[str] | None = Field(default=None, alias="$file_type")


class LookmlLink(LookmlParserValues):
    label: str | None = None
    icon_url: str | None = None
    url: str | None = None


class LookmlActionOption(_LookmlBase):
    name: str | None = None


class LookmlActionParam(_LookmlBase):
    name: str | None = None
    value: str | None = None
    required: bool | None = None
    default: str | None = None
    type: str | None = None
    option: LookmlActionOption | list[LookmlActionOption] | dict[str, Any] | None = None


class LookmlAction(_LookmlBase):
    label: str | None = None
    url: str | None = None
    icon_url: str | None = None
    param: LookmlActionParam | list[LookmlActionParam] | dict[str, Any] | None = None
    form_param: LookmlActionParam | list[LookmlActionParam] | dict[str, Any] | None = (
        None
    )


class LookmlCaseWhen(_LookmlBase):
    label: str | None = None
    sql: str | None = None


class LookmlCase(LookmlParserValues):
    when: LookmlCaseWhen | list[LookmlCaseWhen] | None = None
    else_: str | dict[str, Any] | None = Field(default=None, alias="else")


class LookmlAllowedValue(_LookmlBase):
    label: str | None = None
    value: str | None = None


class LookmlFieldProperties(LookmlParserValues):
    _sql_defaulted: bool = PrivateAttr(default=False)

    alias: list[str] | str | None = None
    allow_fill: bool | None = None
    alpha_sort: bool | None = None
    allow_approximate_optimization: bool | None = None
    approximate: bool | None = None
    approximate_threshold: int | float | None = None
    case: LookmlCase | None = None
    fanout_on: str | None = None
    map_layer_name: str | None = None
    precision: int | None = None
    primary_key: bool | None = None
    required_access_grants: list[str] | None = None
    sql_distinct_key: str | None = None
    direction: str | None = None
    end_location_field: str | None = None
    list_field: str | None = None
    start_location_field: str | None = None
    description: str | None = None
    full_suggestions: bool | None = None
    group_item_label: str | None = None
    group_label: str | None = None
    hidden: bool | None = None
    html: str | None = None
    label_from_parameter: str | None = None
    label: str | None = None
    order_by_field: str | None = None
    required_fields: list[str] | None = None
    style: str | None = None
    suggest_dimension: str | None = None
    suggest_explore: str | None = None
    suggest_persist_for: str | None = None
    suggestable: bool | None = None
    suggestions: str | list[str] | bool | None = None
    synonyms: list[str] | str | None = None
    tags: list[str] | None = None
    timeframes: list[str] | None = None
    units: str | None = None
    default_value: str | None = None
    value_format_name: str | None = None
    view_label: str | None = None
    can_filter: bool | None = None
    case_sensitive: bool | None = None
    skip_drill_filter: bool | None = None
    bypass_suggest_restrictions: bool | None = None


class LookmlParameter(LookmlFieldProperties):
    type: str | None = None
    allowed_value: (
        LookmlAllowedValue | list[LookmlAllowedValue] | dict[str, Any] | None
    ) = None
    sql: str | None = None

    def apply_defaults(self) -> Self:
        if self.type is None:
            self.type = "string"
        return self


class LookmlFilter(LookmlFieldProperties):
    type: str | None = None
    field: str | list[str | None] | None = None
    value: str | list[str | None] | None = None

    def apply_defaults(self) -> Self:
        if self.type is None and self.name_:
            self.type = "string"
        return self


class LookmlDimension(LookmlFieldProperties):
    action: LookmlAction | list[LookmlAction] | None = None
    bins: list[Any] | None = None
    drill_fields: list[str | None] | None = None
    link: LookmlLink | list[LookmlLink] | None = None
    sql_end: str | None = None
    sql_latitude: str | None = None
    sql_longitude: str | None = None
    sql_start: str | None = None
    sql: str | None = None
    tier: str | list[Any] | None = None
    tiers: list[Any] | None = None
    type: str | None = None
    value_format: str | None = None

    def apply_defaults(self) -> Self:
        if self.type is None:
            self.type = "string"
        elif self.type == "bin":
            self.type = "tier"
        if self.tiers is None and self.bins is not None:
            self.tiers = self.bins
        if (
            self.sql is None
            and self.case is None
            and self.name_
            and self.type not in ("location", "distance")
            and not self.type.startswith("duration_")
        ):
            self.sql = _default_table_sql(self.name_)
            self._sql_defaulted = True
        return self


class LookmlDimensionGroup(LookmlFieldProperties):
    type: str | None = None
    sql: str | None = None
    datatype: str | None = None
    convert_tz: bool | None = None
    sql_start: str | None = None
    sql_end: str | None = None
    intervals: list[str] | None = None
    string_datatype: str | None = None
    value_format: str | None = None

    def apply_defaults(self) -> Self:
        if self.type is None:
            self.type = "time"
        if self.sql is None and self.name_ and self.type != "duration":
            self.sql = _default_table_sql(self.name_)
            self._sql_defaulted = True
        if self.type == "time" and self.timeframes is None:
            self.timeframes = list(DEFAULT_TIMEFRAMES)
        if self.type == "duration" and self.intervals is None:
            self.intervals = list(DEFAULT_DURATION_INTERVALS)
        return self


class LookmlMeasure(LookmlFieldProperties):
    drill_fields: list[str | None] | None = None
    filters: (
        LookmlFilter
        | list[LookmlFilter | dict[str, Any] | None]
        | dict[str, Any]
        | None
    ) = None
    link: LookmlLink | list[LookmlLink] | None = None
    percentile: str | int | float | None = None
    sql: str | None = None
    type: str | None = None
    value_format: str | None = None

    def apply_defaults(self) -> Self:
        if self.type is None:
            self.type = "string"
        if self.type == "time" and self.timeframes is None:
            self.timeframes = list(DEFAULT_TIMEFRAMES)
        if (
            self.sql is None
            and self.case is None
            and self.name_
            and self.type not in ("count", "list")
        ):
            self.sql = _default_table_sql(self.name_)
            self._sql_defaulted = True
        return self


class LookmlSet(LookmlParserValues):
    fields: list[str] = Field(default_factory=list)


class LookmlJoin(LookmlParserValues):
    fields: list[str] | None = None
    foreign_key: str | None = None
    from_: str | None = Field(default=None, alias="from")
    outer_only: bool | None = None
    relationship: str | None = None
    relationship_type: str | None = None
    required_joins: list[str] | None = None
    sql_having: str | None = None
    sql_on: str | None = None
    sql_table_name: str | None = None
    sql_where: str | None = None
    sql: str | None = None
    type: str | None = None
    view: str | None = None
    view_name: str | None = None
    view_label: str | None = None
    tags: list[str] | None = None

    def apply_defaults(self) -> Self:
        if not self.relationship and self.sql_on and self.type != "inner":
            self.relationship = "many_to_one"
        if self.type is None and self.sql_on:
            self.type = "left_outer"
        return self


class LookmlAggregateTable(LookmlParserValues):
    query: dict[str, Any] | list[dict[str, Any]] | None = None
    materialization: dict[str, Any] | list[dict[str, Any]] | None = None


class LookmlExploreSourceColumn(LookmlParserValues):
    field: str | None = None


class LookmlExploreSourceDerivedColumn(LookmlParserValues):
    sql: str | None = None


class LookmlExploreSourceBindFilters(LookmlParserValues):
    from_field: str | None = None
    to_field: str | None = None


class LookmlExploreSource(LookmlParserValues):
    column: dict[str, LookmlExploreSourceColumn] | None = None
    derived_column: dict[str, LookmlExploreSourceDerivedColumn] | None = None
    bind_filters: (
        dict[str, LookmlExploreSourceBindFilters]
        | list[LookmlExploreSourceBindFilters]
        | LookmlExploreSourceBindFilters
        | None
    ) = None
    bind_all_filters: bool | None = None
    filters: (
        LookmlFilter
        | list[LookmlFilter | dict[str, Any] | None]
        | dict[str, Any]
        | None
    ) = None
    sort: list[dict[str, Any]] | dict[str, Any] | None = None
    sorts: list[dict[str, Any]] | dict[str, Any] | None = None
    expression_custom_filter: str | None = None
    limit: int | str | None = None
    timezone: str | None = None


class LookmlTestAssert(LookmlParserValues):
    expression: str | None = None


class LookmlTest(LookmlParserValues):
    explore_source: dict[str, LookmlExploreSource] | LookmlExploreSource | None = None
    assert_: dict[str, LookmlTestAssert] | list[LookmlTestAssert] | None = Field(
        default=None, alias="assert"
    )


class LookmlDerivedTable(_LookmlBase):
    cluster_keys: list[str] | None = None
    create_process: dict[str, Any] | None = None
    datagroup_trigger: str | None = None
    distribution: str | None = None
    distribution_style: str | None = None
    explore_source: (
        str | dict[str, LookmlExploreSource | Any] | LookmlExploreSource | None
    ) = None
    increment_key: str | None = None
    increment_offset: int | None = None
    indexes: list[str] | None = None
    interval_trigger: str | None = None
    materialized_view: bool | None = None
    partition_keys: list[str] | None = None
    persist_for: str | None = None
    persist_with: str | None = None
    publish_as_db_view: bool | None = None
    sortkeys: list[str] | None = None
    sql: str | None = None
    sql_create: str | dict[str, Any] | None = None
    sql_trigger_value: str | None = None
    table_compression: str | None = None
    table_format: str | None = None


class LookmlView(LookmlParserValues):
    access_filter: dict[str, Any] | list[dict[str, Any]] | None = None
    derived_table: LookmlDerivedTable | dict[str, Any] | None = None
    description: str | None = None
    dimension_group: dict[str, LookmlDimensionGroup] | None = None
    dimension: dict[str, LookmlDimension] | None = None
    drill_fields: list[str | None] | None = None
    extends_ref: str | None = None
    extends: str | list[str] | None = None
    extension: str | bool | None = None
    fields_hidden_by_default: bool | None = None
    filter: (
        dict[str, LookmlFilter] | LookmlFilter | list[LookmlFilter | None] | None
    ) = None
    hidden: bool | None = None
    label: str | None = None
    measure: dict[str, LookmlMeasure] | None = None
    parameter: dict[str, LookmlParameter] | None = None
    persist_for: str | None = None
    persist_with: str | None = None
    relationship: str | None = None
    required_access_grants: list[str] | None = None
    required: bool | None = None
    set: dict[str, LookmlSet] | None = None
    sql_always_having: str | None = None
    sql_always_where: str | None = None
    sql_on: str | None = None
    sql_table_name: str | None = None
    suggestions: bool | None = None
    tags: list[str] | None = None
    timezone: str | None = None
    view_label: str | None = None

    def apply_defaults(self) -> Self:
        for d in (self.dimension or {}).values():
            d.apply_defaults()
        for dg in (self.dimension_group or {}).values():
            dg.apply_defaults()
        for m in (self.measure or {}).values():
            m.apply_defaults()
        if isinstance(self.filter, dict):
            for f in self.filter.values():
                f.apply_defaults()
        for p in (self.parameter or {}).values():
            p.apply_defaults()
        return self


class LookmlExplore(LookmlParserValues):
    extension: str | bool | None = None
    extends: str | list[str] | None = None
    fields: list[str] | None = None
    tags: list[str] | None = None
    description: str | None = None
    group_label: str | None = None
    hidden: bool | None = None
    label: str | None = None
    query: dict[str, Any] | list[dict[str, Any]] | None = None
    view_label: str | None = None
    access_filter: dict[str, Any] | list[dict[str, Any]] | None = None
    always_filter: dict[str, Any] | None = None
    conditionally_filter: dict[str, Any] | None = None
    case_sensitive: bool | None = None
    sql_always_having: str | None = None
    sql_always_where: str | None = None
    always_join: list[str] | None = None
    join: dict[str, LookmlJoin] | None = None
    cancel_grouping_fields: list[str] | None = None
    from_: str | None = Field(default=None, alias="from")
    persist_for: str | None = None
    persist_with: str | None = None
    required_access_grants: list[str] | None = None
    sql_table_name: str | None = None
    symmetric_aggregates: bool | None = None
    view_name: str | None = None
    aggregate_table: dict[str, LookmlAggregateTable] | None = None

    def apply_defaults(self) -> Self:
        for j in (self.join or {}).values():
            j.apply_defaults()
        return self


class LookmlConstant(LookmlParserValues):
    value: str | None = None


class LookmlVisualization(LookmlParserValues):
    id: str | None = None
    label: str | None = None
    file: str | None = None
    url: str | None = None
    sri_hash: str | None = None
    dependencies: list[str] | None = None


class LookmlManifest(LookmlFileAttributes):
    project_name: str | None = None
    application: Any = None
    includes: list[str] | None = None
    timezone: str | None = None
    constant: dict[str, LookmlConstant] | None = None
    visualization: list[LookmlVisualization] | dict[str, LookmlVisualization] | None = (
        None
    )


class LookmlDashboard(LookmlFileAttributes):
    title: str | None = None
    label: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class LookmlNamedValueFormat(LookmlParserValues):
    value_format: str | None = None
    strict_value_format: bool | None = None


class LookmlMapLayer(LookmlParserValues):
    extents_json_url: str | None = None
    feature_key: str | None = None
    file: str | None = None
    format: str | None = None
    label: str | None = None
    max_zoom_level: int | None = None
    min_zoom_level: int | None = None
    projection: str | None = None
    property_key: str | None = None
    property_label_key: str | None = None
    url: str | None = None


class LookmlModel(LookmlFileAttributes):
    connection: str | None = None
    label: str | None = None
    fiscal_month_offset: int | None = None
    week_start_day: str | None = None
    include: str | list[str] | None = None
    explore: dict[str, LookmlExplore | list[LookmlExplore]] | None = None
    view: dict[str, LookmlView | list[LookmlView]] | None = None
    test: dict[str, LookmlTest | list[LookmlTest]] | None = None
    named_value_format: dict[str, LookmlNamedValueFormat] | None = None
    map_layer: dict[str, LookmlMapLayer] | None = None
    extension: str | bool | None = None
    tags: list[str] | None = None

    def apply_defaults(self) -> Self:
        for v in (self.view or {}).values():
            if isinstance(v, LookmlView):
                v.apply_defaults()
        for e in (self.explore or {}).values():
            if isinstance(e, LookmlExplore):
                e.apply_defaults()
        return self


class LookmlFileEntry(LookmlFileAttributes):
    view: dict[str, LookmlView | list[LookmlView]] | None = None
    explore: dict[str, LookmlExplore | list[LookmlExplore]] | None = None
    model: dict[str, LookmlModel] | None = None
    test: dict[str, LookmlTest | list[LookmlTest]] | None = None
    manifest: dict[str, LookmlManifest] | LookmlManifest | None = None
    dashboard: dict[str, LookmlDashboard] | None = None


class LookmlFile(_LookmlBase):
    view: dict[str, LookmlFileEntry] | None = None
    model: dict[str, LookmlModel | LookmlFileEntry] | None = None
    explore: dict[str, LookmlFileEntry] | None = None
    manifest: dict[str, LookmlFileEntry] | LookmlManifest | None = None
    dashboard: dict[str, LookmlFileEntry] | None = None


class LookmlError(LookmlFileAttributes):
    error: dict[str, Any] | None = None
    message: str | None = None
    code: int | str | None = None


class LookmlProject(_LookmlBase):
    errors: list[LookmlError] | None = None
    file: LookmlFile | dict[str, Any] | None = None
    model: dict[str, LookmlModel] | None = None
    manifest: LookmlManifest | None = None
    positions: LookmlPositions | None = None

    def apply_defaults(self) -> Self:
        for m in (self.model or {}).values():
            m.apply_defaults()
        return self


def _ensure_lookml_parser(version: str = LOOKML_PARSER_VERSION) -> Path:
    LOOKML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mod_dir = LOOKML_CACHE_DIR / "node_modules" / "lookml-parser"
    pkg_json = mod_dir / "package.json"
    if (
        not pkg_json.exists()
        or f'"version": "{version}"' not in pkg_json.read_text(encoding="utf-8")
    ):
        nodejs_wheel.npm(
            [
                "i",
                "--prefix",
                str(LOOKML_CACHE_DIR),
                f"lookml-parser@{version}",
                "--no-audit",
                "--no-fund",
            ],
            return_completed_process=True,
            capture_output=True,
            text=True,
            check=True,
        )
    return mod_dir


def parse_lookml(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
) -> LookmlProject:
    """Parse LookML from --path, --file, or --lookml with modelAssembly, extensions/refinements, and positions."""
    provided = sum(x is not None for x in (path, file, lookml))
    if provided != 1:
        raise ValueError("Specify exactly one of 'path', 'file', or 'lookml'")

    mod_dir = _ensure_lookml_parser()
    opts: dict[str, Any] = {}

    if lookml is not None:
        opts["input"] = [{"path": "inline.model.lkml", "content": lookml}]
    elif file is not None:
        fpath = Path(file).resolve()
        if fpath.name.endswith(".model.lkml"):
            opts["cwd"] = str(fpath.parent)
            opts["source"] = fpath.name
        else:
            content = fpath.read_text(encoding="utf-8")
            opts["input"] = [
                {"path": fpath.name, "content": content},
                {
                    "path": "inline.model.lkml",
                    "content": f'include: "{fpath.name}"',
                },
            ]
    elif path is not None:
        root = Path(path).resolve()
        if root.is_file():
            return parse_lookml(file=root)
        if any(root.rglob("*.model.lkml")):
            opts["cwd"] = str(root)
        else:
            files_input = [
                {
                    "path": f.relative_to(root).as_posix(),
                    "content": f.read_text(encoding="utf-8"),
                }
                for f in sorted(root.rglob("*.lkml"))
                if f.is_file()
            ]
            files_input.append(
                {"path": "inline.model.lkml", "content": 'include: "**/*.lkml"'}
            )
            opts["input"] = files_input

    js_code = f"""
const lp = require({json.dumps(str(mod_dir))});
const opts = JSON.parse(require("fs").readFileSync(0, "utf-8"));
lp.parseFiles({{
  ...opts,
  modelAssembly: true,
  extensions: true,
  positions: true,
  strings: true,
  legacyFileMetadata: true,
  fileOutput: "by-type",
  console: []
}}).then(p => process.stdout.write(JSON.stringify(p))).catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    proc = nodejs_wheel.node(
        ["-e", js_code],
        return_completed_process=True,
        input=json.dumps(opts),
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout if isinstance(proc.stdout, str) else proc.stdout.decode("utf-8")
    return LookmlProject.model_validate_json(out)
