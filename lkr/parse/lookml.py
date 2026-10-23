import json
import os
from pathlib import Path
from typing import Annotated, Any, Self

import nodejs_wheel
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr

_StrList = Annotated[
    list[str],
    BeforeValidator(
        lambda v: [x for x in v if x is not None] if isinstance(v, list) else v
    ),
]

LOOKML_PARSER_VERSION = "9.0.0"
LOOKML_CACHE_DIR = Path(
    os.getenv("LKR_CACHE_DIR", Path.home() / ".lkr" / "lookml-parser")
)

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

    alias: _StrList | str | None = None
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
    required_access_grants: _StrList | None = None
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
    required_fields: _StrList | None = None
    style: str | None = None
    suggest_dimension: str | None = None
    suggest_explore: str | None = None
    suggest_persist_for: str | None = None
    suggestable: bool | None = None
    suggestions: str | _StrList | bool | None = None
    synonyms: _StrList | str | None = None
    tags: _StrList | None = None
    timeframes: _StrList | None = None
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
    sql: str | None = None

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
    intervals: _StrList | None = None
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
    fields: _StrList = Field(default_factory=list)


class LookmlJoin(LookmlParserValues):
    fields: _StrList | None = None
    foreign_key: str | None = None
    from_: str | None = Field(default=None, alias="from")
    outer_only: bool | None = None
    relationship: str | None = None
    relationship_type: str | None = None
    required_joins: _StrList | None = None
    sql_foreign_key: str | None = None
    sql_having: str | None = None
    sql_on: str | None = None
    sql_table_name: str | None = None
    sql_where: str | None = None
    sql: str | None = None
    type: str | None = None
    view: str | None = None
    view_name: str | None = None
    view_label: str | None = None
    tags: _StrList | None = None

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
    explore_source: dict[str, LookmlExploreSource] | LookmlExploreSource | None = None
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
    extends: str | _StrList | None = None
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
    required_access_grants: _StrList | None = None
    required: bool | None = None
    set: dict[str, LookmlSet] | None = None
    sql_always_having: str | None = None
    sql_always_where: str | None = None
    sql_on: str | None = None
    sql_table_name: str | None = None
    suggestions: bool | None = None
    tags: _StrList | None = None
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
    extends: str | _StrList | None = None
    fields: _StrList | None = None
    tags: _StrList | None = None
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
    always_join: _StrList | None = None
    join: dict[str, LookmlJoin] | None = None
    cancel_grouping_fields: _StrList | None = None
    from_: str | None = Field(default=None, alias="from")
    persist_for: str | None = None
    persist_with: str | None = None
    required_access_grants: _StrList | None = None
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
    export: str | None = None


class LookmlLocalDependency(LookmlParserValues):
    project: str | None = None
    override_constant: dict[str, LookmlConstant] | None = None


class LookmlRemoteDependency(LookmlParserValues):
    url: str | None = None
    ref: str | None = None
    override_constant: dict[str, LookmlConstant] | None = None


class LookmlVisualization(LookmlParserValues):
    id: str | None = None
    label: str | None = None
    file: str | None = None
    url: str | None = None
    sri_hash: str | None = None
    dependencies: list[str] | None = None


class LookmlLocalizationSettings(_LookmlBase):
    default_locale: str | None = None
    localization_level: str | None = None
    import_locale_defs: bool | str | None = None


class LookmlManifest(LookmlFileAttributes):
    project_name: str | None = None
    application: Any = None
    includes: list[str] | None = None
    timezone: str | None = None
    constant: dict[str, LookmlConstant] | None = None
    local_dependency: (
        LookmlLocalDependency
        | list[LookmlLocalDependency]
        | dict[str, LookmlLocalDependency]
        | None
    ) = None
    remote_dependency: (
        dict[str, LookmlRemoteDependency]
        | LookmlRemoteDependency
        | list[LookmlRemoteDependency]
        | None
    ) = None
    visualization: list[LookmlVisualization] | dict[str, LookmlVisualization] | None = (
        None
    )
    localization_settings: LookmlLocalizationSettings | dict[str, Any] | None = None


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


