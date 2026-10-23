import itertools
import json
import os
import re
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from lkr.logger import logger
from lkr.parse.constants import SQL_TO_LOOKML_DOC
from lkr.parse.dag import (
    _LOOKML_REF_RE,
    LookmlExploreJoinGraph,
    LookmlExploreJoinNode,
    _as_list,
    _build_chain,
    _chain_root_pos,
    _collect_declarations,
    _extract_lookml_refs,
    _is_field_allowed_by_spec,
    _qualify_field_ref,
    _resolve_explore_base,
    build_explore_join_graph,
)
from lkr.parse.lookml import (
    LookmlDatagroup,
    LookmlDerivedTable,
    LookmlDimensionGroup,
    LookmlExplore,
    LookmlExploreSource,
    LookmlFilter,
    LookmlModel,
    LookmlPositions,
    LookmlTest,
    LookmlView,
    parse_lookml,
)
from lkr.parse.sql import (
    ParsedQuery,
    TableRef,
    _apply_default_db_schema,
    _has_projection_star,
    _normalize_sql_join_type,
    _optimize_stars,
    _split_table_ref,
    parse_sql,
)
from lkr.parse.types import (
    ExploreJoinComparison,
    JoinPrecedent,
    JoinSafetyWarning,
    LookmlAggregateTableMatch,
    LookmlExploreFieldMatch,
    LookmlExploreQueryMatch,
    LookmlFieldMatch,
    LookmlQueryFieldUsage,
    LookmlSourceLocation,
    LookmlTestMatch,
    LookmlUsageMatch,
    LookmlViewMatch,
    QueryLookmlMapping,
    SqlLookmlCompareResult,
    SqlToLookmlResult,
)

_TABLE_COL_RE = re.compile(
    r"\$\{TABLE\}\s*\.\s*(?:[`\"'\[]([^`\"'\]]+)[`\"'\]]|([a-zA-Z0-9_]+))",
    re.IGNORECASE,
)

_DtSource = str | TableRef
_DtColMap = dict[str, list[tuple[_DtSource, str]]]


def _extract_dt_lineage(
    node: exp.Expr | None,
    cte_env: dict[str, _DtColMap] | None = None,
) -> _DtColMap:
    if node is None:
        return {}
    env = dict(cte_env) if cte_env else {}
    if with_ := node.args.get("with_"):
        for cte in with_.expressions:
            if cte.alias_or_name:
                env[cte.alias_or_name.lower()] = _extract_dt_lineage(cte.this, env)
    if isinstance(node, (exp.Subquery, exp.Paren)):
        return _extract_dt_lineage(node.this, env)
    if isinstance(node, exp.SetOperation):
        out = _extract_dt_lineage(node.this, env)
        for k, v in _extract_dt_lineage(node.expression, env).items():
            out.setdefault(k, []).extend(v)
        return out
    if not isinstance(node, exp.Select):
        return {}

    sources: dict[str, _DtSource | _DtColMap] = {}
    from_clause = node.args.get("from") or node.args.get("from_")
    src_items = [
        s.this
        for s in (from_clause, *(node.args.get("joins") or []))
        if s and s.this is not None
    ]
    for src in src_items:
        if isinstance(src, exp.Table) and src.name:
            t_low = src.name.lower()
            alias = (src.alias or src.name).lower()
            if t_low in env:
                sources[alias] = env[t_low]
            elif t_low.startswith("__lkml_tbl_"):
                sources[alias] = t_low[11:]
            else:
                sources[alias] = _split_table_ref(src)
        elif isinstance(src, exp.Subquery):
            sources[(src.alias or f"__sub_{len(sources)}").lower()] = (
                _extract_dt_lineage(src.this, env)
            )

    out_map: _DtColMap = {}
    for proj in node.selects:
        out_col = proj.alias_or_name.lower()
        if not out_col or out_col == "*":
            continue
        for col_expr in proj.find_all(exp.Column):
            if (
                not col_expr.name
                or col_expr.name == "*"
                or col_expr.arg_key == "except_"
                or isinstance(col_expr.this, exp.Star)
            ):
                continue
            c_low = col_expr.name.lower()
            t_qual = (col_expr.table or "").lower()
            if t_qual:
                cand_sources = [sources[t_qual]] if t_qual in sources else []
            else:
                cand_sources = list(sources.values())
            for s in cand_sources:
                if isinstance(s, dict):
                    if c_low in s:
                        out_map.setdefault(out_col, []).extend(s[c_low])
                else:
                    out_map.setdefault(out_col, []).append((s, c_low))
    return out_map

__all__ = [
    "SQL_TO_LOOKML_DOC",
    "LookmlAggregateTableMatch",
    "LookmlExploreFieldMatch",
    "LookmlExploreQueryMatch",
    "LookmlFieldMatch",
    "LookmlQueryFieldUsage",
    "LookmlSourceLocation",
    "LookmlTestMatch",
    "LookmlUsageMatch",
    "LookmlViewMatch",
    "QueryLookmlMapping",
    "SqlLookmlCompareResult",
    "SqlToLookmlResult",
    "parse_sql_to_lookml",
]


def _make_location(file: str, pos: list[int] | None) -> LookmlSourceLocation | None:
    if not pos or len(pos) < 4:
        return None
    p = [int(x) for x in pos[:4]]
    return LookmlSourceLocation(
        file=file,
        line=p[0] + 1,
        end_line=p[2] + 1,
        position=p,
    )


def _parse_lookml_table_name(
    sql_table_name: str | None, view_name: str
) -> TableRef:
    raw = (sql_table_name or view_name).strip().rstrip(";").strip()
    try:
        tbl = sqlglot.to_table(raw)
        if isinstance(tbl, exp.Table) and tbl.name:
            return _split_table_ref(tbl)
    except Exception:  # noqa: BLE001, S110
        pass
    parts = [p.strip("`\"'[] ") for p in raw.split(".") if p.strip("`\"'[] ")]
    cat, db, name = ([None, None, *(parts or [view_name])])[-3:]
    return TableRef(catalog=cat, db=db, name=name or view_name)


def _run_sandbox_json(code: str) -> Any:
    try:
        import click

        from lkr.auth_service import get_auth
        from lkr.classes import LkrCtxObj
        from lkr.codemode.main import run_python_code

        click_ctx = click.get_current_context(silent=True)
        ctx_lkr = (
            click_ctx.obj.get("ctx_lkr")
            if click_ctx and isinstance(click_ctx.obj, dict)
            else None
        ) or LkrCtxObj(force_oauth=False)
        if (
            ctx_lkr.use_sdk != "api_key"
            and not get_auth(ctx_lkr).get_current_instance()
        ):
            return None
        res_str = run_python_code(code, ctx_lkr=ctx_lkr)
        if not res_str:
            return None
        data = json.loads(res_str)
        if (
            isinstance(data, dict)
            and "result" in data
            and isinstance(data["result"], dict)
        ):
            return data["result"]
        return data
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Sandbox lookup failed: {e}")
        return None


# in-memory lru_cache for connection/table metadata per process; no local file cache
@lru_cache(maxsize=128)
def _fetch_connection_metadata_sandbox(conn_name: str) -> dict[str, Any] | None:
    res = _run_sandbox_json(
        f"c = connection({json.dumps(conn_name)})\n"
        "return {'database': c.get('database'), 'schema': c.get('schema'), 'dialect_name': c.get('dialect_name')}"
    )
    return res if isinstance(res, dict) else None


@lru_cache(maxsize=128)
def _fetch_table_columns_sandbox(
    conn_name: str, db: str | None, schema: str | None, table: str
) -> dict[str, str] | None:
    res = _run_sandbox_json(
        f"res = connection_columns({json.dumps(conn_name)}, database={json.dumps(db)}, "
        f"schema_name={json.dumps(schema)}, table_names={json.dumps(table)})\n"
        "return {c['name'].lower(): (c.get('data_type') or 'UNKNOWN') "
        "for t in (res or []) for c in (t.get('columns') or []) if c.get('name')}"
    )
    return res if isinstance(res, dict) and res else None


def _coerce_table(
    tbl: TableRef, db: str | None, schema: str | None, err_msg: str
) -> TableRef:
    if not tbl.db and not tbl.catalog and not schema and not db:
        raise ValueError(err_msg)
    return _apply_default_db_schema(tbl, db, schema)


def _tables_match(sql_tbl: TableRef, view_tbl: TableRef) -> bool:
    if sql_tbl.name.lower() != view_tbl.name.lower():
        return False
    if (sql_tbl.db or "").lower() != (view_tbl.db or "").lower():
        return False
    return (sql_tbl.catalog or "").lower() == (view_tbl.catalog or "").lower()


def _field_matches_column(
    col_name: str,
    field_name: str,
    field_sql: str | None,
    field_type: str,
    timeframes: list[str] | None = None,
) -> bool:
    col_lower = col_name.lower()
    if field_sql:
        clean_sql = field_sql.strip()
        pattern = rf"\$\{{TABLE\}}\s*\.\s*[`\"'\[]?{re.escape(col_name)}[`\"'\]]?(?:\b|$)"
        if re.search(pattern, clean_sql, flags=re.IGNORECASE):
            return True
        if clean_sql.strip("`\"'[] ").lower() == col_lower:
            return True
    elif field_type in ("dimension", "dimension_group") and field_name.lower() == col_lower:
        return True

    if not _extract_lookml_refs(field_sql):
        if field_name.lower() == col_lower:
            return True
        if field_type == "dimension_group" and timeframes:
            for tf in timeframes:
                if f"{field_name}_{tf}".lower() == col_lower:
                    return True
    return False




def _find_explores_for_field(
    model_name: str,
    model_obj: LookmlModel,
    view_name: str,
    field_name: str,
    field_type: str,
    timeframes: list[str] | None,
    required_ext_aliases: set[str],
    exp_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
) -> list[LookmlExploreFieldMatch]:
    matches: list[LookmlExploreFieldMatch] = []
    model_views = model_obj.view or {}
    candidate_names = {field_name.lower()}
    if field_type == "dimension_group" and timeframes:
        candidate_names |= {f"{field_name}_{tf}".lower() for tf in timeframes}

    for exp_name, exp_val in (model_obj.explore or {}).items():
        for exp_obj in _as_list(exp_val):
            if not isinstance(exp_obj, LookmlExplore):
                continue

            exp_chain = _build_chain(exp_name, exp_base_decls, exp_ref_decls)
            base_view_name, base_alias, exp_file, exp_pos = _resolve_explore_base(
                exp_name, exp_obj, exp_chain, model_views
            )

            views_by_alias: dict[str, LookmlView] = {}
            bv = model_views.get(base_view_name)
            if isinstance(bv, LookmlView):
                views_by_alias[base_alias] = bv

            for j_name, j_obj in (exp_obj.join or {}).items():
                jv_name = j_obj.from_ or j_obj.view_name or j_name
                jv = model_views.get(jv_name)
                if isinstance(jv, LookmlView):
                    views_by_alias[j_name] = jv

            explore_aliases_lower = {a.lower() for a in views_by_alias}

            if (
                base_view_name == view_name
                and (required_ext_aliases - {base_alias.lower()})
                <= explore_aliases_lower
                and _is_field_allowed_by_spec(
                    exp_obj.fields,
                    base_alias,
                    candidate_names,
                    views_by_alias,
                    base_alias,
                )
            ):
                matches.append(
                    LookmlExploreFieldMatch(
                        model_name=model_name,
                        explore_name=exp_name,
                        field=f"{base_alias}.{field_name}",
                        view_alias=base_alias,
                        view_name=view_name,
                        join_name=None,
                        file=exp_file,
                        line=exp_pos[0] + 1,
                        end_line=exp_pos[2] + 1,
                        position=exp_pos,
                        join_location=None,
                    )
                )

            for j_name, j_obj in (exp_obj.join or {}).items():
                jv_name = j_obj.from_ or j_obj.view_name or j_name
                if jv_name != view_name:
                    continue
                if (
                    not (required_ext_aliases - {j_name.lower()})
                    <= explore_aliases_lower
                ):
                    continue
                if not _is_field_allowed_by_spec(
                    j_obj.fields, j_name, candidate_names, views_by_alias, j_name
                ):
                    continue
                if not _is_field_allowed_by_spec(
                    exp_obj.fields, j_name, candidate_names, views_by_alias, base_alias
                ):
                    continue

                j_loc: LookmlSourceLocation | None = None
                for fpath, _, p_dict in exp_chain:
                    join_pos_map = p_dict.get("join", {})
                    if isinstance(join_pos_map, dict) and j_name in join_pos_map:
                        jp = join_pos_map[j_name]
                        if isinstance(jp, dict) and "$p" in jp:
                            j_loc = _make_location(fpath, jp["$p"])

                matches.append(
                    LookmlExploreFieldMatch(
                        model_name=model_name,
                        explore_name=exp_name,
                        field=f"{j_name}.{field_name}",
                        view_alias=j_name,
                        view_name=view_name,
                        join_name=j_name,
                        file=exp_file,
                        line=exp_pos[0] + 1,
                        end_line=exp_pos[2] + 1,
                        position=exp_pos,
                        join_location=j_loc,
                    )
                )

    return matches


