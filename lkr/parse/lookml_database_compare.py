from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from lkr.logger import logger
from lkr.parse.dag import (
    _as_list,
    _build_chain,
    _collect_declarations,
    _is_field_allowed_by_spec,
    _resolve_explore_base,
)
from lkr.parse.lookml import (
    LookmlDimension,
    LookmlDimensionGroup,
    LookmlExplore,
    LookmlModel,
    LookmlProject,
    LookmlView,
    parse_lookml,
)
from lkr.parse.sql import (
    TableRef,
    _split_table_ref,
    parse_sql,
)
from lkr.parse.types import (
    CompiledTableInfo,
    CompileErrorInfo,
    LookmlDatabaseCompareResult,
    MissingColumnInfo,
    MissingInDatabase,
    MissingTableInfo,
    TypeMismatchInfo,
    UnmodeledColumnsInfo,
    UnmodeledInLookml,
    ValidationResult,
)

__all__ = [
    "CatalogTable",
    "DatabaseCatalog",
    "fetch_sdk_database_catalog",
    "format_compare_result",
    "load_db_schema_file",
    "parse_lookml_database_compare",
]

_SQL_TABLE_NAME_RE = re.compile(
    r"\$\{\s*([a-zA-Z0-9_]+)\.SQL_TABLE_NAME\s*\}", re.IGNORECASE
)
_TABLE_COL_RE = re.compile(
    r"\$\{TABLE\}\s*\.\s*(?:[`\"'\[]([^`\"'\]]+)[`\"'\]]|([a-zA-Z0-9_]+))",
    re.IGNORECASE,
)
_FIELD_REF_RE = re.compile(
    r"\$\{\s*([a-zA-Z0-9_]+)(?:\.([a-zA-Z0-9_]+))?\s*\}", re.IGNORECASE
)


class CatalogTable:
    def __init__(
        self,
        name: str,
        schema: str | None = None,
        catalog: str | None = None,
        columns: dict[str, str] | list[str] | list[dict[str, Any]] | None = None,
    ):
        self.name = name.strip("`\"'[] ")
        self.schema = schema.strip("`\"'[] ") if schema else None
        self.catalog = catalog.strip("`\"'[] ") if catalog else None
        self.columns: dict[str, str] = {}
        self.col_display: dict[str, str] = {}

        if isinstance(columns, dict):
            for k, v in columns.items():
                k_clean = str(k).strip("`\"'[] ")
                k_low = k_clean.lower()
                self.columns[k_low] = str(v) if v else "UNKNOWN"
                self.col_display[k_low] = k_clean
        elif isinstance(columns, list):
            for item in columns:
                if isinstance(item, dict):
                    c_name = str(item.get("name") or item.get("column") or "").strip(
                        "`\"'[] "
                    )
                    c_type = str(
                        item.get("data_type")
                        or item.get("data_type_looker")
                        or item.get("type")
                        or "UNKNOWN"
                    )
                    if c_name:
                        c_low = c_name.lower()
                        self.columns[c_low] = c_type
                        self.col_display[c_low] = c_name
                elif isinstance(item, str):
                    c_clean = item.strip("`\"'[] ")
                    if c_clean:
                        c_low = c_clean.lower()
                        self.columns[c_low] = "UNKNOWN"
                        self.col_display[c_low] = c_clean

    @property
    def display_name(self) -> str:
        if self.catalog and self.schema:
            return f"{self.catalog}.{self.schema}.{self.name}"
        if self.schema:
            return f"{self.schema}.{self.name}"
        return self.name

    def has_column(self, col: str) -> bool:
        return col.strip("`\"'[] ").lower() in self.columns

    def get_column_type(self, col: str) -> str | None:
        return self.columns.get(col.strip("`\"'[] ").lower())