class LookmlDatagroup(LookmlParserValues):
    sql_trigger: str | None = None
    interval_trigger: str | None = None
    max_cache_age: str | None = None
    label: str | None = None
    description: str | None = None


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
    datagroup: dict[str, LookmlDatagroup | list[LookmlDatagroup]] | None = None

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
    datagroup: dict[str, LookmlDatagroup | list[LookmlDatagroup]] | None = None


class LookmlFile(_LookmlBase):
    view: dict[str, LookmlFileEntry] | None = None
    model: dict[str, LookmlModel | LookmlFileEntry] | None = None
    explore: dict[str, LookmlFileEntry] | None = None
    manifest: dict[str, LookmlFileEntry] | LookmlManifest | None = None
    dashboard: dict[str, LookmlFileEntry] | None = None
    test: dict[str, LookmlFileEntry] | None = None


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
    if not pkg_json.exists() or f'"version": "{version}"' not in pkg_json.read_text(
        encoding="utf-8"
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
            encoding="utf-8",
            check=True,
        )
    return mod_dir


def _find_manifest_file(
    start: Path | None,
    explicit_manifest: Path | str | None = None,
) -> Path | None:
    if explicit_manifest is not None:
        mpath = Path(explicit_manifest).resolve()
        if mpath.is_dir():
            mpath = mpath / "manifest.lkml"
        if not mpath.is_file():
            raise FileNotFoundError(f"Manifest file not found: {explicit_manifest}")
        return mpath
    if start is None:
        return None
    base = start.resolve()
    if base.is_file():
        base = base.parent
    for cand_dir in (base, *list(base.parents)[:3]):
        cand = cand_dir / "manifest.lkml"
        if cand.is_file():
            return cand
    return None