def _extract_query_columns(
    parsed_query: ParsedQuery,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
    exclude_join_on: bool = False,
    split_count_cols: bool = False,
) -> list[tuple[str | None, str]]:
    seen: set[tuple[str | None, str]] = set()
    result: list[tuple[str | None, str]] = []

    def _add(tbl: str | None, col: str) -> None:
        if col == "*":
            return
        key = ((tbl or "").lower() or None, col.lower())
        if col and key not in seen:
            seen.add(key)
            result.append((tbl or None, col))

    if not schema and not exclude_join_on and not split_count_cols:
        for c in parsed_query.columns:
            if c.column:
                _add(c.table, c.column)

    try:
        eff_dialect = dialect or ("bigquery" if "`" in parsed_query.raw_sql else None)
        for expr in sqlglot.parse(parsed_query.raw_sql, read=eff_dialect):
            if expr is not None:
                opt_expr = _optimize_stars(
                    expr,
                    dialect=eff_dialect,
                    schema=schema,
                    default_db=default_db,
                    default_schema=default_schema,
                )
                on_col_ids = (
                    {
                        id(c)
                        for j in opt_expr.find_all(exp.Join)
                        if j.args.get("on")
                        for c in j.args["on"].find_all(exp.Column)
                    }
                    if exclude_join_on
                    else set()
                )
                cnt_col_ids: set[int] = set()
                for cnt_expr in opt_expr.find_all(exp.Count):
                    if isinstance(cnt_expr.parent, exp.Filter):
                        continue
                    arg = cnt_expr.this
                    if isinstance(arg, (exp.Star, exp.Literal)):
                        _add(None, "COUNT(*)")
                    elif isinstance(arg, exp.Column) and isinstance(arg.this, exp.Star):
                        _add(
                            arg.table or None,
                            f"COUNT({arg.table}.*)" if arg.table else "COUNT(*)",
                        )
                    elif split_count_cols:
                        c = (
                            arg
                            if isinstance(arg, exp.Column)
                            else arg.expressions[0]
                            if isinstance(arg, exp.Distinct)
                            and len(arg.expressions) == 1
                            and isinstance(arg.expressions[0], exp.Column)
                            else None
                        )
                        if (
                            c is not None
                            and c.name
                            and not isinstance(c.this, exp.Star)
                            and id(c) not in on_col_ids
                        ):
                            cnt_col_ids.add(id(c))
                            _add(c.table or None, f"COUNT({c.name})")
                for col_expr in opt_expr.find_all(exp.Column):
                    if (
                        id(col_expr) not in on_col_ids
                        and id(col_expr) not in cnt_col_ids
                        and col_expr.name
                        and col_expr.arg_key != "except_"
                        and not isinstance(col_expr.this, exp.Star)
                    ):
                        _add(col_expr.table or None, col_expr.name)
    except Exception:  # noqa: BLE001, S110
        pass

    if not result:
        for c in parsed_query.columns:
            if c.column:
                _add(c.table, c.column)

    return result


class _FieldProperty:
    def __init__(
        self,
        prop_type: str,
        prop_key: str,
        expr: str | None,
        refs: list[str],
        sql_text: str | None = None,
    ) -> None:
        self.prop_type = prop_type
        self.prop_key = prop_key
        self.sub_key = prop_key
        self.expr = expr
        self.refs = refs
        self.sql_text = sql_text


class _FieldMatchInfo:
    def __init__(
        self,
        sql_table: str,
        sql_column: str,
        via: list[str],
        ext_aliases: set[str],
        matched_property: str,
        property_path: str,
        expression: str | None,
        sub_key: str,
    ) -> None:
        self.sql_table = sql_table
        self.sql_column = sql_column
        self.via = via
        self.ext_aliases = ext_aliases
        self.matched_property = matched_property
        self.property_path = property_path
        self.expression = expression
        self.sub_key = sub_key


def _extract_filter_refs(filters: Any) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for f in _as_list(filters):
        if isinstance(f, LookmlFilter):
            for item in _as_list(f.field):
                if item:
                    val_str = str(f.value) if f.value is not None else ""
                    refs.append((str(item).strip(), f"{item}: {val_str}".strip()))
            for k, v in (f.model_extra or {}).items():
                if not k.startswith("$") and not k.startswith("_") and k != "type":
                    refs.append((k.strip(), f"{k}: {v}".strip()))
        elif isinstance(f, dict):
            if "field" in f and isinstance(f["field"], str):
                fld = f["field"].strip()
                val = f.get("value", "")
                refs.append((fld, f"{fld}: {val}".strip()))
            for k, v in f.items():
                if k not in ("field", "value", "$p", "$s", "$type", "$name", "type"):
                    refs.append((k.strip(), f"{k}: {v}".strip()))
    return refs


def _get_field_properties(ftype: str, fname: str, fobj: Any) -> list[_FieldProperty]:
    props: list[_FieldProperty] = []
    if getattr(fobj, "sql", None):
        raw_sql = str(fobj.sql)
        props.append(
            _FieldProperty(
                prop_type=f"{ftype}.sql",
                prop_key="sql",
                expr=raw_sql.strip(),
                refs=_extract_lookml_refs(raw_sql),
                sql_text=raw_sql,
            )
        )
    if case_obj := getattr(fobj, "case", None):
        for w in _as_list(getattr(case_obj, "when", None)):
            if w and getattr(w, "sql", None):
                raw_wsql = str(w.sql)
                props.append(
                    _FieldProperty(
                        prop_type=f"{ftype}.case.when.sql",
                        prop_key="case.when.sql",
                        expr=raw_wsql.strip(),
                        refs=_extract_lookml_refs(raw_wsql),
                        sql_text=raw_wsql,
                    )
                )
    if ftype == "measure" and getattr(fobj, "filters", None):
        for ref_field, filter_repr in _extract_filter_refs(fobj.filters):
            props.append(
                _FieldProperty(
                    prop_type="measure.filters",
                    prop_key="filters",
                    expr=filter_repr,
                    refs=[ref_field],
                    sql_text=None,
                )
            )
    for attr, p_suffix in (("sql_start", "sql_start"), ("sql_end", "sql_end")):
        if val := getattr(fobj, attr, None):
            raw_val = str(val)
            props.append(
                _FieldProperty(
                    prop_type=f"{ftype}.{p_suffix}",
                    prop_key=p_suffix,
                    expr=raw_val.strip(),
                    refs=_extract_lookml_refs(raw_val),
                    sql_text=raw_val,
                )
            )
    for attr, p_suffix in (("sql_latitude", "sql_latitude"), ("sql_longitude", "sql_longitude")):
        if val := getattr(fobj, attr, None):
            raw_val = str(val)
            props.append(
                _FieldProperty(
                    prop_type=f"{ftype}.{p_suffix}",
                    prop_key=p_suffix,
                    expr=raw_val.strip(),
                    refs=_extract_lookml_refs(raw_val),
                    sql_text=raw_val,
                )
            )
    if val := getattr(fobj, "sql_distinct_key", None):
        raw_val = str(val)
        props.append(
            _FieldProperty(
                prop_type=f"{ftype}.sql_distinct_key",
                prop_key="sql_distinct_key",
                expr=raw_val.strip(),
                refs=_extract_lookml_refs(raw_val),
                sql_text=raw_val,
            )
        )
    return props


def _find_field_prop_location(
    chain: list[tuple[str, Any, dict[str, Any]]],
    ftype: str,
    fname: str,
    sub_key: str,
) -> LookmlSourceLocation | None:
    for fpath, _, p_dict in chain:
        type_pos = p_dict.get(ftype, {})
        if not isinstance(type_pos, dict) or fname not in type_pos:
            continue
        f_pos = type_pos[fname]
        if not isinstance(f_pos, dict):
            continue
        if sub_key == "case.when.sql":
            case_p = f_pos.get("case", {})
            if isinstance(case_p, dict):
                when_p = case_p.get("when", {})
                if isinstance(when_p, dict):
                    if "sql" in when_p and isinstance(when_p["sql"], dict) and "$p" in when_p["sql"]:
                        return _make_location(fpath, when_p["sql"]["$p"])
                    if "$p" in when_p:
                        return _make_location(fpath, when_p["$p"])
                elif isinstance(when_p, list) and when_p:
                    for item in when_p:
                        if isinstance(item, dict) and "sql" in item and "$p" in item["sql"]:
                            return _make_location(fpath, item["sql"]["$p"])
                if "$p" in case_p:
                    return _make_location(fpath, case_p["$p"])
        elif sub_key in f_pos and isinstance(f_pos[sub_key], dict) and "$p" in f_pos[sub_key]:
            return _make_location(fpath, f_pos[sub_key]["$p"])
        elif "sql" in f_pos and isinstance(f_pos["sql"], dict) and "$p" in f_pos["sql"]:
            return _make_location(fpath, f_pos["sql"]["$p"])
    return None


def _chain_prop_loc(
    chain: list[tuple[str, Any, dict[str, Any]]],
    prop_path: list[str],
    default_file: str,
    default_pos: list[int],
) -> LookmlSourceLocation:
    for fpath, _, p_dict in chain:
        curr: Any = p_dict
        found = True
        for part in prop_path:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                found = False
                break
        if (
            found
            and isinstance(curr, dict)
            and "$p" in curr
            and (loc := _make_location(fpath, curr["$p"]))
        ):
            return loc
    if len(prop_path) > 1:
        for fpath, _, p_dict in chain:
            curr = p_dict
            found = True
            for part in prop_path[:-1]:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                else:
                    found = False
                    break
            if (
                found
                and isinstance(curr, dict)
                and "$p" in curr
                and (loc := _make_location(fpath, curr["$p"]))
            ):
                return loc
    return (
        _make_location(default_file, default_pos)
        or LookmlSourceLocation(
            file=default_file, line=1, end_line=1, position=default_pos
        )
    )


def _find_datagroup_location(
    positions: LookmlPositions | None,
    model_name: str,
    dg_name: str,
    sub_key: str,
) -> LookmlSourceLocation:
    pos_models = positions.model if positions and positions.model else {}
    pos_files = positions.file if positions and positions.file else {}

    m_dg = pos_models.get(model_name, {}).get("datagroup", {}).get(dg_name, {})
    if isinstance(m_dg, dict):
        if sub_key in m_dg and isinstance(m_dg[sub_key], dict) and "$p" in m_dg[sub_key]:
            raw_p = m_dg[sub_key]["$p"]
            p = [int(x) for x in (raw_p[1:5] if len(raw_p) >= 5 else raw_p[:4])]
            return LookmlSourceLocation(
                file=f"{model_name}.model.lkml", line=p[0] + 1, end_line=p[2] + 1, position=p
            )
        if "$p" in m_dg:
            raw_p = m_dg["$p"]
            p = [int(x) for x in (raw_p[1:5] if len(raw_p) >= 5 else raw_p[:4])]
            return LookmlSourceLocation(
                file=f"{model_name}.model.lkml", line=p[0] + 1, end_line=p[2] + 1, position=p
            )

    for f_key, f_val in pos_files.items():
        if isinstance(f_val, dict) and "datagroup" in f_val:
            dg_dict = f_val["datagroup"].get(dg_name, {})
            if isinstance(dg_dict, dict):
                f_name = f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                if (
                    sub_key in dg_dict
                    and isinstance(dg_dict[sub_key], dict)
                    and "$p" in dg_dict[sub_key]
                    and (loc := _make_location(f_name, dg_dict[sub_key]["$p"]))
                ):
                    return loc
                if "$p" in dg_dict and (loc := _make_location(f_name, dg_dict["$p"])):
                    return loc

    return LookmlSourceLocation(file=f"{model_name}.model.lkml", line=1, end_line=1, position=[0, 0, 0, 0])


def _iter_view_fields(
    view_obj: LookmlView,
) -> list[tuple[str, str, Any]]:
    f_val = view_obj.filter
    filter_dict = (
        f_val
        if isinstance(f_val, dict)
        else {f.name_: f for f in _as_list(f_val) if getattr(f, "name_", None)}
    )
    return [
        (ftype, fname, fobj)
        for ftype, fdict in (
            ("dimension", view_obj.dimension or {}),
            ("dimension_group", view_obj.dimension_group or {}),
            ("measure", view_obj.measure or {}),
            ("filter", filter_dict),
        )
        for fname, fobj in fdict.items()
        if fobj is not None
    ]


def _get_view_field(view_obj: LookmlView, ftype: str, fname: str) -> Any:
    return next(
        (fobj for ft, fn, fobj in _iter_view_fields(view_obj) if ft == ftype and fn == fname),
        None,
    )


def _extract_view_columns(view_obj: LookmlView) -> dict[str, str]:
    cols: dict[str, str] = {}
    for ftype, fname, fobj in _iter_view_fields(view_obj):
        for p in _get_field_properties(ftype, fname, fobj):
            if p.sql_text:
                for m in _TABLE_COL_RE.finditer(p.sql_text):
                    cols[(m.group(1) or m.group(2)).lower()] = "UNKNOWN"
        f_subtype = str(getattr(fobj, "type", "") or "")
        if (
            not getattr(fobj, "sql", None)
            and ftype in ("dimension", "dimension_group")
            and f_subtype not in ("location", "distance", "duration")
            and not f_subtype.startswith("duration_")
            and getattr(fobj, "case", None) is None
        ):
            cols[fname.lower()] = "UNKNOWN"
    return cols