class DatabaseCatalog:
    def __init__(self, tables: list[CatalogTable] | None = None):
        self.tables: list[CatalogTable] = tables or []

    def add_table(self, table: CatalogTable) -> None:
        self.tables.append(table)

    def find_table(
        self, name: str, schema: str | None = None, catalog: str | None = None
    ) -> CatalogTable | None:
        name_clean = name.strip("`\"'[] ").lower()
        schema_clean = schema.strip("`\"'[] ").lower() if schema else None
        catalog_clean = catalog.strip("`\"'[] ").lower() if catalog else None

        # 1. Exact catalog + schema + table match
        for t in self.tables:
            if t.name.lower() == name_clean:
                if catalog_clean and t.catalog and t.catalog.lower() != catalog_clean:
                    continue
                if schema_clean and t.schema and t.schema.lower() != schema_clean:
                    continue
                if schema_clean and not t.schema:
                    continue
                return t

        # 2. Schema + table match (catalog omitted in LookML or DB catalog)
        if schema_clean:
            for t in self.tables:
                if (
                    t.name.lower() == name_clean
                    and t.schema
                    and t.schema.lower() == schema_clean
                ):
                    return t

        # 3. Table-only match when LookML has no schema/catalog
        if not catalog_clean and not schema_clean:
            for t in self.tables:
                if t.name.lower() == name_clean:
                    return t

        return None

    def get_tables_in_schemas(self, schemas: set[str | None]) -> list[CatalogTable]:
        if not schemas or schemas == {None}:
            return list(self.tables)
        schemas_clean = {s.lower() for s in schemas if s}
        return [
            t
            for t in self.tables
            if (t.schema and t.schema.lower() in schemas_clean)
            or (not t.schema and None in schemas)
        ]


def load_db_schema_file(path: Path | str) -> DatabaseCatalog:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Database schema file not found: {path}")
    raw_text = p.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    catalog = DatabaseCatalog()

    def _split_table_name(tbl_str: str) -> tuple[str | None, str | None, str]:
        parts = [s.strip("`\"'[] ") for s in tbl_str.split(".") if s.strip("`\"'[] ")]
        cat, sch, name = ([None, None, *(parts or [tbl_str])])[-3:]
        return cat, sch, name or tbl_str

    if isinstance(data, dict):
        if "tables" in data and isinstance(data["tables"], list):
            for item in data["tables"]:
                if isinstance(item, dict):
                    tbl_str = item.get("table") or item.get("name") or ""
                    cat_s, sch_s, name_s = _split_table_name(tbl_str)
                    cat = item.get("catalog") or cat_s
                    sch = item.get("schema") or sch_s
                    name = item.get("name") if not cat_s and not sch_s else name_s
                    cols = item.get("columns") or []
                    catalog.add_table(
                        CatalogTable(name=name, schema=sch, catalog=cat, columns=cols)
                    )
                elif isinstance(item, str):
                    cat, sch, name = _split_table_name(item)
                    catalog.add_table(
                        CatalogTable(name=name, schema=sch, catalog=cat, columns=[])
                    )
        elif "tables" in data and isinstance(data["tables"], dict):
            for t_key, t_val in data["tables"].items():
                cat, sch, name = _split_table_name(t_key)
                catalog.add_table(
                    CatalogTable(name=name, schema=sch, catalog=cat, columns=t_val)
                )
        else:
            # Check for format: {"schema.table": ["col1", "col2"]} or nested {"cat": {"sch": {"tbl": [...]}}}
            is_nested = any(isinstance(v, dict) for v in data.values())
            if is_nested:
                for k1, v1 in data.items():
                    if isinstance(v1, dict):
                        for k2, v2 in v1.items():
                            if isinstance(v2, dict):
                                for k3, v3 in v2.items():
                                    catalog.add_table(
                                        CatalogTable(
                                            name=k3, schema=k2, catalog=k1, columns=v3
                                        )
                                    )
                            elif isinstance(v2, list):
                                catalog.add_table(
                                    CatalogTable(
                                        name=k2, schema=k1, catalog=None, columns=v2
                                    )
                                )
            else:
                for t_key, t_val in data.items():
                    cat, sch, name = _split_table_name(t_key)
                    catalog.add_table(
                        CatalogTable(name=name, schema=sch, catalog=cat, columns=t_val)
                    )
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                tbl_str = item.get("table") or item.get("name") or ""
                cat_s, sch_s, name_s = _split_table_name(tbl_str)
                cat = item.get("catalog") or cat_s
                sch = item.get("schema") or sch_s
                name = item.get("name") if not cat_s and not sch_s else name_s
                cols = item.get("columns") or []
                catalog.add_table(
                    CatalogTable(name=name, schema=sch, catalog=cat, columns=cols)
                )
            elif isinstance(item, str):
                cat, sch, name = _split_table_name(item)
                catalog.add_table(
                    CatalogTable(name=name, schema=sch, catalog=cat, columns=[])
                )

    return catalog