def parse_lookml(
    path: Path | str | None = None,
    file: Path | str | None = None,
    lookml: str | None = None,
    *,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> LookmlProject:
    """Parse LookML from --path, --file, or --lookml with modelAssembly, extensions/refinements, constants, and positions."""
    provided = sum(x is not None for x in (path, file, lookml))
    if provided != 1:
        raise ValueError("Specify exactly one of 'path', 'file', or 'lookml'")

    mod_dir = _ensure_lookml_parser()
    opts: dict[str, Any] = {}
    if constants:
        opts["constants"] = {str(k): str(v) for k, v in constants.items()}

    if lookml is not None:
        opts["input"] = [{"path": "inline.model.lkml", "content": lookml}]
        mpath = _find_manifest_file(None, manifest)
    elif file is not None:
        fpath = Path(file).resolve()
        mpath = _find_manifest_file(fpath, manifest)
        if fpath.name.endswith(".model.lkml"):
            opts["cwd"] = str(fpath.parent)
            opts["source"] = fpath.name
        else:
            opts["input"] = [
                {"path": fpath.name, "content": fpath.read_text(encoding="utf-8")},
                {"path": "inline.model.lkml", "content": f'include: "{fpath.name}"'},
            ]
    else:
        assert path is not None
        root = Path(path).resolve()
        if root.is_file():
            return parse_lookml(file=root, manifest=manifest, constants=constants)
        mpath = _find_manifest_file(root, manifest)
        if any(root.rglob("*.model.lkml")):
            opts["cwd"] = str(root)
            opts["source"] = "**/*.lkml"
        else:
            opts["input"] = [
                *(
                    {
                        "path": f.relative_to(root).as_posix(),
                        "content": f.read_text(encoding="utf-8"),
                    }
                    for f in sorted(root.rglob("*.lkml"))
                    if f.is_file()
                ),
                {"path": "inline.model.lkml", "content": 'include: "**/*.lkml"'},
            ]

    if (
        mpath is not None
        and (file is None or mpath != Path(file).resolve())
        and (path is None or mpath != (Path(path).resolve() / "manifest.lkml"))
    ):
        opts["extraManifestContent"] = mpath.read_text(encoding="utf-8")

    js_code = f"""
const path = require("path");
const modDir = {json.dumps(str(mod_dir))};
const pegParser = require(path.join(modDir, "lib/parse/parser.generated.js"));
const getPositionsMod = require(path.join(modDir, "lib/positions/get-positions.js"));
const xf = require(path.join(modDir, "lib/transformations/index.js"));
const {{ getSchemaProperty }} = require(path.join(modDir, "lib/schema/lookml-schema.js"));

const origPegParse = pegParser.parse.bind(pegParser);
const AT_ENC_RE = /@\\{{([a-zA-Z0-9_-]+)\\}}/g;
const AT_DEC_RE = /__LKR_AT_([a-zA-Z0-9_-]+?)__/g;

function restoreAtTokens(node) {{
  if (!node || typeof node !== "object") return node;
  if (Array.isArray(node)) {{
    node.forEach(restoreAtTokens);
    return node;
  }}
  for (const k of ["value", "raw", "name", "declarationType", "key"]) {{
    if (typeof node[k] === "string" && node[k].includes("__LKR_AT_")) {{
      node[k] = node[k].replace(AT_DEC_RE, "@{{$1}}");
    }}
  }}
  for (const k of ["declarations", "items", "entries", "value", "syntax"]) {{
    if (node[k] && typeof node[k] === "object") restoreAtTokens(node[k]);
  }}
  return node;
}}

pegParser.parse = function(str, options) {{
  if (typeof str === "string" && str.includes("@{{")) {{
    try {{
      return restoreAtTokens(origPegParse(str.replace(AT_ENC_RE, "__LKR_AT_$1__"), options));
    }} catch (e) {{
      return origPegParse(str, options);
    }}
  }}
  return origPegParse(str, options);
}};

const origGetPositionsRecurse = getPositionsMod.getPositionsRecurse;
const cachedFilePositions = new Map();
let freezeFilePositions = false;
getPositionsMod.getPositionsRecurse = function(stringsNode, sl, sc, logPath, d, trace, dataNode, parentKey) {{
  if (d === 0 && Array.isArray(logPath) && logPath[1]) {{
    const cacheKey = logPath[1];
    if (freezeFilePositions && cachedFilePositions.has(cacheKey)) return cachedFilePositions.get(cacheKey);
    const res = origGetPositionsRecurse(stringsNode, sl, sc, logPath, d, trace, dataNode, parentKey);
    cachedFilePositions.set(cacheKey, res);
    return res;
  }}
  return origGetPositionsRecurse(stringsNode, sl, sc, logPath, d, trace, dataNode, parentKey);
}};

const lp = require(modDir);

function normalizeDepList(rawDep) {{
  if (!rawDep || typeof rawDep !== "object") return [];
  if (Array.isArray(rawDep)) return rawDep.flatMap(normalizeDepList);
  return (rawDep.$type || "project" in rawDep || "url" in rawDep || "override_constant" in rawDep)
    ? [rawDep]
    : Object.values(rawDep).flatMap(normalizeDepList);
}}

function extractConsts(mapObj) {{
  const out = {{}};
  for (const [k, v] of Object.entries(mapObj || {{}})) {{
    if (!k.startsWith("$") && v && typeof v === "object" && v.value != null) out[k] = String(v.value);
  }}
  return out;
}}

function extractDepOverrides(obj) {{
  return [...normalizeDepList(obj?.local_dependency), ...normalizeDepList(obj?.remote_dependency)].map(dep => ({{
    project: dep.project || dep.$name || null,
    overrides: extractConsts(dep.override_constant),
    depRef: dep
  }}));
}}

function interpolateString(str, constMap, fallbackMap = {{}}) {{
  if (typeof str !== "string" || !str.includes("@{{")) return str;
  return str.replace(AT_ENC_RE, (m, ref) =>
    Object.prototype.hasOwnProperty.call(constMap, ref) ? constMap[ref] : (Object.prototype.hasOwnProperty.call(fallbackMap, ref) ? fallbackMap[ref] : m)
  );
}}

function resolveChainedMap(map, fallbackMap = {{}}) {{
  for (let pass = 0; pass < 10; pass++) {{
    let changed = false;
    for (const [k, v] of Object.entries(map)) {{
      const next = interpolateString(v, map, fallbackMap);
      if (next !== v) {{ map[k] = next; changed = true; }}
    }}
    if (!changed) break;
  }}
  return map;
}}

const SKIP_KEYS = new Set([
  "$strings", "$ast", "$p", "$type", "$file_path", "$file_rel", "$file_name", "$file_type",
  "error", "errors", "info", "constant", "local_dependency", "remote_dependency"
]);

function substituteNode(node, constMap, parentScope, propKey, posNode, projectErrors) {{
  if (!node || typeof node !== "object" || !constMap) return node;
  if (Array.isArray(node)) {{
    for (let i = 0; i < node.length; i++) {{
      if (typeof node[i] === "string") node[i] = interpolateString(node[i], constMap);
      else substituteNode(node[i], constMap, parentScope, propKey, posNode?.[i], projectErrors);
    }}
    return node;
  }}

  const scope = node.$type || propKey || parentScope || "model";
  if (typeof node.$name === "string") node.$name = interpolateString(node.$name, constMap);

  for (const key of Object.keys(node)) {{
    if (SKIP_KEYS.has(key)) continue;
    let targetKey = key;
    if (key.includes("@{{")) {{
      const resolvedKey = interpolateString(key, constMap);
      if (resolvedKey !== key) {{
        node[resolvedKey] = node[key];
        delete node[key];
        if (posNode && typeof posNode === "object" && key in posNode) {{
          posNode[resolvedKey] = posNode[key];
          delete posNode[key];
        }}
        targetKey = resolvedKey;
      }}
    }}

    const val = node[targetKey];
    if (typeof val === "string" && val.includes("@{{")) {{
      const resolved = interpolateString(val, constMap);
      const schema = getSchemaProperty(scope, targetKey);
      let finalVal = resolved;
      if (schema?.type === "boolean") {{
        const low = resolved.trim().toLowerCase();
        if (low === "yes" || low === "true") finalVal = true;
        else if (low === "no" || low === "false") finalVal = false;
      }} else if (schema?.type === "number") {{
        const trimmed = resolved.trim();
        if (trimmed !== "" && !Number.isNaN(Number(trimmed))) finalVal = Number(trimmed);
      }}
      node[targetKey] = finalVal;
      if (finalVal !== val && typeof finalVal !== "string") {{
        const isSpurious = e => e?.code === "INVALID_PROPERTY_TYPE" && e.property === targetKey;
        if (Array.isArray(node.errors)) {{
          node.errors = node.errors.filter(e => !isSpurious(e));
          if (!node.errors.length) delete node.errors;
        }}
        if (Array.isArray(projectErrors)) {{
          projectErrors.splice(0, projectErrors.length, ...projectErrors.filter(e => !isSpurious(e)));
        }}
      }}
    }} else if (val && typeof val === "object") {{
      substituteNode(val, constMap, scope, targetKey, posNode?.[targetKey], projectErrors);
    }}
  }}
  return node;
}}

const origAssembleModels = xf.assembleModels;
(async () => {{
  let rawStdin = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) rawStdin += chunk;
  const {{ extraManifestContent, constants: cliConstants, ...parseOpts }} = JSON.parse(rawStdin);

xf.assembleModels = function(project, assembleOpts) {{
  for (const f of Object.values(project.file || {{}})) {{
    if (typeof f.$file_path === "string") f.$file_path = f.$file_path.replace(/\\\\/g, "/");
    if (typeof f.$file_rel === "string") f.$file_rel = f.$file_rel.replace(/\\\\/g, "/");
  }}
  if (extraManifestContent && project.file) {{
    const manFile = {{
      ...lp.parse(extraManifestContent, {{ strings: true }}),
      $file_path: "manifest.lkml",
      $file_rel: "",
      $file_name: "",
      $file_type: "manifest"
    }};
    project.file["manifest"] = project.manifest = manFile;
  }}

  const files = Object.values(project.file || {{}});
  const rootMan = files.find(f => f.$file_type === "manifest" && !/^imported_projects\\//.test(f.$file_path || ""));
  if (rootMan) project.manifest = rootMan;

  if (!project.manifest) {{
    const inlineMan = files.find(f => f.project_name || f.constant || f.local_dependency || f.remote_dependency || f.localization_settings);
    if (inlineMan || (cliConstants && Object.keys(cliConstants).length)) {{
      project.manifest = {{
        $file_path: inlineMan?.$file_path || "manifest.lkml",
        $file_rel: inlineMan?.$file_rel || "",
        $file_name: inlineMan?.$file_name || "",
        $file_type: "manifest",
        constant: {{}}
      }};
      for (const k of ["project_name", "timezone", "constant", "local_dependency", "remote_dependency", "localization_settings"]) {{
        if (inlineMan?.[k]) project.manifest[k] = JSON.parse(JSON.stringify(inlineMan[k]));
      }}
    }}
  }}

  xf.addPositions(project);
  freezeFilePositions = true;

  const impDirect = {{}}, impDeps = {{}}, impManifests = {{}}, importedProjectNames = new Set();
  for (const f of files) {{
    const m = (f.$file_path || "").match(/^imported_projects\\/([^/]+)\\//);
    if (m) {{
      importedProjectNames.add(m[1]);
      if (f.$file_type === "manifest") {{
        impManifests[m[1]] = f;
        impDirect[m[1]] = extractConsts(f.constant);
        impDeps[m[1]] = extractDepOverrides(f);
      }}
    }}
  }}

  const rootDirect = {{}}, rootDeps = [];
  for (const src of [...files.filter(f => !/^imported_projects\\//.test(f.$file_path || "")), ...(project.manifest ? [project.manifest] : [])]) {{
    Object.assign(rootDirect, extractConsts(src?.constant));
    rootDeps.push(...extractDepOverrides(src));
  }}

  const rootConsts = {{}};
  for (const pName of Object.keys(impDirect)) Object.assign(rootConsts, impDirect[pName]);
  for (const pName of Object.keys(impDeps)) for (const d of impDeps[pName]) Object.assign(rootConsts, d.overrides);
  Object.assign(rootConsts, rootDirect);
  for (const d of rootDeps) {{
    for (const [k, v] of Object.entries(d.overrides)) {{
      if (!d.project || !importedProjectNames.has(d.project) || !(k in rootDirect)) rootConsts[k] = v;
    }}
  }}
  if (cliConstants) Object.assign(rootConsts, cliConstants);
  resolveChainedMap(rootConsts);

  const projectConsts = {{}};
  for (const pName of new Set([...importedProjectNames, ...rootDeps.map(d => d.project).filter(Boolean)])) {{
    const pMap = {{ ...(impDirect[pName] || {{}}) }};
    for (const d of impDeps[pName] || []) Object.assign(pMap, d.overrides);
    for (const d of rootDeps) {{
      if (!d.project || d.project === pName) {{
        for (const [k, v] of Object.entries(d.overrides)) pMap[k] = interpolateString(v, rootConsts);
      }}
    }}
    if (cliConstants) Object.assign(pMap, cliConstants);
    resolveChainedMap(pMap, rootConsts);
    projectConsts[pName] = pMap;
    for (const [k, v] of Object.entries(pMap)) if (!(k in rootConsts)) rootConsts[k] = v;
  }}
  resolveChainedMap(rootConsts);

  function updateManifestObj(manObj, resolvedMap) {{
    if (!manObj || typeof manObj !== "object") return;
    for (const [k, cObj] of Object.entries(manObj.constant || {{}})) {{
      if (!k.startsWith("$") && cObj && typeof cObj === "object" && k in resolvedMap) cObj.value = resolvedMap[k];
    }}
    for (const d of extractDepOverrides(manObj)) {{
      for (const [k, ocObj] of Object.entries(d.depRef?.override_constant || {{}})) {{
        if (!k.startsWith("$") && ocObj && typeof ocObj.value === "string") ocObj.value = interpolateString(ocObj.value, resolvedMap);
      }}
    }}
  }}

  if (project.manifest) {{
    if (cliConstants && Object.keys(cliConstants).length) {{
      project.manifest.constant = project.manifest.constant || {{}};
      for (const [k, v] of Object.entries(cliConstants)) {{
        project.manifest.constant[k] = {{ ...(project.manifest.constant[k] || {{ $type: "constant", $name: k }}), value: String(v) }};
      }}
    }}
    updateManifestObj(project.manifest, rootConsts);
  }}
  for (const [pName, impMan] of Object.entries(impManifests)) {{
    updateManifestObj(impMan, {{ ...rootConsts, ...(projectConsts[pName] || {{}}) }});
  }}

  if (Object.keys(rootConsts).length) {{
    for (const [fKey, fObj] of Object.entries(project.file || {{}})) {{
      const m = (fObj.$file_path || "").match(/^imported_projects\\/([^/]+)\\//);
      const activeConsts = m ? {{ ...rootConsts, ...(projectConsts[m[1]] || {{}}) }} : rootConsts;
      substituteNode(fObj, activeConsts, fObj.$file_type || "model", null, cachedFilePositions.get(`file['${{fKey}}']`), project.errors);
      updateManifestObj(fObj, activeConsts);
    }}
    if (Array.isArray(project.errors) && !project.errors.length) delete project.errors;
  }}

  return origAssembleModels(project, assembleOpts);
}};

lp.parseFiles({{
  ...parseOpts,
  modelAssembly: true,
  extensions: true,
  positions: true,
  strings: true,
  legacyFileMetadata: true,
  console: []
}}).then(p => {{
  if (p.positions && p.positions.file && !p.positions.file.manifest && p.positions.file["inline.model"] && p.manifest) {{
    p.positions.file.manifest = p.positions.file["inline.model"];
  }}
  if (p.file && !p.file.view) {{
    const allFiles = Object.values(p.file);
    p.file = {{
      model: allFiles.filter(f => f.$file_type === "model" || (f.$file_path && f.$file_path.endsWith(".model.lkml"))).reduce((a, f) => (a[f.$file_rel || f.$file_path] = f, a), {{}}),
      view: allFiles.filter(f => f.$file_type === "view" || (f.$file_path && f.$file_path.endsWith(".view.lkml"))).reduce((a, f) => (a[f.$file_rel || f.$file_path] = f, a), {{}}),
      explore: allFiles.filter(f => f.$file_type === "explore" || (f.$file_path && f.$file_path.endsWith(".explore.lkml"))).reduce((a, f) => (a[f.$file_rel || f.$file_path] = f, a), {{}}),
      test: allFiles.filter(f => f.$file_type === "test" || (f.$file_path && f.$file_path.endsWith(".test.lkml")) || f.test).reduce((a, f) => (a[f.$file_rel || f.$file_path] = f, a), {{}}),
      manifest: p.manifest || undefined
    }};
  }}
  process.stdout.write(JSON.stringify(p));
}}).catch(err => {{
  console.error(err);
  process.exit(1);
}});
}})().catch(err => {{
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
        encoding="utf-8",
        check=True,
    )
    out = proc.stdout if isinstance(proc.stdout, str) else proc.stdout.decode("utf-8")
    return LookmlProject.model_validate_json(out)