class _TestInfo:
    def __init__(
        self,
        model_name: str,
        test_name: str,
        explore_name: str,
        file: str,
        line: int,
        end_line: int,
        position: list[int],
        referenced_tokens: set[str],
        col_aliases: dict[str, str],
    ) -> None:
        self.model_name = model_name
        self.test_name = test_name
        self.explore_name = explore_name
        self.file = file
        self.line = line
        self.end_line = end_line
        self.position = position
        self.referenced_tokens = referenced_tokens
        self.col_aliases = col_aliases


def _extract_test_refs(
    t_obj: LookmlTest,
) -> tuple[str, set[str], dict[str, str]]:
    explore_name = ""
    referenced_tokens: set[str] = set()
    col_aliases: dict[str, str] = {}

    es_dict = t_obj.explore_source or {}
    es_items = (
        list(es_dict.items())
        if isinstance(es_dict, dict)
        else ([(es_dict.name_ or "", es_dict)] if hasattr(es_dict, "name_") else [])
    )

    for exp_name, es in es_items:
        explore_name = exp_name
        if not es:
            continue

        for col_name, col_obj in (es.column or {}).items():
            c_clean = col_name.strip().lower()
            f_clean = (
                col_obj.field.strip().lower()
                if col_obj and col_obj.field
                else c_clean
            )
            referenced_tokens.add(f_clean)
            col_aliases[c_clean] = f_clean

        for dcol_obj in (es.derived_column or {}).values():
            if dcol_obj and dcol_obj.sql:
                for r in _extract_lookml_refs(dcol_obj.sql):
                    referenced_tokens.add(r.strip().lower())

        for f in _as_list(es.filters):
            if isinstance(f, LookmlFilter):
                for item in _as_list(f.field):
                    if item:
                        referenced_tokens.add(str(item).strip().lower())
                for k in f.model_extra or {}:
                    if not k.startswith("$") and not k.startswith("_"):
                        referenced_tokens.add(k.strip().lower())
            elif isinstance(f, dict):
                if "field" in f and isinstance(f["field"], str):
                    referenced_tokens.add(f["field"].strip().lower())
                for k in f:
                    if k not in (
                        "field",
                        "value",
                        "$p",
                        "$s",
                        "$type",
                        "$name",
                        "type",
                    ):
                        referenced_tokens.add(k.strip().lower())

        if es.expression_custom_filter:
            for r in _extract_lookml_refs(es.expression_custom_filter):
                referenced_tokens.add(r.strip().lower())

        for s in (*_as_list(es.sorts), *_as_list(es.sort)):
            if isinstance(s, dict) and "field" in s:
                referenced_tokens.add(str(s["field"]).strip().lower())

        for bf in _as_list(es.bind_filters):
            for attr in ("from_field", "to_field"):
                if fld := getattr(bf, attr, None):
                    referenced_tokens.add(fld.strip().lower())

    for a in _as_list(t_obj.assert_):
        if a and (expr := getattr(a, "expression", None)):
            for r in _extract_lookml_refs(expr):
                rc = r.strip().lower()
                referenced_tokens.add(rc)
                if rc in col_aliases:
                    referenced_tokens.add(col_aliases[rc])

    return explore_name, referenced_tokens, col_aliases


def _collect_model_test_infos(
    model_name: str,
    model_obj: LookmlModel,
    test_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    test_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    positions: LookmlPositions | None = None,
) -> list[_TestInfo]:
    tests_map: dict[str, LookmlTest] = {}
    if isinstance(model_obj.test, dict):
        for t_name, t_val in model_obj.test.items():
            for item in _as_list(t_val):
                if isinstance(item, LookmlTest):
                    tests_map[t_name] = item

    for t_name, decl_list in test_base_decls.items():
        if t_name not in tests_map:
            for _, item, _ in decl_list:
                if isinstance(item, LookmlTest):
                    tests_map[t_name] = item
                    break

    pos_files = positions.file if positions and positions.file else {}
    pos_models = positions.model if positions and positions.model else {}

    test_infos: list[_TestInfo] = []
    for test_name, t_obj in tests_map.items():
        chain = _build_chain(test_name, test_base_decls, test_ref_decls)
        test_file, test_pos = _chain_root_pos(chain, test_name)

        if not test_file or test_pos == [0, 0, 0, 0]:
            for f_key, f_val in pos_files.items():
                if isinstance(f_val, dict) and "test" in f_val:
                    t_pos_dict = f_val["test"].get(test_name)
                    if isinstance(t_pos_dict, dict) and "$p" in t_pos_dict:
                        test_file = (
                            f_key if f_key.endswith(".lkml") else f"{f_key}.lkml"
                        )
                        test_pos = [int(x) for x in t_pos_dict["$p"][:4]]
                        break

        if test_pos == [0, 0, 0, 0]:
            m_tests = pos_models.get(model_name, {}).get("test", {})
            if isinstance(m_tests, dict) and test_name in m_tests:
                t_pos_dict = m_tests[test_name]
                if isinstance(t_pos_dict, dict) and "$p" in t_pos_dict:
                    raw_p = t_pos_dict["$p"]
                    test_pos = [
                        int(x)
                        for x in (raw_p[1:5] if len(raw_p) >= 5 else raw_p[:4])
                    ]

        if not test_file:
            fp = (
                getattr(t_obj, "file_path", None)
                or getattr(model_obj, "file_path", None)
                or ""
            )
            test_file = (
                fp[0]
                if isinstance(fp, list) and fp
                else (fp or f"{model_name}.model.lkml")
            )

        line = test_pos[0] + 1 if test_pos else 1
        end_line = test_pos[2] + 1 if test_pos and len(test_pos) > 2 else line
        explore_name, referenced_tokens, col_aliases = _extract_test_refs(t_obj)

        test_infos.append(
            _TestInfo(
                model_name=model_name,
                test_name=test_name,
                explore_name=explore_name,
                file=test_file,
                line=line,
                end_line=end_line,
                position=test_pos or [0, 0, 0, 0],
                referenced_tokens=referenced_tokens,
                col_aliases=col_aliases,
            )
        )

    return test_infos


def _find_tests_for_field(
    model_name: str,
    view_name: str,
    field_name: str,
    field_type: str,
    timeframes: list[str] | None,
    explores: list[LookmlExploreFieldMatch],
    test_infos: list[_TestInfo],
) -> list[LookmlTestMatch]:
    matches: list[LookmlTestMatch] = []
    view_lower = view_name.lower()
    field_lower = field_name.lower()

    explores_by_name: dict[str, list[LookmlExploreFieldMatch]] = {}
    for em in explores:
        explores_by_name.setdefault(em.explore_name.lower(), []).append(em)

    field_variants = (
        [(f"{field_name}_{tf}", f"{field_lower}_{tf.lower()}") for tf in timeframes]
        if field_type == "dimension_group" and timeframes
        else [(field_name, field_lower)]
    )

    for ti in test_infos:
        exp_matches = explores_by_name.get(ti.explore_name.lower(), [])
        matched_var_name: str | None = None
        for v_name, v_lower in field_variants:
            tokens = {f"{view_lower}.{v_lower}"}
            if exp_matches:
                for em in exp_matches:
                    tokens.add(
                        em.field.lower()
                        if v_name == field_name
                        else f"{em.view_alias.lower()}.{v_lower}"
                    )
                    tokens.add(v_lower)
            elif ti.explore_name.lower() == view_lower:
                tokens.add(v_lower)

            if tokens & ti.referenced_tokens:
                matched_var_name = v_name
                break

        if not matched_var_name:
            continue

        base_prefix = exp_matches[0].view_alias if exp_matches else view_name
        matched_field_name = f"{base_prefix}.{matched_var_name}"

        matches.append(
            LookmlTestMatch(
                model_name=ti.model_name,
                test_name=ti.test_name,
                explore_name=ti.explore_name,
                field=matched_field_name,
                fields=[matched_field_name],
                file=ti.file,
                line=ti.line,
                end_line=ti.end_line,
                position=ti.position,
            )
        )

    return matches


def _collect_query_block_fields(
    q_dict: dict[str, Any], base_alias: str
) -> list[LookmlQueryFieldUsage]:
    usages: list[LookmlQueryFieldUsage] = []
    seen: set[tuple[str, str]] = set()

    def _add(ref: str, loc: str) -> None:
        tok = re.sub(r"\s+(?:asc|desc)\s*$", "", ref.strip(), flags=re.IGNORECASE)
        if not tok:
            return
        qual = _qualify_field_ref(tok, base_alias)
        if (qual, loc) not in seen:
            seen.add((qual, loc))
            usages.append(LookmlQueryFieldUsage(field=qual, used_in=loc))

    for key in ("dimensions", "measures", "pivots", "filters", "sorts"):
        val = q_dict.get(key)
        for item in val if isinstance(val, list) else ([val] if val is not None else []):
            if isinstance(item, dict):
                for k in item:
                    if not str(k).startswith("$"):
                        _add(str(k), key)
            elif isinstance(item, str):
                _add(item.split(":", 1)[0], key)

    return usages


def _chain_sub_loc(
    exp_chain: list[tuple[str, Any, dict[str, Any]]],
    block_key: str,
    item_name: str,
    default_file: str,
    default_pos: list[int],
) -> LookmlSourceLocation:
    loc: LookmlSourceLocation | None = None
    for fpath, _, p_dict in exp_chain:
        sub_map = p_dict.get(block_key, {})
        if isinstance(sub_map, dict) and item_name in sub_map:
            sp = sub_map[item_name]
            if isinstance(sp, dict) and "$p" in sp:
                loc = _make_location(fpath, sp["$p"])
    return (
        loc
        or _make_location(default_file, default_pos)
        or LookmlSourceLocation(
            file=default_file, line=1, end_line=1, position=default_pos
        )
    )


def _preprocess_dt_sql(
    raw_sql: str,
    vname: str,
    vobj: LookmlView,
    model_views: dict[str, LookmlView],
    alias_to_view: dict[str, str],
) -> str:
    def _resolve_field_sql(t_view: str, qual: str, fname: str, depth: int = 0) -> str:
        tv = (
            model_views.get(t_view)
            or model_views.get(alias_to_view.get(t_view.lower(), ""))
            if depth <= 6
            else None
        )
        fl = fname.lower()
        fobj = next(
            (
                fo
                for _, fn, fo in (_iter_view_fields(tv) if tv else ())
                if fn.lower() == fl
                or (
                    isinstance(fo, LookmlDimensionGroup)
                    and any(
                        c.lower() == fl
                        for c in (
                            *(f"{fn}_{tf}" for tf in (fo.timeframes or ())),
                            *(f"{iv}s_{fn}" for iv in (fo.intervals or ())),
                        )
                    )
                )
            ),
            None,
        )
        if fobj is None:
            return f"{qual}.{fname}"
        whens = [
            f"WHEN {w.sql} THEN 1"
            for w in _as_list(getattr(getattr(fobj, "case", None), "when", None))
            if getattr(w, "sql", None)
        ]
        expr = (
            getattr(fobj, "sql", None)
            or (f"CASE {' '.join(whens)} END" if whens else None)
            or (
                f"COALESCE({getattr(fobj, 'sql_start', None) or '1'}, {getattr(fobj, 'sql_end', None) or '1'})"
                if getattr(fobj, "sql_start", None) or getattr(fobj, "sql_end", None)
                else None
            )
        )
        if not expr:
            return "COUNT(*)" if getattr(fobj, "type", None) == "count" else f"{qual}.{fname}"
        s = _LOOKML_REF_RE.sub(
            lambda m: _expand_tok(m.group(1) or m.group(2), t_view, qual, depth + 1),
            str(expr).strip(),
        )
        return f"({s})"

    def _expand_tok(ref: str, cur_view: str, cur_qual: str, depth: int = 0) -> str:
        ru = ref.upper()
        if ru == "TABLE":
            return cur_qual
        if ru.endswith(".SQL_TABLE_NAME"):
            return f"__lkml_tbl_{ref.split('.', 1)[0]}"
        if "." in ref:
            pfx, fld = ref.split(".", 1)
            if pfx in ("_view", "_field", "_model", "_explore"):
                return _resolve_field_sql(cur_view, cur_qual, fld, depth)
            return _resolve_field_sql(alias_to_view.get(pfx.lower(), pfx), pfx, fld, depth)
        return _resolve_field_sql(cur_view, cur_qual, ref, depth)

    s = raw_sql.strip().rstrip(";").strip()
    if exts := [e for e in _as_list(vobj.extends) if isinstance(e, str)]:
        s = re.sub(r"\$\{\s*EXTENDED\s*\}\s*\.\s*\*", "*", s, flags=re.IGNORECASE)
        s = re.sub(
            r"\(?\s*\$\{\s*EXTENDED\s*\}\s*\)?",
            f"__lkml_tbl_{exts[-1]}",
            s,
            flags=re.IGNORECASE,
        )
    s = re.sub(r"\{\{\s*(?:_table|_view\._name)\s*\}\}", vname, s)
    s = re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\._name\s*\}\}", r"\1", s)
    s = _LOOKML_REF_RE.sub(
        lambda m: _expand_tok(m.group(1) or m.group(2), vname, vname), s
    )
    s = re.sub(r"\{%\s*parameter\s+[^%]+%\}", "1", s, flags=re.IGNORECASE)
    s = re.sub(r"\{%.*?%\}", " ", s, flags=re.DOTALL)
    return re.sub(r"\{\{.*?\}\}", "1", s, flags=re.DOTALL)