def fetch_sdk_database_catalog(
    sdk: Any,
    connections_and_schemas: list[tuple[str, str | None, str | None]],
    fetch_columns: bool = False,
) -> DatabaseCatalog:
    catalog = DatabaseCatalog()
    seen: set[tuple[str, str | None, str | None]] = set()

    for conn_name, db_name, sch_name in connections_and_schemas:
        if not conn_name:
            continue
        key = (conn_name, db_name, sch_name)
        if key in seen:
            continue
        seen.add(key)

        try:
            schema_tables = sdk.connection_tables(
                connection_name=conn_name,
                database=db_name,
                schema_name=sch_name,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Failed to fetch connection tables for connection '{conn_name}': {e}"
            )
            continue

        for st in schema_tables or []:
            t_schema = getattr(st, "name", None) or sch_name
            t_list = getattr(st, "tables", None) or []
            for t in t_list:
                t_name = getattr(t, "name", None) or ""
                if not t_name:
                    continue

                col_map: dict[str, str] = {}
                if fetch_columns:
                    try:
                        sc_list = sdk.connection_columns(
                            connection_name=conn_name,
                            database=db_name,
                            schema_name=t_schema,
                            table_names=t_name,
                        )
                        for sc in sc_list or []:
                            for c in getattr(sc, "columns", None) or []:
                                c_name = getattr(c, "name", None)
                                c_type = (
                                    getattr(c, "data_type_looker", None)
                                    or getattr(c, "data_type", None)
                                    or "UNKNOWN"
                                )
                                if c_name:
                                    col_map[c_name.lower()] = c_type
                    except Exception as e:  # noqa: BLE001
                        logger.debug(
                            f"Failed to fetch columns for {conn_name}.{t_schema}.{t_name}: {e}"
                        )

                catalog.add_table(
                    CatalogTable(
                        name=t_name,
                        schema=t_schema,
                        catalog=db_name,
                        columns=col_map,
                    )
                )

    return catalog


def _clean_raw_table_string(raw: str) -> str:
    cleaned = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "", raw)
    cleaned = re.sub(r"@\{[a-zA-Z0-9_]+\}", "", cleaned)
    return cleaned.strip().rstrip(";").strip()


def _resolve_view_sql_table_name(
    view_name: str,
    views: dict[str, LookmlView],
    visited: set[str] | None = None,
) -> str:
    if visited is None:
        visited = set()
    if view_name in visited:
        return view_name
    visited.add(view_name)

    vobj = views.get(view_name)
    if not vobj or not vobj.sql_table_name:
        return view_name

    raw = vobj.sql_table_name.strip().rstrip(";").strip()
    return _SQL_TABLE_NAME_RE.sub(
        lambda m: _resolve_view_sql_table_name(m.group(1), views, set(visited)),
        raw,
    )


def _table_ref_from_sql(raw_table: str, fallback_name: str) -> TableRef:
    clean = _clean_raw_table_string(raw_table)
    if not clean:
        clean = fallback_name
    try:
        tbl = sqlglot.to_table(clean)
        if isinstance(tbl, exp.Table) and tbl.name:
            return _split_table_ref(tbl)
    except Exception:  # noqa: BLE001, S110
        pass
    parts = [p.strip("`\"'[] ") for p in clean.split(".") if p.strip("`\"'[] ")]
    cat, db, name = ([None, None, *(parts or [fallback_name])])[-3:]
    return TableRef(catalog=cat, db=db, name=name or fallback_name)