def _match_model_views(
    pq: ParsedQuery,
    model_name: str,
    model_obj: LookmlModel,
    view_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    view_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    exp_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]],
    test_base_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]] | None = None,
    test_ref_decls: dict[str, list[tuple[str, Any, dict[str, Any]]]] | None = None,
    positions: LookmlPositions | None = None,
    lkml_conn: str | None = None,
    lkml_db: str | None = None,
    lkml_schema: str | None = None,
    dialect: str | None = None,
    sql_db: str | None = None,
    sql_schema: str | None = None,
) -> tuple[list[LookmlViewMatch], list[LookmlUsageMatch]]:
    eff_conn = lkml_conn or model_obj.connection
    eff_db, eff_schema = lkml_db, lkml_schema
    meta_fetched = bool(eff_db and eff_schema) or not eff_conn

    def _coerce_lkml_table(tbl: TableRef, err_msg: str) -> TableRef:
        nonlocal eff_db, eff_schema, meta_fetched
        if (not tbl.catalog or not tbl.db) and not meta_fetched:
            meta_fetched = True
            meta = _fetch_connection_metadata_sandbox(eff_conn) if eff_conn else None
            eff_db = eff_db or (meta.get("database") if meta else None)
            eff_schema = eff_schema or (meta.get("schema") if meta else None)
        return _coerce_table(tbl, eff_db, eff_schema, err_msg)

    model_views: dict[str, LookmlView] = {}
    for k, v in (model_obj.view or {}).items():
        for view_obj in _as_list(v):
            if isinstance(view_obj, LookmlView):
                model_views[k] = view_obj
    view_chains = {
        vname: _build_chain(vname, view_base_decls, view_ref_decls)
        for vname in model_views
    }
    for vname, chain in view_chains.items():
        vobj = model_views[vname]
        if (
            vobj.derived_table
            and vobj.sql_table_name
            and next(
                (
                    bool(getattr(v, "derived_table", None))
                    for _, v, _ in reversed(chain)
                    if getattr(v, "derived_table", None)
                    or getattr(v, "sql_table_name", None)
                ),
                False,
            )
        ):
            model_views[vname] = vobj.model_copy(update={"sql_table_name": None})
    self_names_by_view = {
        vname: {v.name_.lower() for _, v, _ in chain if v.name_} | {vname.lower()}
        for vname, chain in view_chains.items()
    }

    aliases_for_view: dict[str, set[str]] = {
        vname: {vname.lower()} for vname in model_views
    }
    alias_to_view: dict[str, str] = {vname.lower(): vname for vname in model_views}
    for exp_name, exp_obj in (model_obj.explore or {}).items():
        if not isinstance(exp_obj, LookmlExplore):
            continue
        exp_chain = _build_chain(exp_name, exp_base_decls, exp_ref_decls)
        b_view, b_alias, _, _ = _resolve_explore_base(
            exp_name, exp_obj, exp_chain, model_views
        )
        aliases_for_view.setdefault(b_view, {b_view.lower()}).add(b_alias.lower())
        alias_to_view.setdefault(b_alias.lower(), b_view)
        for j_name, j_obj in (exp_obj.join or {}).items():
            jv_name = j_obj.from_ or j_obj.view_name or j_name
            aliases_for_view.setdefault(jv_name, {jv_name.lower()}).add(j_name.lower())
            alias_to_view.setdefault(j_name.lower(), jv_name)

    test_infos = _collect_model_test_infos(
        model_name=model_name,
        model_obj=model_obj,
        test_base_decls=test_base_decls or {},
        test_ref_decls=test_ref_decls or {},
        positions=positions,
    )

    # (view_name, ftype, fname) -> list[_FieldMatchInfo]
    matched_fields: dict[
        tuple[str, str, str], list[_FieldMatchInfo]
    ] = {}
    queue: deque[tuple[str, str, str, _FieldMatchInfo]] = deque()
    direct_views: dict[str, str] = {}
    view_order: list[str] = []

    view_cols_by_name = {
        vn: _extract_view_columns(vo) for vn, vo in model_views.items()
    }
    dt_schema: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        "": {
            "": {
                f"__lkml_tbl_{vn.lower()}": dict(cols)
                for vn, cols in view_cols_by_name.items()
                if cols
            }
        }
    }

    ndt_cols_by_view: dict[str, list[tuple[str, str, str]]] = {}
    dt_raw_cols_by_view: dict[str, list[tuple[str, TableRef, str]]] = {}
    for vname, vobj in model_views.items():
        dt = vobj.derived_table
        if not isinstance(dt, LookmlDerivedTable):
            continue
        es_raw = dt.explore_source
        es_items = (
            list(es_raw.items())
            if isinstance(es_raw, dict)
            else [(es_raw.name_ or "", es_raw)]
            if isinstance(es_raw, LookmlExploreSource)
            else []
        )
        for es_name, es in es_items:
            col_map: dict[str, set[tuple[str, str]]] = {}
            for col_name, col_obj in (es.column or {}).items():
                raw_ref = (
                    col_obj.field.strip()
                    if col_obj and col_obj.field
                    else col_name.strip()
                )
                pfx, fld = (
                    raw_ref.split(".", 1) if "." in raw_ref else (es_name, raw_ref)
                )
                col_map.setdefault(col_name.lower(), set()).add(
                    (pfx.strip().lower(), fld.strip().lower())
                )
            dcols = es.derived_column or {}
            changed = bool(dcols)
            while changed:
                changed = False
                for dc_name, dc_obj in dcols.items():
                    if not (dc_obj and dc_obj.sql):
                        continue
                    dc_low = dc_name.lower()
                    new_pairs = {
                        p
                        for c_low, pairs in col_map.items()
                        if re.search(
                            rf"\b{re.escape(c_low)}\b", dc_obj.sql, re.IGNORECASE
                        )
                        for p in pairs
                    } - col_map.get(dc_low, set())
                    if new_pairs:
                        col_map.setdefault(dc_low, set()).update(new_pairs)
                        changed = True
            for c_low, pairs in col_map.items():
                ndt_cols_by_view.setdefault(vname, []).extend(
                    (c_low, *p) for p in pairs
                )
                dt_schema[""][""].setdefault(
                    f"__lkml_tbl_{vname.lower()}", {}
                ).setdefault(c_low, "UNKNOWN")
        if dt.sql:
            clean_dt_sql = _preprocess_dt_sql(
                dt.sql, vname, vobj, model_views, alias_to_view
            )
            dt_dialect = "bigquery" if "`" in clean_dt_sql else None
            try:
                for expr in sqlglot.parse(clean_dt_sql, read=dt_dialect):
                    if expr is None:
                        continue
                    if _has_projection_star(expr):
                        ref_tbls = {
                            t.name.lower()
                            for t in expr.find_all(exp.Table)
                            if t.name and not t.name.lower().startswith("__lkml_tbl_")
                        }
                        for vn, vo in model_views.items():
                            v_cols = view_cols_by_name.get(vn, {})
                            if not v_cols or (
                                getattr(vo, "derived_table", None)
                                and not vo.sql_table_name
                            ):
                                continue
                            raw_vt = _parse_lookml_table_name(vo.sql_table_name, vn)
                            if raw_vt.name.lower() in ref_tbls:
                                try:
                                    vt = _coerce_lkml_table(raw_vt, "")
                                    dt_schema.setdefault(
                                        (vt.catalog or "").lower(), {}
                                    ).setdefault((vt.db or "").lower(), {}).setdefault(
                                        vt.name.lower(), {}
                                    ).update(v_cols)
                                except ValueError:
                                    pass
                    opt_dt = _optimize_stars(
                        expr,
                        dialect=dt_dialect,
                        schema=dt_schema,
                        default_db=eff_db,
                        default_schema=eff_schema,
                    )
                    for out_col, origins in _extract_dt_lineage(opt_dt).items():
                        dt_schema[""][""].setdefault(
                            f"__lkml_tbl_{vname.lower()}", {}
                        ).setdefault(out_col, "UNKNOWN")
                        for src_origin, base_col in origins:
                            if isinstance(src_origin, TableRef):
                                dt_raw_cols_by_view.setdefault(vname, []).append(
                                    (out_col, src_origin, base_col)
                                )
                            else:
                                ndt_cols_by_view.setdefault(vname, []).append(
                                    (out_col, src_origin, base_col)
                                )
            except Exception:  # noqa: BLE001, S110
                pass

    conn_info = f"connection '{eff_conn}'" if eff_conn else "connection"
    lookml_schema: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    db_cols_by_view: dict[str, dict[str, str] | None] = {}
    matched_sources: list[
        tuple[TableRef, str, str, LookmlView, tuple[str, str] | None]
    ] = []

    for sql_tbl in pq.tables:
        raw_table_str = ".".join(
            p for p in (sql_tbl.catalog, sql_tbl.db, sql_tbl.name) if p
        )
        for view_name, view_obj in model_views.items():
            cand_sources: list[tuple[TableRef, tuple[str, str] | None]] = [
                (raw_dt_tbl, (out_col, dt_src_col))
                for out_col, raw_dt_tbl, dt_src_col in dt_raw_cols_by_view.get(
                    view_name, ()
                )
            ]
            if not getattr(view_obj, "derived_table", None) or view_obj.sql_table_name:
                cand_sources.append(
                    (_parse_lookml_table_name(view_obj.sql_table_name, view_name), None)
                )
            for raw_cand_tbl, dt_col_pair in cand_sources:
                if raw_cand_tbl.name.lower() != sql_tbl.name.lower():
                    continue
                view_tbl = _coerce_lkml_table(
                    raw_cand_tbl,
                    f"LookML view '{view_name}' table '{raw_cand_tbl.name}' cannot be qualified. "
                    f"Specify --lkml-schema and/or --lkml-db (or LKR_LKML_SCHEMA, LKR_LKML_DB) "
                    f"or ensure Looker {conn_info} metadata is accessible.",
                )
                if not _tables_match(sql_tbl, view_tbl):
                    continue
                matched_sources.append(
                    (sql_tbl, raw_table_str, view_name, view_obj, dt_col_pair)
                )
                tbl_schema_cols = (
                    lookml_schema.setdefault((sql_tbl.catalog or "").lower(), {})
                    .setdefault((sql_tbl.db or "").lower(), {})
                    .setdefault(sql_tbl.name.lower(), {})
                )
                if dt_col_pair is None:
                    db_cols = (
                        _fetch_table_columns_sandbox(
                            eff_conn, view_tbl.catalog, view_tbl.db, view_tbl.name
                        )
                        if eff_conn
                        else None
                    )
                    db_cols_by_view[view_name] = db_cols
                    tbl_schema_cols.update(
                        db_cols or view_cols_by_name.get(view_name, {})
                    )
                else:
                    tbl_schema_cols[dt_col_pair[1].lower()] = "UNKNOWN"

    eff_query_cols = _extract_query_columns(
        pq,
        dialect=dialect,
        schema=lookml_schema or None,
        default_db=sql_db,
        default_schema=sql_schema,
        split_count_cols=True,
    )
    non_join_col_set = {
        ((t or "").lower() or None, c.lower())
        for t, c in _extract_query_columns(
            pq,
            dialect=dialect,
            schema=lookml_schema or None,
            default_db=sql_db,
            default_schema=sql_schema,
            exclude_join_on=True,
            split_count_cols=True,
        )
    }
    non_join_units: set[tuple[str, str]] = set()

    for sql_tbl, raw_table_str, view_name, view_obj, dt_col_pair in matched_sources:
        self_names = self_names_by_view[view_name]
        pks = _view_pk_columns(view_obj)
        if dt_col_pair is None and view_name not in direct_views:
            direct_views[view_name] = raw_table_str
            view_order.append(view_name)
        for tbl_qual, col_name in eff_query_cols:
            is_non_join = (
                (tbl_qual or "").lower() or None,
                col_name.lower(),
            ) in non_join_col_set
            cnt_inner = (
                col_name[6:-1]
                if col_name.startswith("COUNT(")
                and col_name.endswith(")")
                and col_name != "COUNT(*)"
                else None
            )
            is_tbl_cnt = bool(cnt_inner and cnt_inner.endswith(".*"))
            if cnt_inner and not is_tbl_cnt:
                if dt_col_pair and cnt_inner.lower() != dt_col_pair[1]:
                    continue
                if (dt_col_pair[0] if dt_col_pair else cnt_inner).lower() in pks:
                    is_tbl_cnt = True
                else:
                    col_name = cnt_inner
            is_cnt = col_name == "COUNT(*)" or is_tbl_cnt
            if not is_cnt and dt_col_pair and col_name.lower() != dt_col_pair[1]:
                continue
            if tbl_qual and tbl_qual.lower() not in {
                sql_tbl.name.lower(),
                (sql_tbl.alias or "").lower(),
                view_name.lower(),
            }:
                continue
            if is_non_join:
                non_join_units.add(
                    ("*", "count(*)")
                    if col_name == "COUNT(*)"
                    else (raw_table_str.lower(), "count(*)" if is_cnt else col_name.lower())
                )
            target_col = dt_col_pair[0] if (dt_col_pair and not is_cnt) else col_name
            for ftype, fname, fobj in _iter_view_fields(view_obj):
                tfs = (
                    fobj.timeframes
                    if isinstance(fobj, LookmlDimensionGroup)
                    else None
                )
                props = _get_field_properties(ftype, fname, fobj)
                direct_hits: list[tuple[_FieldProperty | None, str, str, str | None]] = []
                if is_cnt:
                    if (
                        ftype == "measure"
                        and getattr(fobj, "type", None) == "count"
                        and not getattr(fobj, "filters", None)
                    ):
                        direct_hits.append((None, "measure.type", "type", "count"))
                else:
                    for p in props:
                        if p.sql_text and _field_matches_column(target_col, fname, p.sql_text, ftype, tfs):
                            direct_hits.append((p, p.prop_type, p.prop_key, p.expr))
                    if not direct_hits and _field_matches_column(target_col, fname, None, ftype, tfs):
                        direct_hits.append((None, f"{ftype}.sql", "sql", fobj.sql.strip() if getattr(fobj, "sql", None) else None))

                for fp_obj, m_prop, sub_key, expr_val in direct_hits:
                    fkey = (view_name, ftype, fname)
                    existing = matched_fields.get(fkey, [])
                    if any(x.sql_column == col_name and x.matched_property == m_prop for x in existing):
                        continue
                    if view_name not in direct_views:
                        direct_views[view_name] = raw_table_str
                        view_order.append(view_name)
                    refs = fp_obj.refs if fp_obj else []
                    ext_aliases = {
                        r.split(".", 1)[0].lower()
                        for r in refs
                        if "." in r
                        and r.split(".", 1)[0].lower() not in self_names
                    }
                    prop_path = f"view.{view_name}.{ftype}.{fname}.{sub_key}"
                    minfo = _FieldMatchInfo(
                        sql_table=raw_table_str,
                        sql_column=col_name,
                        via=[],
                        ext_aliases=ext_aliases,
                        matched_property=m_prop,
                        property_path=prop_path,
                        expression=expr_val,
                        sub_key=sub_key,
                    )
                    matched_fields.setdefault(fkey, []).append(minfo)
                    queue.append((view_name, ftype, fname, minfo))

    # Transitive forward ${...} and derived_table propagation
    while queue:
        src_view, src_ftype, src_fname, src_info = queue.popleft()
        src_tbl = src_info.sql_table
        src_col = src_info.sql_column
        src_via = src_info.via
        src_ext = src_info.ext_aliases
        src_fobj = _get_view_field(model_views[src_view], src_ftype, src_fname)
        src_cands = {src_fname.lower()}
        if isinstance(src_fobj, LookmlDimensionGroup) and src_fobj.timeframes:
            src_cands |= {f"{src_fname}_{tf}".lower() for tf in src_fobj.timeframes}
        src_aliases = aliases_for_view.get(src_view, {src_view.lower()})

        for cand_view, cand_obj in model_views.items():
            cand_self = self_names_by_view[cand_view]
            matched_ndt_cols = [
                ndt_col
                for ndt_col, pfx, fld in ndt_cols_by_view.get(cand_view, ())
                if (fld in src_cands or fld == src_col.lower()) and pfx in src_aliases
            ]
            for c_ftype, c_fname, c_fobj in _iter_view_fields(cand_obj):
                ckey = (cand_view, c_ftype, c_fname)
                existing = matched_fields.get(ckey, [])
                tfs = (
                    c_fobj.timeframes
                    if isinstance(c_fobj, LookmlDimensionGroup)
                    else None
                )
                hits_ndt = any(
                    _field_matches_column(ndt_col, c_fname, getattr(c_fobj, "sql", None), c_ftype, tfs)
                    for ndt_col in matched_ndt_cols
                )
                if hits_ndt:
                    m_prop = f"{c_ftype}.sql"
                    if not any(x.sql_column == src_col and x.matched_property == m_prop for x in existing):
                        own_ext = {
                            r.split(".", 1)[0].lower()
                            for r in _extract_lookml_refs(getattr(c_fobj, "sql", None))
                            if "." in r and r.split(".", 1)[0].lower() not in cand_self
                        }
                        minfo = _FieldMatchInfo(
                            sql_table=src_tbl,
                            sql_column=src_col,
                            via=[*src_via, f"{src_view}.{src_fname}"],
                            ext_aliases=own_ext,
                            matched_property=m_prop,
                            property_path=f"view.{cand_view}.{c_ftype}.{c_fname}.sql",
                            expression=c_fobj.sql.strip() if getattr(c_fobj, "sql", None) else None,
                            sub_key="sql",
                        )
                        matched_fields.setdefault(ckey, []).append(minfo)
                        queue.append((cand_view, c_ftype, c_fname, minfo))
                        if cand_view not in direct_views and cand_view not in view_order:
                            view_order.append(cand_view)

                for fp in _get_field_properties(c_ftype, c_fname, c_fobj):
                    hits_ref = (
                        not getattr(c_fobj, "_sql_defaulted", False)
                        and bool(fp.refs)
                        and any(
                            (cand_view == src_view and r.lower() in src_cands)
                            if "." not in r
                            else (
                                r.split(".", 1)[1].lower() in src_cands
                                and (
                                    r.split(".", 1)[0].lower() in src_aliases
                                    or (
                                        cand_view == src_view
                                        and r.split(".", 1)[0].lower() in cand_self
                                    )
                                )
                            )
                            for r in fp.refs
                        )
                    )
                    if hits_ref and not any(
                        x.sql_column == src_col and x.matched_property == fp.prop_type
                        for x in existing
                    ):
                            own_ext = {
                                r.split(".", 1)[0].lower()
                                for r in fp.refs
                                if "." in r and r.split(".", 1)[0].lower() not in cand_self
                            }
                            minfo = _FieldMatchInfo(
                                sql_table=src_tbl,
                                sql_column=src_col,
                                via=[*src_via, f"{src_view}.{src_fname}"],
                                ext_aliases=src_ext | own_ext,
                                matched_property=fp.prop_type,
                                property_path=f"view.{cand_view}.{c_ftype}.{c_fname}.{fp.sub_key}",
                                expression=fp.expr,
                                sub_key=fp.sub_key,
                            )
                            matched_fields.setdefault(ckey, []).append(minfo)
                            queue.append((cand_view, c_ftype, c_fname, minfo))
                            if cand_view not in direct_views and cand_view not in view_order:
                                view_order.append(cand_view)

    results: list[LookmlViewMatch] = []
    for view_name in view_order:
        assembled_view = model_views[view_name]
        chain = view_chains[view_name]
        view_file, view_pos = _chain_root_pos(chain, view_name)

        sql_tbl_loc: LookmlSourceLocation | None = None
        for fpath, _, p_dict in chain:
            st_pos = p_dict.get("sql_table_name", {})
            if isinstance(st_pos, dict) and "$p" in st_pos:
                sql_tbl_loc = _make_location(fpath, st_pos["$p"])

        v_fields: list[LookmlFieldMatch] = []
        v_sql_tbl = direct_views.get(view_name, "")
        for ftype, fname, fobj in _iter_view_fields(assembled_view):
            key = (view_name, ftype, fname)
            if key not in matched_fields:
                continue
            for minfo in matched_fields[key]:
                if not v_sql_tbl:
                    v_sql_tbl = minfo.sql_table

                f_loc: LookmlSourceLocation | None = None
                for fpath, _, p_dict in chain:
                    type_pos = p_dict.get(ftype, {})
                    if isinstance(type_pos, dict) and fname in type_pos:
                        f_pos_dict = type_pos[fname]
                        if isinstance(f_pos_dict, dict) and "$p" in f_pos_dict:
                            f_loc = _make_location(fpath, f_pos_dict["$p"])

                f_sql_loc = _find_field_prop_location(chain, ftype, fname, minfo.sub_key)
                loc = (
                    f_loc
                    or _make_location(view_file, view_pos)
                    or LookmlSourceLocation(
                        file=view_file, line=1, end_line=1, position=view_pos
                    )
                )
                tfs = (
                    fobj.timeframes if isinstance(fobj, LookmlDimensionGroup) else None
                )
                exp_matches = _find_explores_for_field(
                    model_name,
                    model_obj,
                    view_name,
                    fname,
                    ftype,
                    tfs,
                    minfo.ext_aliases,
                    exp_base_decls,
                    exp_ref_decls,
                )
                test_matches = _find_tests_for_field(
                    model_name=model_name,
                    view_name=view_name,
                    field_name=fname,
                    field_type=ftype,
                    timeframes=tfs,
                    explores=exp_matches,
                    test_infos=test_infos,
                )
                u_loc = f_sql_loc or loc
                usage_match = LookmlUsageMatch(
                    model_name=model_name,
                    view_name=view_name,
                    field_name=fname,
                    matched_property=minfo.matched_property,
                    property_path=minfo.property_path,
                    expression=minfo.expression,
                    sql_table=minfo.sql_table,
                    sql_column=minfo.sql_column,
                    file=u_loc.file,
                    line=u_loc.line,
                    end_line=u_loc.end_line,
                    position=u_loc.position,
                )
                v_fields.append(
                    LookmlFieldMatch(
                        sql_column=minfo.sql_column,
                        field_type=ftype,
                        field_name=fname,
                        sql=fobj.sql.strip() if getattr(fobj, "sql", None) else None,
                        matched_property=minfo.matched_property,
                        property_path=minfo.property_path,
                        expression=minfo.expression,
                        via=minfo.via,
                        file=loc.file,
                        line=loc.line,
                        end_line=loc.end_line,
                        position=loc.position,
                        sql_location=f_sql_loc,
                        explores=exp_matches,
                        tests=test_matches,
                        usages=[usage_match],
                    )
                )

        db_cols = db_cols_by_view.get(view_name) if view_name in direct_views else None
        v_cols = set(view_cols_by_name.get(view_name, {}))
        results.append(
            LookmlViewMatch(
                sql_table=v_sql_tbl,
                view_name=view_name,
                sql_table_name=(
                    assembled_view.sql_table_name.strip()
                    if assembled_view.sql_table_name
                    else None
                ),
                model_name=model_name,
                file=view_file,
                line=view_pos[0] + 1,
                end_line=view_pos[2] + 1,
                position=view_pos,
                sql_table_name_location=sql_tbl_loc,
                fields=v_fields,
                unmodeled_db_columns=sorted(set(db_cols) - v_cols) if db_cols else [],
                missing_db_columns=sorted(v_cols - set(db_cols)) if db_cols else [],
            )
        )

    def _dict_list(val: Any) -> list[dict[str, Any]]:
        return [d for d in (val if isinstance(val, list) else [val]) if isinstance(d, dict)]

    def _match_usages(
        usages: list[LookmlQueryFieldUsage],
        entries: list[
            tuple[
                LookmlViewMatch,
                LookmlFieldMatch,
                LookmlExploreFieldMatch,
                tuple[str, str],
                set[str],
            ]
        ],
    ) -> tuple[
        list[LookmlQueryFieldUsage],
        list[str],
        list[LookmlFieldMatch],
        set[tuple[str, str]],
    ]:
        m_usages: list[LookmlQueryFieldUsage] = []
        unmatched: list[str] = []
        m_fms: list[LookmlFieldMatch] = []
        cov: set[tuple[str, str]] = set()
        for u in usages:
            hits = [
                (fm, uk)
                for _, fm, _, uk, cands in entries
                if u.field.lower() in cands
            ]
            if hits:
                m_usages.append(u)
                for fm, uk in hits:
                    cov.add(uk)
                    if fm not in m_fms:
                        m_fms.append(fm)
            elif u.used_in != "increment_key" and u.field not in unmatched:
                unmatched.append(u.field)
        return m_usages, unmatched, m_fms, cov

    explore_usages: list[LookmlUsageMatch] = []
    matched_vms = {vm.view_name.lower(): vm for vm in results}
    matched_fields_by_view: dict[str, dict[str, LookmlFieldMatch]] = {
        vm.view_name.lower(): {fm.field_name.lower(): fm for fm in vm.fields}
        for vm in results
    }
    matched_cols_by_view: dict[str, dict[str, LookmlFieldMatch]] = {
        vm.view_name.lower(): {fm.sql_column.lower(): fm for fm in vm.fields}
        for vm in results
    }

    def _match_explore_expr(
        expr: str,
        views_by_alias: dict[str, str],
        default_alias: str,
        jv_name: str | None = None,
    ) -> tuple[bool, str | None, str | None, str | None, str | None]:
        for r in _extract_lookml_refs(expr):
            if "." in r:
                a, f = r.split(".", 1)
                v_name = views_by_alias.get(a.lower(), a.lower())
            else:
                v_name = views_by_alias.get(default_alias.lower(), default_alias.lower())
                f = r
            if v_name in matched_vms:
                vm = matched_vms[v_name]
                fm = matched_fields_by_view.get(v_name, {}).get(f.lower()) or matched_cols_by_view.get(v_name, {}).get(f.lower())
                if fm:
                    return True, vm.sql_table, fm.sql_column, v_name, fm.field_name
                elif vm.fields:
                    return True, vm.sql_table, vm.fields[0].sql_column, v_name, f
                else:
                    return True, vm.sql_table, None, v_name, f
        for m in _TABLE_COL_RE.finditer(expr):
            col = (m.group(1) or m.group(2)).lower()
            cand_views = [jv_name.lower()] if jv_name else [views_by_alias.get(default_alias.lower(), default_alias.lower())]
            for cv in cand_views:
                if cv in matched_vms:
                    vm = matched_vms[cv]
                    fm = matched_cols_by_view.get(cv, {}).get(col)
                    if fm:
                        return True, vm.sql_table, fm.sql_column, cv, fm.field_name
                    return True, vm.sql_table, col, cv, None
        for v_name, vm in matched_vms.items():
            tbl_clean = vm.sql_table.rsplit(".", 1)[-1].lower()
            if re.search(rf"\b{re.escape(tbl_clean)}\b", expr, re.IGNORECASE) or re.search(rf"\b{re.escape(v_name)}\b", expr, re.IGNORECASE):
                for col_name, fm in matched_cols_by_view.get(v_name, {}).items():
                    if re.search(rf"\b{re.escape(col_name)}\b", expr, re.IGNORECASE):
                        return True, vm.sql_table, fm.sql_column, v_name, fm.field_name
                if vm.fields:
                    return True, vm.sql_table, vm.fields[0].sql_column, v_name, None
                return True, vm.sql_table, None, v_name, None
        return False, None, None, None, None

    for exp_name, exp_val in (model_obj.explore or {}).items():
        for exp_obj in _as_list(exp_val):
            if not isinstance(exp_obj, LookmlExplore):
                continue
            exp_chain = _build_chain(exp_name, exp_base_decls, exp_ref_decls)
            base_view_name, base_alias, exp_file, exp_pos = _resolve_explore_base(
                exp_name, exp_obj, exp_chain, model_views
            )
            views_by_alias: dict[str, str] = {base_alias.lower(): base_view_name.lower()}
            for j_name, j_obj in (exp_obj.join or {}).items():
                jv_name = j_obj.from_ or j_obj.view_name or j_name
                views_by_alias[j_name.lower()] = jv_name.lower()

            if exp_obj.sql_always_where:
                raw_expr = str(exp_obj.sql_always_where).strip()
                hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias)
                if hit:
                    loc = _chain_prop_loc(exp_chain, ["sql_always_where"], exp_file, exp_pos)
                    explore_usages.append(
                        LookmlUsageMatch(
                            model_name=model_name,
                            explore_name=exp_name,
                            view_name=v_name,
                            field_name=f_name,
                            matched_property="explore.sql_always_where",
                            property_path=f"explore.{exp_name}.sql_always_where",
                            expression=raw_expr,
                            sql_table=tbl,
                            sql_column=col,
                            file=loc.file,
                            line=loc.line,
                            end_line=loc.end_line,
                            position=loc.position,
                        )
                    )

            if exp_obj.sql_always_having:
                raw_expr = str(exp_obj.sql_always_having).strip()
                hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias)
                if hit:
                    loc = _chain_prop_loc(exp_chain, ["sql_always_having"], exp_file, exp_pos)
                    explore_usages.append(
                        LookmlUsageMatch(
                            model_name=model_name,
                            explore_name=exp_name,
                            view_name=v_name,
                            field_name=f_name,
                            matched_property="explore.sql_always_having",
                            property_path=f"explore.{exp_name}.sql_always_having",
                            expression=raw_expr,
                            sql_table=tbl,
                            sql_column=col,
                            file=loc.file,
                            line=loc.line,
                            end_line=loc.end_line,
                            position=loc.position,
                        )
                    )

            for af in _as_list(exp_obj.access_filter):
                if isinstance(af, dict):
                    fld_val = af.get("field")
                    if fld_val:
                        fld_str = str(fld_val).strip()
                        if "." in fld_str:
                            a, f = fld_str.split(".", 1)
                            v_name = views_by_alias.get(a.lower(), a.lower())
                        else:
                            v_name = views_by_alias.get(base_alias.lower(), base_alias.lower())
                            f = fld_str
                        if v_name in matched_vms:
                            vm = matched_vms[v_name]
                            fm = matched_fields_by_view.get(v_name, {}).get(f.lower()) or matched_cols_by_view.get(v_name, {}).get(f.lower())
                            col = fm.sql_column if fm else f
                            loc = _chain_prop_loc(exp_chain, ["access_filter"], exp_file, exp_pos)
                            expr_str = f"field: {fld_str}, user_attribute: {af.get('user_attribute', '')}".strip()
                            explore_usages.append(
                                LookmlUsageMatch(
                                    model_name=model_name,
                                    explore_name=exp_name,
                                    view_name=v_name,
                                    field_name=f,
                                    matched_property="explore.access_filter",
                                    property_path=f"explore.{exp_name}.access_filter",
                                    expression=expr_str,
                                    sql_table=vm.sql_table,
                                    sql_column=col,
                                    file=loc.file,
                                    line=loc.line,
                                    end_line=loc.end_line,
                                    position=loc.position,
                                )
                            )

            for j_name, j_obj in (exp_obj.join or {}).items():
                jv_name = j_obj.from_ or j_obj.view_name or j_name
                if j_obj.sql_on:
                    raw_expr = str(j_obj.sql_on).strip()
                    hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias, jv_name=jv_name)
                    if hit:
                        loc = _chain_prop_loc(exp_chain, ["join", j_name, "sql_on"], exp_file, exp_pos)
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                explore_name=exp_name,
                                view_name=v_name or jv_name,
                                join_name=j_name,
                                field_name=f_name,
                                matched_property="join.sql_on",
                                property_path=f"explore.{exp_name}.join.{j_name}.sql_on",
                                expression=raw_expr,
                                sql_table=tbl,
                                sql_column=col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )

                if j_obj.sql_where:
                    raw_expr = str(j_obj.sql_where).strip()
                    hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias, jv_name=jv_name)
                    if hit:
                        loc = _chain_prop_loc(exp_chain, ["join", j_name, "sql_where"], exp_file, exp_pos)
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                explore_name=exp_name,
                                view_name=v_name or jv_name,
                                join_name=j_name,
                                field_name=f_name,
                                matched_property="join.sql_where",
                                property_path=f"explore.{exp_name}.join.{j_name}.sql_where",
                                expression=raw_expr,
                                sql_table=tbl,
                                sql_column=col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )

                if j_obj.sql:
                    raw_expr = str(j_obj.sql).strip()
                    hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias, jv_name=jv_name)
                    if hit:
                        loc = _chain_prop_loc(exp_chain, ["join", j_name, "sql"], exp_file, exp_pos)
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                explore_name=exp_name,
                                view_name=v_name or jv_name,
                                join_name=j_name,
                                field_name=f_name,
                                matched_property="join.sql",
                                property_path=f"explore.{exp_name}.join.{j_name}.sql",
                                expression=raw_expr,
                                sql_table=tbl,
                                sql_column=col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )

                sql_fk = getattr(j_obj, "sql_foreign_key", None) or (j_obj.model_extra or {}).get("sql_foreign_key")
                if sql_fk:
                    raw_expr = str(sql_fk).strip()
                    hit, tbl, col, v_name, f_name = _match_explore_expr(raw_expr, views_by_alias, base_alias, jv_name=jv_name)
                    if hit:
                        loc = _chain_prop_loc(exp_chain, ["join", j_name, "sql_foreign_key"], exp_file, exp_pos)
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                explore_name=exp_name,
                                view_name=v_name or jv_name,
                                join_name=j_name,
                                field_name=f_name,
                                matched_property="join.sql_foreign_key",
                                property_path=f"explore.{exp_name}.join.{j_name}.sql_foreign_key",
                                expression=raw_expr,
                                sql_table=tbl,
                                sql_column=col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )

                if j_obj.foreign_key:
                    raw_fk = str(j_obj.foreign_key).strip()
                    hit, tbl, col, v_name, f_name = False, None, None, None, None
                    base_v = base_view_name.lower()
                    if base_v in matched_vms:
                        vm = matched_vms[base_v]
                        fm = matched_fields_by_view.get(base_v, {}).get(raw_fk.lower()) or matched_cols_by_view.get(base_v, {}).get(raw_fk.lower())
                        if fm:
                            hit, tbl, col, v_name, f_name = True, vm.sql_table, fm.sql_column, base_view_name, fm.field_name
                        else:
                            hit, tbl, col, v_name, f_name = True, vm.sql_table, raw_fk, base_view_name, raw_fk
                    elif jv_name.lower() in matched_vms:
                        vm = matched_vms[jv_name.lower()]
                        hit, tbl, col, v_name, f_name = True, vm.sql_table, raw_fk, jv_name, raw_fk
                    if hit:
                        loc = _chain_prop_loc(exp_chain, ["join", j_name, "foreign_key"], exp_file, exp_pos)
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                explore_name=exp_name,
                                view_name=v_name or jv_name,
                                join_name=j_name,
                                field_name=f_name,
                                matched_property="join.foreign_key",
                                property_path=f"explore.{exp_name}.join.{j_name}.foreign_key",
                                expression=raw_fk,
                                sql_table=tbl,
                                sql_column=col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )

            if not exp_obj.aggregate_table and not exp_obj.query:
                continue
            exp_entries: list[
                tuple[
                    LookmlViewMatch,
                    LookmlFieldMatch,
                    LookmlExploreFieldMatch,
                    tuple[str, str],
                    set[str],
                ]
            ] = []
            canon_by_unit: dict[tuple[str, str], str] = {}
            for vm in results:
                for fm in vm.fields:
                    f_sql_tbl = vm.sql_table
                    col_name = fm.sql_column
                    uk = (
                        ("*", "count(*)")
                        if col_name == "COUNT(*)"
                        else (f_sql_tbl.lower(), "count(*)")
                        if col_name.startswith("COUNT(")
                        else (f_sql_tbl.lower(), col_name.lower())
                    )
                    fobj = getattr(model_views[vm.view_name], fm.field_type)[
                        fm.field_name
                    ]
                    tfs = (
                        fobj.timeframes
                        if isinstance(fobj, LookmlDimensionGroup)
                        else None
                    )
                    for em in fm.explores:
                        if em.explore_name != exp_name:
                            continue
                        aliases = {em.view_alias.lower(), vm.view_name.lower()}
                        fn_low = fm.field_name.lower()
                        cands = {f"{a}.{fn_low}" for a in aliases}
                        if fm.field_type == "dimension_group":
                            cands |= {
                                f"{a}.{fn_low}_{tf.lower()}"
                                for a in aliases
                                for tf in (tfs or ())
                            }
                        exp_entries.append((vm, fm, em, uk, cands))
                        if (
                            fm.field_type == "measure"
                            and getattr(fobj, "type", None) == "count"
                            and uk != ("*", "count(*)")
                            and ("*", "count(*)") in non_join_units
                        ):
                            exp_entries.append((vm, fm, em, ("*", "count(*)"), cands))
                        if (not non_join_units or uk in non_join_units) and (
                            not fm.via or uk not in canon_by_unit
                        ):
                            canon_by_unit[uk] = em.field

            if not exp_entries:
                continue

            for agg_name, agg_val in (exp_obj.aggregate_table or {}).items():
                for agg_obj in _as_list(agg_val):
                    q_dicts = _dict_list(agg_obj.query)
                    usages = [
                        u
                        for qd in q_dicts
                        for u in _collect_query_block_fields(qd, base_alias)
                    ]
                    tf_gran = next(
                        (
                            str(qd["timeframe_granularity"])
                            for qd in q_dicts
                            if qd.get("timeframe_granularity")
                        ),
                        None,
                    )
                    mat = (_dict_list(agg_obj.materialization) or [{}])[0]
                    inc_key = mat.get("increment_key")
                    sql_trig = (
                        str(mat["sql_trigger_value"]).strip()
                        if mat.get("sql_trigger_value")
                        else None
                    )
                    if inc_key:
                        usages.append(
                            LookmlQueryFieldUsage(
                                field=_qualify_field_ref(str(inc_key), base_alias),
                                used_in="increment_key",
                            )
                        )
                    matched_usages, _, matched_fms, covered_units = _match_usages(
                        usages, exp_entries
                    )
                    if sql_trig:
                        try:
                            trig_res = parse_sql(sql=sql_trig, dialect=dialect)
                            trig_cols = {
                                ((t or "").lower() or None, c.lower())
                                for q in trig_res.queries
                                for t, c in _extract_query_columns(q, dialect=dialect)
                            }
                            tbl_to_aliases: dict[str, set[str | None]] = {}
                            for q in trig_res.queries:
                                for t in q.tables:
                                    if t.name:
                                        tbl_to_aliases.setdefault(
                                            t.name.lower(), {t.name.lower(), None}
                                        ).add((t.alias or t.name).lower())
                            for vm, fm, em, uk, _ in exp_entries:
                                v_tbl = vm.sql_table.rsplit(".", 1)[-1].lower()
                                c_low = fm.sql_column.lower()
                                t_aliases = tbl_to_aliases.get(v_tbl)
                                if (
                                    not fm.via
                                    and t_aliases
                                    and any((a, c_low) in trig_cols for a in t_aliases)
                                ):
                                    u_trig = LookmlQueryFieldUsage(
                                        field=em.field, used_in="sql_trigger_value"
                                    )
                                    if u_trig not in matched_usages:
                                        matched_usages.append(u_trig)
                                    covered_units.add(uk)
                                    if fm not in matched_fms:
                                        matched_fms.append(fm)
                        except Exception:  # noqa: BLE001, S110
                            pass

                    if matched_usages:
                        loc = _chain_sub_loc(
                            exp_chain, "aggregate_table", agg_name, exp_file, exp_pos
                        )
                        missing = [
                            f for u, f in canon_by_unit.items() if u not in covered_units
                        ]
                        agg_match = LookmlAggregateTableMatch(
                            model_name=model_name,
                            explore_name=exp_name,
                            aggregate_table_name=agg_name,
                            coverage="hit_candidate"
                            if not missing
                            else "partial_overlap",
                            matched_fields=matched_usages,
                            missing_query_fields=missing,
                            timeframe_granularity=tf_gran,
                            datagroup_trigger=mat.get("datagroup_trigger"),
                            sql_trigger_value=sql_trig,
                            increment_key=inc_key,
                            **loc.model_dump(),
                        )
                        for fm in matched_fms:
                            fm.aggregate_tables.append(agg_match)

            for q_name, q_val in (exp_obj.query or {}).items():
                for q_dict in _dict_list(q_val):
                    matched_usages, unmatched_refs, matched_fms, covered_units = (
                        _match_usages(
                            _collect_query_block_fields(q_dict, base_alias), exp_entries
                        )
                    )
                    if matched_usages:
                        loc = _chain_sub_loc(
                            exp_chain, "query", q_name, exp_file, exp_pos
                        )
                        missing = [
                            f for u, f in canon_by_unit.items() if u not in covered_units
                        ]
                        q_match = LookmlExploreQueryMatch(
                            model_name=model_name,
                            explore_name=exp_name,
                            query_name=q_name,
                            coverage="exact"
                            if not missing and not unmatched_refs
                            else "partial_overlap",
                            matched_fields=matched_usages,
                            unmatched_explore_query_fields=unmatched_refs,
                            missing_query_fields=missing,
                            **loc.model_dump(),
                        )
                        for fm in matched_fms:
                            fm.explore_queries.append(q_match)

    for v_name, v_obj in model_views.items():
        if not isinstance(v_obj, LookmlView):
            continue
        dt = getattr(v_obj, "derived_table", None)
        if not dt:
            continue
        sql_trig = getattr(dt, "sql_trigger_value", None)
        if not sql_trig:
            continue
        sql_trig_str = str(sql_trig).strip()
        try:
            trig_res = parse_sql(sql=sql_trig_str, dialect=dialect)
            trig_tables = {
                (t.name or "").lower()
                for q in trig_res.queries
                for t in q.tables
                if t.name
            }
            trig_cols = {
                c.lower()
                for q in trig_res.queries
                for _, c in _extract_query_columns(q, dialect=dialect)
            }
            matched_vm = None
            matched_col = None
            for vm in results:
                v_tbl = vm.sql_table.rsplit(".", 1)[-1].lower()
                if v_tbl in trig_tables or vm.view_name.lower() in trig_tables:
                    matched_vm = vm
                    for fm in vm.fields:
                        if fm.sql_column.lower() in trig_cols:
                            matched_col = fm.sql_column
                            break
                    if not matched_col and vm.fields:
                        matched_col = vm.fields[0].sql_column
                    break
            if matched_vm or (v_name.lower() in matched_vms):
                m_vm = matched_vm or matched_vms[v_name.lower()]
                v_chain = view_chains.get(v_name, [])
                v_file, v_pos = _chain_root_pos(v_chain, v_name)
                loc = _chain_prop_loc(v_chain, ["derived_table", "sql_trigger_value"], v_file, v_pos)
                explore_usages.append(
                    LookmlUsageMatch(
                        model_name=model_name,
                        view_name=v_name,
                        matched_property="derived_table.sql_trigger_value",
                        property_path=f"view.{v_name}.derived_table.sql_trigger_value",
                        expression=sql_trig_str,
                        sql_table=m_vm.sql_table,
                        sql_column=matched_col or (m_vm.fields[0].sql_column if m_vm.fields else None),
                        file=loc.file,
                        line=loc.line,
                        end_line=loc.end_line,
                        position=loc.position,
                    )
                )
        except Exception:  # noqa: BLE001, S110
            pass

    for dg_name, dg_val in (getattr(model_obj, "datagroup", None) or {}).items():
        for dg_obj in _as_list(dg_val):
            if not isinstance(dg_obj, LookmlDatagroup):
                continue
            if dg_obj.sql_trigger:
                sql_trig = str(dg_obj.sql_trigger).strip()
                try:
                    trig_res = parse_sql(sql=sql_trig, dialect=dialect)
                    trig_tables = {
                        (t.name or "").lower()
                        for q in trig_res.queries
                        for t in q.tables
                        if t.name
                    }
                    trig_cols = {
                        c.lower()
                        for q in trig_res.queries
                        for _, c in _extract_query_columns(q, dialect=dialect)
                    }
                    matched_vm = None
                    matched_col = None
                    for vm in results:
                        v_tbl = vm.sql_table.rsplit(".", 1)[-1].lower()
                        if v_tbl in trig_tables or vm.view_name.lower() in trig_tables:
                            matched_vm = vm
                            for fm in vm.fields:
                                if fm.sql_column.lower() in trig_cols:
                                    matched_col = fm.sql_column
                                    break
                            if not matched_col and vm.fields:
                                matched_col = vm.fields[0].sql_column
                            break
                    if matched_vm:
                        loc = _find_datagroup_location(positions, model_name, dg_name, "sql_trigger")
                        explore_usages.append(
                            LookmlUsageMatch(
                                model_name=model_name,
                                datagroup_name=dg_name,
                                matched_property="datagroup.sql_trigger",
                                property_path=f"datagroup.{dg_name}.sql_trigger",
                                expression=sql_trig,
                                sql_table=matched_vm.sql_table,
                                sql_column=matched_col,
                                file=loc.file,
                                line=loc.line,
                                end_line=loc.end_line,
                                position=loc.position,
                            )
                        )
                except Exception:  # noqa: BLE001, S110
                    pass

            if dg_obj.interval_trigger:
                interval_trig = str(dg_obj.interval_trigger).strip()
                dg_used_by = False
                matched_vm = None
                for vm in results:
                    v_obj = model_views.get(vm.view_name)
                    if v_obj and getattr(v_obj, "persist_with", None) == dg_name:
                        dg_used_by = True
                        matched_vm = vm
                        break
                    dt = getattr(v_obj, "derived_table", None)
                    if dt and (getattr(dt, "datagroup_trigger", None) == dg_name or getattr(dt, "persist_with", None) == dg_name):
                        dg_used_by = True
                        matched_vm = vm
                        break
                if not dg_used_by:
                    for exp_name, exp_val in (model_obj.explore or {}).items():
                        for exp_obj in _as_list(exp_val):
                            if (
                                isinstance(exp_obj, LookmlExplore)
                                and getattr(exp_obj, "persist_with", None) == dg_name
                                and any(
                                    vm.view_name.lower() in (exp_obj.from_ or exp_name).lower()
                                    for vm in results
                                )
                            ):
                                dg_used_by = True
                                matched_vm = results[0] if results else None
                                break
                if dg_used_by and matched_vm:
                    loc = _find_datagroup_location(positions, model_name, dg_name, "interval_trigger")
                    explore_usages.append(
                        LookmlUsageMatch(
                            model_name=model_name,
                            datagroup_name=dg_name,
                            matched_property="datagroup.interval_trigger",
                            property_path=f"datagroup.{dg_name}.interval_trigger",
                            expression=interval_trig,
                            sql_table=matched_vm.sql_table,
                            sql_column=matched_vm.fields[0].sql_column if matched_vm.fields else None,
                            file=loc.file,
                            line=loc.line,
                            end_line=loc.end_line,
                            position=loc.position,
                        )
                    )

    return results, explore_usages


def _normalize_lookml_join_type(jtype: str | None) -> str:
    t = (jtype or "left_outer").lower()
    if t in ("left_outer", "left"):
        return "LEFT"
    if t == "inner":
        return "INNER"
    if t in ("full_outer", "full"):
        return "FULL"
    if t == "cross":
        return "CROSS"
    return "LEFT"


_FLIP_REL: dict[str, str] = {
    "many_to_one": "one_to_many",
    "one_to_many": "many_to_one",
}


def _view_table_tail(v: LookmlView | None) -> str:
    return (
        re.sub(r"[\${}\s;`\"'\[\]]", "", v.sql_table_name).split(".")[-1].lower()
        if v and v.sql_table_name
        else ""
    )


def _view_pk_columns(v: LookmlView | None) -> set[str]:
    if not v or not v.dimension:
        return set()
    pks: set[str] = set()
    for d_name, d_obj in v.dimension.items():
        if getattr(d_obj, "primary_key", False):
            pks.add(d_name.lower())
            if d_obj.sql:
                for m in _TABLE_COL_RE.finditer(d_obj.sql):
                    pks.add((m.group(1) or m.group(2)).lower())
    return pks


def _resolve_table_view(
    tbl_name: str,
    tbl_alias: str,
    target_graph: LookmlExploreJoinGraph,
    m_views: dict[str, LookmlView],
) -> LookmlView | None:
    keys = {tbl_name, tbl_alias} - {""}
    if not keys:
        return None
    if keys & {target_graph.base_view.lower(), target_graph.base_alias.lower()}:
        return m_views.get(target_graph.base_view)
    for j_name, j_node in target_graph.joins.items():
        if keys & {j_name.lower(), j_node.target_view.lower(), j_node.view_alias.lower()}:
            return m_views.get(j_node.target_view)
    for v_name, v_obj in m_views.items():
        v_tbl = _view_table_tail(v_obj)
        if keys & ({v_name.lower()} | ({v_tbl} if v_tbl else set())):
            return v_obj
    return None