def _extract_view_fields_columns(
    view_obj: LookmlView,
    allowed_fields: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Extract physical columns and primary keys from a LookML view."""
    columns: set[str] = set()
    primary_keys: set[str] = set()

    # Collect all fields
    fields: list[tuple[str, Any]] = []
    for d_name, d_obj in (view_obj.dimension or {}).items():
        fields.append((d_name, d_obj))
    for dg_name, dg_obj in (view_obj.dimension_group or {}).items():
        fields.append((dg_name, dg_obj))
    for m_name, m_obj in (view_obj.measure or {}).items():
        fields.append((m_name, m_obj))

    for f_name, f_obj in fields:
        if allowed_fields is not None and f_name.lower() not in allowed_fields:
            continue

        is_pk = bool(getattr(f_obj, "primary_key", False))
        sql_texts = [
            s
            for s in (
                getattr(f_obj, "sql", None),
                getattr(f_obj, "sql_start", None),
                getattr(f_obj, "sql_end", None),
            )
            if s
        ]

        found_cols: list[str] = []
        for s in sql_texts:
            for m in _TABLE_COL_RE.finditer(s):
                col_name = m.group(1) or m.group(2)
                if col_name:
                    found_cols.append(col_name.strip("`\"'[] "))

        if found_cols:
            for col in found_cols:
                columns.add(col)
                if is_pk:
                    primary_keys.add(col)
        elif not sql_texts and isinstance(f_obj, (LookmlDimension, LookmlDimensionGroup)):
            f_type = getattr(f_obj, "type", "") or ""
            if f_type not in ("location", "distance") and getattr(f_obj, "case", None) is None:
                columns.add(f_name)
                if is_pk:
                    primary_keys.add(f_name)
        elif sql_texts and isinstance(f_obj, (LookmlDimension, LookmlDimensionGroup)):
            # Check if sql is a bare column reference without ${TABLE}.
            clean_sql = sql_texts[0].strip().rstrip(";").strip()
            if re.match(r"^[a-zA-Z0-9_]+$", clean_sql) and not clean_sql.upper().startswith("COUNT"):
                columns.add(clean_sql)
                if is_pk:
                    primary_keys.add(clean_sql)

    return columns, primary_keys


def _format_table_key(catalog: str | None, schema: str | None, name: str) -> str:
    cat = catalog.strip("`\"'[] ") if catalog else None
    sch = schema.strip("`\"'[] ") if schema else None
    nm = name.strip("`\"'[] ")
    if cat and sch:
        return f"{cat}.{sch}.{nm}"
    if sch:
        return f"{sch}.{nm}"
    return nm


def _extract_explore_via_ast(
    model_name: str,
    model_obj: LookmlModel,
    explore_name: str,
    explore_obj: LookmlExplore,
    proj: LookmlProject,
    view_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    view_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    model_views: dict[str, LookmlView],
) -> dict[str, dict[str, Any]]:
    """Compile physical tables and columns for an explore statically from LookML AST."""
    tables: dict[str, dict[str, Any]] = {}
    exp_chain = _build_chain(explore_name, exp_base_decls, exp_ref_decls)
    base_view_name, base_alias, _, _ = _resolve_explore_base(
        explore_name, explore_obj, exp_chain, model_views
    )

    # 1. Base view
    base_view_obj = model_views.get(base_view_name)
    if base_view_obj:
        raw_tbl = _resolve_view_sql_table_name(base_view_name, model_views)
        t_ref = _table_ref_from_sql(raw_tbl, base_view_name)
        t_key = _format_table_key(t_ref.catalog, t_ref.db, t_ref.name)
        b_cols, b_pks = _extract_view_fields_columns(base_view_obj)

        tables[t_key] = {
            "table": t_key,
            "catalog": t_ref.catalog,
            "schema": t_ref.db,
            "name": t_ref.name,
            "connection": model_obj.connection,
            "columns": set(b_cols),
            "primary_keys": set(b_pks),
            "view_alias": base_alias,
        }

    # 2. Joined views
    for j_alias, j_obj in (explore_obj.join or {}).items():
        jv_name = j_obj.from_ or j_obj.view_name or j_alias
        jv_obj = model_views.get(jv_name)
        if not jv_obj:
            continue

        raw_tbl = (
            j_obj.sql_table_name
            or _resolve_view_sql_table_name(jv_name, model_views)
        )
        t_ref = _table_ref_from_sql(raw_tbl, jv_name)
        t_key = _format_table_key(t_ref.catalog, t_ref.db, t_ref.name)

        allowed_fields: set[str] | None = None
        j_fields = getattr(j_obj, "fields", None)
        if j_fields is not None:
            all_field_names = [
                *(getattr(jv_obj, "dimension", {}) or {}),
                *(getattr(jv_obj, "dimension_group", {}) or {}),
                *(getattr(jv_obj, "measure", {}) or {}),
            ]
            allowed_fields = {
                f_name.lower()
                for f_name in all_field_names
                if _is_field_allowed_by_spec(
                    j_fields, j_alias, {f_name.lower()}, model_views, j_alias
                )
            }

        j_cols, j_pks = _extract_view_fields_columns(jv_obj, allowed_fields)

        # Foreign key & sql_on columns
        j_fk = getattr(j_obj, "foreign_key", None)
        if j_fk:
            # Foreign key exists on base view table
            fk_col = j_fk.strip("`\"'[] ")
            for t_data in tables.values():
                if t_data["view_alias"] == base_alias:
                    t_data["columns"].add(fk_col)
            # Joined view uses its primary key
            j_cols.update(j_pks)

        j_sql_on = getattr(j_obj, "sql_on", None)
        if j_sql_on:
            for m in _TABLE_COL_RE.finditer(j_sql_on):
                c_name = m.group(1) or m.group(2)
                if c_name:
                    j_cols.add(c_name.strip("`\"'[] "))

            for m in _FIELD_REF_RE.finditer(j_sql_on):
                v_ref = m.group(1)
                f_ref = m.group(2)
                if f_ref:
                    if v_ref == base_alias:
                        for t_data in tables.values():
                            if t_data["view_alias"] == base_alias:
                                t_data["columns"].add(f_ref)
                    elif v_ref == j_alias:
                        j_cols.add(f_ref)

        j_sfk = getattr(j_obj, "sql_foreign_key", None)
        if j_sfk:
            for m in _TABLE_COL_RE.finditer(j_sfk):
                c_name = m.group(1) or m.group(2)
                if c_name:
                    j_cols.add(c_name.strip("`\"'[] "))

        if t_key not in tables:
            tables[t_key] = {
                "table": t_key,
                "catalog": t_ref.catalog,
                "schema": t_ref.db,
                "name": t_ref.name,
                "connection": model_obj.connection,
                "columns": set(j_cols),
                "primary_keys": set(j_pks),
                "view_alias": j_alias,
            }
        else:
            tables[t_key]["columns"].update(j_cols)
            tables[t_key]["primary_keys"].update(j_pks)

    return tables


def _extract_explore_via_sdk_sql(
    sdk: Any,
    model_name: str,
    explore_name: str,
    connection_name: str | None,
) -> dict[str, dict[str, Any]]:
    """Compile explore SQL using Looker SDK and parse physical tables and columns via SQLGlot."""
    from looker_sdk.sdk.api40.models import WriteQuery

    body = WriteQuery(
        model=model_name,
        view=explore_name,
        fields=["ALL_FIELDS*"],
    )
    sql_str = sdk.run_inline_query(result_format="sql", body=body)
    if isinstance(sql_str, bytes):
        sql_str = sql_str.decode("utf-8")

    parsed = parse_sql(sql=sql_str)
    if not parsed.queries or parsed.queries[0].error:
        err = parsed.queries[0].error if parsed.queries else "SQL parsing failed"
        raise ValueError(f"Failed to parse compiled SQL: {err}")

    pq = parsed.queries[0]
    cte_names = {c.name.lower() for c in pq.ctes if c.name}

    # Parse AST to build alias-to-table map and collect columns
    try:
        expr = sqlglot.parse_one(sql_str, read="bigquery" if chr(96) in sql_str else None)
    except Exception:  # noqa: BLE001
        try:
            expr = sqlglot.parse_one(sql_str)
        except Exception:  # noqa: BLE001
            expr = None

    table_aliases: dict[str, TableRef] = {}
    table_refs_by_key: dict[str, TableRef] = {}

    for t in pq.tables:
        if t.name.lower() in cte_names:
            continue
        t_key = _format_table_key(t.catalog, t.db, t.name)
        table_refs_by_key[t_key] = t
        if t.alias:
            table_aliases[t.alias.lower()] = t
        table_aliases[t.name.lower()] = t

    cols_by_key: dict[str, set[str]] = defaultdict(set)

    if expr is not None:
        for col in expr.find_all(exp.Column):
            c_name = col.name.strip("`\"'[] ")
            if not c_name:
                continue
            tbl_prefix = (col.table or "").strip("`\"'[] ").lower()
            if tbl_prefix in table_aliases:
                t_ref = table_aliases[tbl_prefix]
                cols_by_key[_format_table_key(t_ref.catalog, t_ref.db, t_ref.name)].add(
                    c_name
                )
            elif len(table_refs_by_key) == 1:
                single_key = next(iter(table_refs_by_key))
                cols_by_key[single_key].add(c_name)

    out: dict[str, dict[str, Any]] = {}
    for t_key, t_ref in table_refs_by_key.items():
        out[t_key] = {
            "table": t_key,
            "catalog": t_ref.catalog,
            "schema": t_ref.db,
            "name": t_ref.name,
            "connection": connection_name,
            "columns": cols_by_key.get(t_key, set()),
            "primary_keys": set(),
        }

    return out


def parse_lookml_database_compare(
    path: Path | str | None = None,
    lookml_file: Path | str | None = None,
    lookml: str | None = None,
    *,
    model: list[str] | str | None = None,
    explore: list[str] | str | None = None,
    columns: bool = False,
    validate: bool = False,
    validate_columns: bool = False,
    db_schema_file: Path | str | None = None,
    sdk: Any | None = None,
    project: LookmlProject | None = None,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> LookmlDatabaseCompareResult:
    """Compile physical tables/columns across LookML explores and validate them against the database."""
    if validate_columns:
        validate = True
        columns = True
    if db_schema_file is not None:
        validate = True

    model_filters: set[str] | None = None
    if model:
        m_list = [model] if isinstance(model, str) else model
        model_filters = {s.strip().lower() for m in m_list for s in m.split(",") if s.strip()}

    explore_filters: set[str] | None = None
    if explore:
        e_list = [explore] if isinstance(explore, str) else explore
        explore_filters = {s.strip().lower() for e in e_list for s in e.split(",") if s.strip()}

    warnings: list[str] = [
        "ALL_FIELDS* SQL compilation does not evaluate filter-only fields or non-default parameter values."
    ]

    proj = (
        project.apply_defaults()
        if project is not None
        else parse_lookml(
            path=path,
            file=lookml_file,
            lookml=lookml,
            manifest=manifest,
            constants=constants,
        ).apply_defaults()
    )

    view_base_decls, view_ref_decls = _collect_declarations(proj, "view", LookmlView)
    exp_base_decls, exp_ref_decls = _collect_declarations(proj, "explore", LookmlExplore)

    table_data_map: dict[str, dict[str, Any]] = {}
    compile_errors: list[CompileErrorInfo] = []
    referenced_schemas: set[str | None] = set()
    connections_and_schemas: list[tuple[str, str | None, str | None]] = []

    for m_name, m_obj in (proj.model or {}).items():
        if model_filters and m_name.lower() not in model_filters:
            continue

        m_views: dict[str, LookmlView] = {}
        for k, v in (m_obj.view or {}).items():
            for vo in _as_list(v):
                if isinstance(vo, LookmlView):
                    m_views[k] = vo

        for e_name, e_val in (m_obj.explore or {}).items():
            if explore_filters and e_name.lower() not in explore_filters:
                continue

            for e_obj in _as_list(e_val):
                if not isinstance(e_obj, LookmlExplore):
                    continue

                full_exp_name = f"{m_name}.{e_name}"
                exp_tables: dict[str, dict[str, Any]] | None = None

                # Try SDK SQL compilation first if SDK is available
                if sdk is not None:
                    try:
                        exp_tables = _extract_explore_via_sdk_sql(
                            sdk=sdk,
                            model_name=m_name,
                            explore_name=e_name,
                            connection_name=m_obj.connection,
                        )
                    except Exception as e:  # noqa: BLE001
                        compile_errors.append(
                            CompileErrorInfo(
                                model=m_name, explore=e_name, error=str(e)
                            )
                        )
                        logger.debug(
                            f"SDK SQL compilation failed for {full_exp_name}, falling back to AST: {e}"
                        )

                # Fallback / offline AST compilation
                if exp_tables is None:
                    try:
                        exp_tables = _extract_explore_via_ast(
                            model_name=m_name,
                            model_obj=m_obj,
                            explore_name=e_name,
                            explore_obj=e_obj,
                            proj=proj,
                            view_base_decls=view_base_decls,
                            view_ref_decls=view_ref_decls,
                            exp_base_decls=exp_base_decls,
                            exp_ref_decls=exp_ref_decls,
                            model_views=m_views,
                        )
                    except Exception as e:  # noqa: BLE001
                        compile_errors.append(
                            CompileErrorInfo(
                                model=m_name, explore=e_name, error=str(e)
                            )
                        )
                        continue

                for t_key, t_info in exp_tables.items():
                    referenced_schemas.add(t_info.get("schema"))
                    if m_obj.connection:
                        connections_and_schemas.append(
                            (
                                m_obj.connection,
                                t_info.get("catalog"),
                                t_info.get("schema"),
                            )
                        )

                    if t_key not in table_data_map:
                        table_data_map[t_key] = {
                            "table": t_info["table"],
                            "catalog": t_info["catalog"],
                            "schema": t_info["schema"],
                            "name": t_info["name"],
                            "connection": t_info["connection"],
                            "explores": {full_exp_name},
                            "columns": set(t_info["columns"]),
                        }
                    else:
                        table_data_map[t_key]["explores"].add(full_exp_name)
                        table_data_map[t_key]["columns"].update(t_info["columns"])

    # Build compiled tables list
    compiled_tables: list[CompiledTableInfo] = []
    for t_key in sorted(table_data_map.keys()):
        td = table_data_map[t_key]
        cols = sorted(td["columns"]) if columns else []
        compiled_tables.append(
            CompiledTableInfo(
                table=td["table"],
                catalog=td["catalog"],
                schema=td["schema"],
                name=td["name"],
                connection=td["connection"],
                explores=sorted(td["explores"]),
                columns=cols,
            )
        )

    # Database validation
    validation_result: ValidationResult | None = None
    if validate:
        catalog: DatabaseCatalog | None = None
        if db_schema_file is not None:
            catalog = load_db_schema_file(db_schema_file)
        elif sdk is not None:
            catalog = fetch_sdk_database_catalog(
                sdk=sdk,
                connections_and_schemas=connections_and_schemas,
                fetch_columns=columns,
            )
        else:
            warnings.append(
                "Cannot validate against database: Looker SDK is not authenticated and no --db-schema-file was provided."
            )

        if catalog is not None:
            missing_tables: list[MissingTableInfo] = []
            missing_columns: list[MissingColumnInfo] = []
            type_mismatches: list[TypeMismatchInfo] = []
            unmodeled_tables: list[str] = []
            unmodeled_columns: list[UnmodeledColumnsInfo] = []

            # 1. Missing in database (in LookML, not in DB)
            for tbl in compiled_tables:
                cat_tbl = catalog.find_table(tbl.name, tbl.schema, tbl.catalog)
                if cat_tbl is None:
                    missing_tables.append(
                        MissingTableInfo(table=tbl.table, explores=tbl.explores)
                    )
                elif columns:
                    for col in tbl.columns:
                        if not cat_tbl.has_column(col):
                            missing_columns.append(
                                MissingColumnInfo(
                                    table=tbl.table,
                                    column=col,
                                    explores=tbl.explores,
                                )
                            )

            # 2. Unmodeled in LookML (in DB, not in LookML)
            scope_schemas = (
                referenced_schemas if any(s is not None for s in referenced_schemas) else set()
            )
            candidate_db_tables = catalog.get_tables_in_schemas(scope_schemas)

            for db_t in candidate_db_tables:
                matching_ct = next(
                    (
                        ct
                        for ct in compiled_tables
                        if ct.name.lower() == db_t.name.lower()
                        and (
                            not ct.schema
                            or ct.schema.lower() == (db_t.schema or "").lower()
                        )
                    ),
                    None,
                )
                if matching_ct is None:
                    unmodeled_tables.append(db_t.display_name)
                elif columns:
                    modeled_cols = {c.lower() for c in matching_ct.columns}
                    unmodeled_cols = [
                        c_orig
                        for c_low, c_orig in db_t.col_display.items()
                        if c_low not in modeled_cols
                    ]
                    if unmodeled_cols:
                        unmodeled_columns.append(
                            UnmodeledColumnsInfo(
                                table=matching_ct.table,
                                columns=sorted(unmodeled_cols),
                            )
                        )

            unmodeled_tables.sort()
            unmodeled_columns.sort(key=lambda u: u.table)

            validation_result = ValidationResult(
                missing_in_database=MissingInDatabase(
                    tables=missing_tables,
                    columns=missing_columns,
                    type_mismatches=type_mismatches,
                ),
                unmodeled_in_lookml=UnmodeledInLookml(
                    tables=unmodeled_tables,
                    columns=unmodeled_columns,
                ),
            )

    return LookmlDatabaseCompareResult(
        warnings=warnings,
        tables=compiled_tables,
        validation=validation_result,
        compile_errors=compile_errors,
    )


def format_compare_result(
    result: LookmlDatabaseCompareResult,
    fmt: Literal["console", "json", "txt"] = "console",
) -> str:
    if fmt == "json":
        return result.model_dump_json(indent=2, by_alias=True, exclude_none=True)

    lines: list[str] = []

    if result.warnings:
        for w in result.warnings:
            lines.append(f"⚠️  {w}")
        lines.append("")

    lines.append(f"Compiled LookML Tables ({len(result.tables)} tables)")
    lines.append("-" * 70)

    for tbl in result.tables:
        lines.append(f"Table: {tbl.table}")
        if tbl.connection:
            lines.append(f"  Connection: {tbl.connection}")
        lines.append(f"  Explores: {', '.join(tbl.explores)}")
        if tbl.columns:
            lines.append(f"  Columns ({len(tbl.columns)}): {', '.join(tbl.columns)}")
        lines.append("")

    if result.validation is not None:
        v = result.validation
        lines.append("=" * 70)
        lines.append("Database Validation")
        lines.append("=" * 70)

        missing_t = v.missing_in_database.tables
        missing_c = v.missing_in_database.columns
        unmod_t = v.unmodeled_in_lookml.tables
        unmod_c = v.unmodeled_in_lookml.columns

        has_issues = bool(missing_t or missing_c or unmod_t or unmod_c)

        if not has_issues:
            lines.append("✅ All compiled tables and columns exist in the database.")
            lines.append("")
        else:
            if missing_t or missing_c:
                lines.append("❌ Missing in Database (referenced in LookML, not in DB):")
                if missing_t:
                    lines.append(f"  Tables ({len(missing_t)}):")
                    for mt in missing_t:
                        lines.append(f"    • {mt.table} (explores: {', '.join(mt.explores)})")
                if missing_c:
                    lines.append(f"  Columns ({len(missing_c)}):")
                    for mc in missing_c:
                        lines.append(
                            f"    • {mc.table}.{mc.column} (explores: {', '.join(mc.explores)})"
                        )
                lines.append("")

            if unmod_t or unmod_c:
                lines.append("⚠️  Unmodeled in LookML (exist in DB, not referenced in LookML):")
                if unmod_t:
                    lines.append(f"  Tables ({len(unmod_t)}):")
                    for ut in unmod_t:
                        lines.append(f"    • {ut}")
                if unmod_c:
                    lines.append(f"  Columns ({len(unmod_c)} tables):")
                    for uc in unmod_c:
                        lines.append(f"    • {uc.table}: {', '.join(uc.columns)}")
                lines.append("")

    if result.compile_errors:
        lines.append("=" * 70)
        lines.append(f"Compile Errors ({len(result.compile_errors)})")
        lines.append("=" * 70)
        for ce in result.compile_errors:
            lines.append(f"• {ce.model}.{ce.explore}: {ce.error}")
        lines.append("")

    return "\n".join(lines).rstrip()