def _build_views_by_model(
    models: dict[str, LookmlModel],
) -> dict[str, dict[str, LookmlView]]:
    return {
        m_name: {
            v_k: items[-1]
            for v_k, v_v in (m_obj.view or {}).items()
            if (items := [x for x in _as_list(v_v) if isinstance(x, LookmlView)])
        }
        for m_name, m_obj in models.items()
    }


def _analyze_query_joins(
    pq: ParsedQuery,
    all_explore_graphs: list[LookmlExploreJoinGraph],
    models: dict[str, LookmlModel],
    query_explores: list[LookmlExploreFieldMatch],
    views_by_model: dict[str, dict[str, LookmlView]] | None = None,
) -> list[ExploreJoinComparison]:
    if not pq.joins:
        return []

    candidate_explore_keys = {
        (em.model_name, em.explore_name) for em in query_explores
    }
    queried_table_names = {t.name.lower() for t in pq.tables if t.name}

    candidate_graphs: list[LookmlExploreJoinGraph] = []
    if candidate_explore_keys:
        candidate_graphs = [
            g
            for g in all_explore_graphs
            if (g.model_name, g.explore_name) in candidate_explore_keys
        ]

    if not candidate_graphs and queried_table_names:
        candidate_graphs = [
            g
            for g in all_explore_graphs
            if g.base_view.lower() in queried_table_names
            or g.base_alias.lower() in queried_table_names
            or any(
                j.name.lower() in queried_table_names
                or j.target_view.lower() in queried_table_names
                for j in g.joins.values()
            )
        ]

    if not candidate_graphs:
        candidate_graphs = all_explore_graphs

    if views_by_model is None:
        views_by_model = _build_views_by_model(models)

    results: list[ExploreJoinComparison] = []

    for target_graph in candidate_graphs:
        m_views = views_by_model.get(target_graph.model_name or "", {})
        bv_tail = _view_table_tail(m_views.get(target_graph.base_view))
        base_names = {target_graph.base_view.lower(), target_graph.base_alias.lower()} | (
            {bv_tail} if bv_tail else set()
        )

        # Precompute explore-level safety warnings (fan trap detection)
        o2m_joins = [
            j
            for j in target_graph.joins.values()
            if (j.relationship or "").lower() in ("one_to_many", "many_to_many")
        ]
        explore_safety_warnings = [
            JoinSafetyWarning(
                rule="fan_trap",
                severity="warning",
                message=(
                    f"Potential fan trap detected: join '{j1.name}' ({j1.relationship}) "
                    f"and join '{j2.name}' ({j2.relationship}) create a multi-fanout path "
                    "which can multiply aggregate calculations"
                ),
                joins=[j1.name, j2.name],
            )
            for j1, j2 in itertools.combinations(o2m_joins, 2)
        ]

        for sql_join in pq.joins:
            left_t = sql_join.left_table
            right_t = sql_join.right_table
            left_name = (left_t.name if left_t else "").lower()
            left_alias = (left_t.alias if left_t and left_t.alias else left_name).lower()
            right_name = (right_t.name if right_t else "").lower()
            right_alias = (right_t.alias if right_t and right_t.alias else right_name).lower()

            left_view = _resolve_table_view(left_name, left_alias, target_graph, m_views)
            right_view = _resolve_table_view(right_name, right_alias, target_graph, m_views)
            left_pks = _view_pk_columns(left_view)
            right_pks = _view_pk_columns(right_view)
            inferred_rel: str | None = None
            if sql_join.equi_joins and (left_pks or right_pks):
                l_is_pk = bool(left_pks) and all(
                    l_col.lower() in left_pks for (_, l_col), _ in sql_join.equi_joins
                )
                r_is_pk = bool(right_pks) and all(
                    r_col.lower() in right_pks for _, (_, r_col) in sql_join.equi_joins
                )
                if l_is_pk and r_is_pk:
                    inferred_rel = "one_to_one"
                elif r_is_pk:
                    inferred_rel = "many_to_one"
                elif l_is_pk:
                    inferred_rel = "one_to_many"
                elif left_view is not None and right_view is not None:
                    inferred_rel = "many_to_many"

            matched_j: LookmlExploreJoinNode | None = None
            matched_inverted = False

            for j_name, j_node in target_graph.joins.items():
                jv_tail = _view_table_tail(m_views.get(j_node.target_view))
                j_names = {
                    j_name.lower(),
                    j_node.target_view.lower(),
                    j_node.view_alias.lower(),
                } | ({jv_tail} if jv_tail else set())

                from_v = (j_node.from_view or target_graph.base_alias).lower()
                from_tail = _view_table_tail(m_views.get(j_node.from_view or ""))
                from_names = {from_v} | ({from_tail} if from_tail else set())

                fwd_match = (right_name in j_names or right_alias in j_names) and (
                    left_name in base_names
                    or left_alias in base_names
                    or left_name in from_names
                    or left_alias in from_names
                )
                rev_match = (left_name in j_names or left_alias in j_names) and (
                    right_name in base_names
                    or right_alias in base_names
                    or right_name in from_names
                    or right_alias in from_names
                )
                if fwd_match or rev_match:
                    matched_j = j_node
                    matched_inverted = rev_match and not fwd_match
                    break

            safety_warnings = list(explore_safety_warnings)
            precedents: list[JoinPrecedent] = []

            # Missing required joins
            if matched_j and matched_j.required_joins:
                query_tables = {
                    t.lower()
                    for j in pq.joins
                    for tbl in [j.left_table, j.right_table]
                    if tbl
                    for t in [tbl.name, tbl.alias]
                    if t
                }
                for req in matched_j.required_joins:
                    req_node = target_graph.joins.get(req)
                    if not req_node:
                        safety_warnings.append(
                            JoinSafetyWarning(
                                rule="missing_required_join",
                                severity="warning",
                                message=(
                                    f"Join '{matched_j.name}' specifies required_joins '{req}', "
                                    f"which is not defined in explore '{target_graph.explore_name}'"
                                ),
                                joins=[matched_j.name, req],
                            )
                        )
                    else:
                        req_aliases = {
                            req.lower(),
                            req_node.target_view.lower(),
                            req_node.view_alias.lower(),
                        }
                        if not (req_aliases & query_tables):
                            safety_warnings.append(
                                JoinSafetyWarning(
                                    rule="missing_required_join",
                                    severity="warning",
                                    message=(
                                        f"Join '{matched_j.name}' specifies required_joins '{req}', "
                                        "but it is not joined in the query"
                                    ),
                                    joins=[matched_j.name, req],
                                )
                            )

            if matched_j is not None:
                sql_type = _normalize_sql_join_type(sql_join.side, sql_join.kind)
                lkml_type = _normalize_lookml_join_type(matched_j.type)
                type_match = (sql_type == lkml_type)

                equi_match = True
                if sql_join.equi_joins and matched_j.equi_joins:
                    sql_cols = {
                        (l_col.lower(), r_col.lower())
                        for (_, l_col), (_, r_col) in sql_join.equi_joins
                    }
                    sql_cols_rev = {
                        (r_col.lower(), l_col.lower())
                        for (_, l_col), (_, r_col) in sql_join.equi_joins
                    }
                    lkml_cols = {
                        (f_col.lower(), j_col.lower())
                        for (_, f_col), (_, j_col) in matched_j.equi_joins
                    }
                    equi_match = bool(sql_cols & lkml_cols or sql_cols_rev & lkml_cols)

                status = (
                    "exact_match"
                    if (type_match and equi_match)
                    else "type_mismatch"
                )
                if inferred_rel is None:
                    inferred_rel = (
                        _FLIP_REL.get(matched_j.relationship, matched_j.relationship)
                        if matched_inverted
                        else matched_j.relationship
                    )
                else:
                    expected_explore_rel = (
                        _FLIP_REL.get(inferred_rel, inferred_rel)
                        if matched_inverted
                        else inferred_rel
                    )
                    if expected_explore_rel != matched_j.relationship:
                        safety_warnings.append(
                            JoinSafetyWarning(
                                rule="relationship_mismatch",
                                severity="warning",
                                message=(
                                    f"Join '{matched_j.name}' declares relationship '{matched_j.relationship}', "
                                    f"but primary keys infer '{expected_explore_rel}'"
                                ),
                                joins=[matched_j.name],
                            )
                        )

                results.append(
                    ExploreJoinComparison(
                        explore_name=target_graph.explore_name,
                        model_name=target_graph.model_name,
                        sql_join=sql_join,
                        status=status,
                        matched_explore_join=matched_j.name,
                        explore_join_type=matched_j.type,
                        sql_join_type=sql_type,
                        relationship=matched_j.relationship,
                        inferred_relationship=inferred_rel,
                        safety_warnings=safety_warnings,
                        precedents=[],
                    )
                )
            else:
                both_precedents: list[JoinPrecedent] = []
                target_precedents: list[JoinPrecedent] = []
                seen_both: set[tuple[str, str, str]] = set()
                seen_target: set[tuple[str, str, str]] = set()

                for other_g in all_explore_graphs:
                    if (other_g.model_name, other_g.explore_name) == (
                        target_graph.model_name,
                        target_graph.explore_name,
                    ):
                        continue
                    o_views = views_by_model.get(other_g.model_name or "", {})
                    obv_tail = _view_table_tail(o_views.get(other_g.base_view))
                    o_base_names = {
                        other_g.base_view.lower(),
                        other_g.base_alias.lower(),
                    } | ({obv_tail} if obv_tail else set())

                    for oj_name, oj_node in other_g.joins.items():
                        ojv_tail = _view_table_tail(o_views.get(oj_node.target_view))
                        oj_names = {
                            oj_name.lower(),
                            oj_node.target_view.lower(),
                            oj_node.view_alias.lower(),
                        } | ({ojv_tail} if ojv_tail else set())

                        from_v = (oj_node.from_view or other_g.base_alias).lower()
                        from_tail = _view_table_tail(o_views.get(oj_node.from_view or ""))
                        from_names = {from_v} | ({from_tail} if from_tail else set())

                        right_matches = bool(oj_names & {right_name, right_alias})
                        left_matches = bool(
                            (o_base_names | from_names) & {left_name, left_alias}
                        )
                        rev_right_matches = bool(oj_names & {left_name, left_alias})
                        rev_left_matches = bool(
                            (o_base_names | from_names) & {right_name, right_alias}
                        )

                        is_both = (right_matches and left_matches) or (
                            rev_right_matches and rev_left_matches
                        )
                        is_target = right_matches or rev_right_matches

                        prec_key = (
                            other_g.model_name or "",
                            other_g.explore_name,
                            oj_node.name,
                        )
                        prec_item = JoinPrecedent(
                            model_name=other_g.model_name or "",
                            explore_name=other_g.explore_name,
                            join_name=oj_node.name,
                            target_view=oj_node.target_view,
                            type=oj_node.type,
                            relationship=oj_node.relationship,
                            sql_on=oj_node.sql_on,
                            file=oj_node.file,
                            line=oj_node.line,
                        )
                        if is_both and prec_key not in seen_both:
                            seen_both.add(prec_key)
                            both_precedents.append(prec_item)
                        elif is_target and prec_key not in seen_target:
                            seen_target.add(prec_key)
                            target_precedents.append(prec_item)

                precedents = both_precedents if both_precedents else target_precedents
                if inferred_rel is None and both_precedents:
                    inferred_rel = both_precedents[0].relationship

                results.append(
                    ExploreJoinComparison(
                        explore_name=target_graph.explore_name,
                        model_name=target_graph.model_name,
                        sql_join=sql_join,
                        status="missing_join",
                        matched_explore_join=None,
                        explore_join_type=None,
                        sql_join_type=_normalize_sql_join_type(sql_join.side, sql_join.kind),
                        relationship=None,
                        inferred_relationship=inferred_rel,
                        safety_warnings=safety_warnings,
                        precedents=precedents,
                    )
                )

    return results


def parse_sql_to_lookml(
    sql: str | None = None,
    sql_file: Path | str | None = None,
    path: Path | str | None = None,
    lookml_file: Path | str | None = None,
    lookml: str | None = None,
    dialect: str | None = None,
    describe: bool = False,
    sql_db: str | None = None,
    sql_schema: str | None = None,
    lkml_conn: str | None = None,
    lkml_db: str | None = None,
    lkml_schema: str | None = None,
    *,
    manifest: Path | str | None = None,
    constants: dict[str, str] | None = None,
) -> SqlToLookmlResult:
    """Parse SQL queries and map referenced tables and columns to LookML views/fields with file and line locations."""
    sql_db = sql_db or os.getenv("LKR_SQL_DB")
    sql_schema = sql_schema or os.getenv("LKR_SQL_SCHEMA")
    lkml_conn = lkml_conn or os.getenv("LKR_LKML_CONN")
    lkml_db = lkml_db or os.getenv("LKR_LKML_DB")
    lkml_schema = lkml_schema or os.getenv("LKR_LKML_SCHEMA")

    sql_res = parse_sql(sql=sql, file=sql_file, dialect=dialect)
    project = parse_lookml(
        path=path,
        file=lookml_file,
        lookml=lookml,
        manifest=manifest,
        constants=constants,
    ).apply_defaults()

    view_base_decls, view_ref_decls = _collect_declarations(project, "view", LookmlView)
    exp_base_decls, exp_ref_decls = _collect_declarations(
        project, "explore", LookmlExplore
    )
    test_base_decls, test_ref_decls = _collect_declarations(
        project, "test", LookmlTest
    )
    models: dict[str, LookmlModel] = project.model or {}

    all_explore_graphs: list[LookmlExploreJoinGraph] = []
    for m_name, m_obj in models.items():
        m_views = m_obj.view or {}
        for e_name, e_val in (m_obj.explore or {}).items():
            for e_obj in _as_list(e_val):
                if isinstance(e_obj, LookmlExplore):
                    e_chain = _build_chain(e_name, exp_base_decls, exp_ref_decls)
                    all_explore_graphs.append(
                        build_explore_join_graph(
                            explore_name=e_name,
                            explore_obj=e_obj,
                            explore_chain=e_chain,
                            model_views=m_views,
                            model_name=m_name,
                        )
                    )

    views_by_model = _build_views_by_model(models)

    mappings: list[QueryLookmlMapping] = []
    for raw_pq in sql_res.queries:
        coerced_tables = [
            _coerce_table(
                tbl,
                sql_db,
                sql_schema,
                f"SQL table '{tbl.name}' is unqualified. Specify --sql-schema and/or --sql-db "
                "(or LKR_SQL_SCHEMA, LKR_SQL_DB) to qualify SQL tables.",
            )
            for tbl in raw_pq.tables
        ]
        pq = raw_pq.model_copy(update={"tables": coerced_tables})
        view_matches: list[LookmlViewMatch] = []
        extra_usages: list[LookmlUsageMatch] = []
        for model_name, model_obj in models.items():
            vm_list, exp_u_list = _match_model_views(
                pq,
                model_name,
                model_obj,
                view_base_decls,
                view_ref_decls,
                exp_base_decls,
                exp_ref_decls,
                test_base_decls,
                test_ref_decls,
                project.positions,
                lkml_conn=lkml_conn,
                lkml_db=lkml_db,
                lkml_schema=lkml_schema,
                dialect=dialect,
                sql_db=sql_db,
                sql_schema=sql_schema,
            )
            view_matches.extend(vm_list)
            extra_usages.extend(exp_u_list)
        query_explores = list(
            {
                (em.model_name, em.explore_name, em.field, em.join_name): em
                for vm in view_matches
                for fm in vm.fields
                for em in fm.explores
            }.values()
        )
        tests_by_key: dict[tuple[str, str], LookmlTestMatch] = {}
        for tm in (t for vm in view_matches for fm in vm.fields for t in fm.tests):
            key = (tm.model_name, tm.test_name)
            if key not in tests_by_key:
                tests_by_key[key] = tm.model_copy(update={"fields": list(tm.fields)})
            else:
                existing = tests_by_key[key]
                existing.fields.extend(f for f in tm.fields if f not in existing.fields)
        query_tests = list(tests_by_key.values())
        query_agg_tables = list(
            {
                (am.model_name, am.explore_name, am.aggregate_table_name): am
                for vm in view_matches
                for fm in vm.fields
                for am in fm.aggregate_tables
            }.values()
        )
        query_explore_queries = list(
            {
                (qm.model_name, qm.explore_name, qm.query_name): qm
                for vm in view_matches
                for fm in vm.fields
                for qm in fm.explore_queries
            }.values()
        )
        query_join_analysis = _analyze_query_joins(
            pq,
            all_explore_graphs,
            models,
            query_explores,
            views_by_model=views_by_model,
        )
        all_raw_usages = [
            u for vm in view_matches for fm in vm.fields for u in fm.usages
        ] + extra_usages
        seen_keys: set[Any] = set()
        query_usages: list[LookmlUsageMatch] = []
        for u in all_raw_usages:
            key = (
                u.model_name,
                u.explore_name,
                u.view_name,
                u.join_name,
                u.field_name,
                u.datagroup_name,
                u.matched_property,
                u.property_path,
                u.file,
                u.line,
            )
            if key not in seen_keys:
                seen_keys.add(key)
                query_usages.append(u)

        mappings.append(
            QueryLookmlMapping(
                raw_sql=pq.raw_sql,
                parsed_query=pq,
                views=view_matches,
                explores=query_explores,
                tests=query_tests,
                aggregate_tables=query_agg_tables,
                explore_queries=query_explore_queries,
                join_analysis=query_join_analysis,
                usages=query_usages,
            )
        )

    return SqlToLookmlResult(
        doc_=SQL_TO_LOOKML_DOC if describe else None,
        queries=mappings,
        dialect=dialect,
    )
