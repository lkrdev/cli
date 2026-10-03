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
    _as_list,
    _build_chain,
    _chain_root_pos,
    _collect_declarations,
    _extract_lookml_refs,
    _is_field_allowed_by_spec,
    _resolve_explore_base,
)
from lkr.parse.lookml import (
    LookmlDerivedTable,
    LookmlDimension,
    LookmlDimensionGroup,
    LookmlExplore,
    LookmlExploreSource,
    LookmlFilter,
    LookmlMeasure,
    LookmlModel,
    LookmlPositions,
    LookmlTest,
    LookmlView,
    parse_lookml,
)
from lkr.parse.sql import ParsedQuery, TableRef, _split_table_ref, parse_sql
from lkr.parse.types import (
    LookmlExploreFieldMatch,
    LookmlFieldMatch,
    LookmlSourceLocation,
    LookmlTestMatch,
    LookmlViewMatch,
    QueryLookmlMapping,
    SqlLookmlCompareResult,
    SqlToLookmlResult,
)

_SQL_TABLE_NAME_RE = re.compile(
    r"\$\{\s*([a-zA-Z0-9_]+)\.SQL_TABLE_NAME\s*\}", re.IGNORECASE
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
        if not out_col:
            continue
        for col_expr in proj.find_all(exp.Column):
            if not col_expr.name:
                continue
            c_low = col_expr.name.lower()
            t_qual = (col_expr.table or "").lower()
            cand_sources = (
                [sources[t_qual]] if t_qual in sources else list(sources.values())
            )
            for s in cand_sources:
                if isinstance(s, dict):
                    if c_low in s:
                        out_map.setdefault(out_col, []).extend(s[c_low])
                else:
                    out_map.setdefault(out_col, []).append((s, c_low))
    return out_map

__all__ = [
    "SQL_TO_LOOKML_DOC",
    "LookmlExploreFieldMatch",
    "LookmlFieldMatch",
    "LookmlSourceLocation",
    "LookmlTestMatch",
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


# in-memory lru_cache for connection metadata per process; no local file cache
@lru_cache(maxsize=128)
def _fetch_connection_metadata_sandbox(conn_name: str) -> dict[str, Any] | None:
    try:
        from lkr.codemode.main import run_python_code

        code = (
            f"c = connection({json.dumps(conn_name)})\n"
            "return {'database': c.get('database'), 'schema': c.get('schema'), 'dialect_name': c.get('dialect_name')}"
        )
        res_str = run_python_code(code)
        if not res_str:
            return None
        data = json.loads(res_str)
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], dict):
                return data["result"]
            return data
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not fetch connection metadata for '{conn_name}': {e}")
        return None
    return None


def _coerce_table(
    tbl: TableRef, db: str | None, schema: str | None, err_msg: str
) -> TableRef:
    if tbl.catalog and tbl.db:
        return tbl
    if tbl.db and not tbl.catalog:
        return tbl.model_copy(update={"catalog": db}) if db else tbl
    if not tbl.db and not tbl.catalog:
        if not schema and not db:
            raise ValueError(err_msg)
        return tbl.model_copy(
            update={"db": schema or db, "catalog": db if schema else None}
        )
    if tbl.catalog and not tbl.db and schema:
        return tbl.model_copy(update={"db": schema})
    return tbl


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
    parsed_query: ParsedQuery, dialect: str | None = None
) -> list[tuple[str | None, str]]:
    seen: set[tuple[str | None, str]] = set()
    result: list[tuple[str | None, str]] = []

    def _add(tbl: str | None, col: str) -> None:
        key = ((tbl or "").lower() or None, col.lower())
        if col and key not in seen:
            seen.add(key)
            result.append((tbl or None, col))

    for c in parsed_query.columns:
        if c.column:
            _add(c.table, c.column)

    try:
        eff_dialect = dialect or ("bigquery" if "`" in parsed_query.raw_sql else None)
        for expr in sqlglot.parse(parsed_query.raw_sql, read=eff_dialect):
            if expr is not None:
                for col_expr in expr.find_all(exp.Column):
                    if col_expr.name:
                        _add(col_expr.table or None, col_expr.name)
    except Exception:  # noqa: BLE001, S110
        pass

    return result


def _iter_view_fields(
    view_obj: LookmlView,
) -> list[tuple[str, str, LookmlDimension | LookmlDimensionGroup | LookmlMeasure]]:
    out: list[
        tuple[str, str, LookmlDimension | LookmlDimensionGroup | LookmlMeasure]
    ] = []
    for ftype, fdict in (
        ("dimension", view_obj.dimension or {}),
        ("dimension_group", view_obj.dimension_group or {}),
        ("measure", view_obj.measure or {}),
    ):
        for fname, fobj in fdict.items():
            if isinstance(
                fobj, (LookmlDimension, LookmlDimensionGroup, LookmlMeasure)
            ):
                out.append((ftype, fname, fobj))
    return out


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


def _match_model_views(
    pq: ParsedQuery,
    query_cols: list[tuple[str | None, str]],
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
) -> list[LookmlViewMatch]:
    eff_conn = lkml_conn or model_obj.connection
    meta = _fetch_connection_metadata_sandbox(eff_conn) if eff_conn else None
    eff_db = lkml_db or (meta.get("database") if meta else None)
    eff_schema = lkml_schema or (meta.get("schema") if meta else None)

    model_views: dict[str, LookmlView] = {}
    for k, v in (model_obj.view or {}).items():
        for view_obj in _as_list(v):
            if isinstance(view_obj, LookmlView):
                model_views[k] = view_obj
    view_chains = {
        vname: _build_chain(vname, view_base_decls, view_ref_decls)
        for vname in model_views
    }
    self_names_by_view = {
        vname: {v.name_.lower() for _, v, _ in chain if v.name_} | {vname.lower()}
        for vname, chain in view_chains.items()
    }

    aliases_for_view: dict[str, set[str]] = {
        vname: {vname.lower()} for vname in model_views
    }
    for exp_name, exp_obj in (model_obj.explore or {}).items():
        if not isinstance(exp_obj, LookmlExplore):
            continue
        exp_chain = _build_chain(exp_name, exp_base_decls, exp_ref_decls)
        b_view, b_alias, _, _ = _resolve_explore_base(
            exp_name, exp_obj, exp_chain, model_views
        )
        aliases_for_view.setdefault(b_view, {b_view.lower()}).add(b_alias.lower())
        for j_name, j_obj in (exp_obj.join or {}).items():
            jv_name = j_obj.from_ or j_obj.view_name or j_name
            aliases_for_view.setdefault(jv_name, {jv_name.lower()}).add(j_name.lower())

    test_infos = _collect_model_test_infos(
        model_name=model_name,
        model_obj=model_obj,
        test_base_decls=test_base_decls or {},
        test_ref_decls=test_ref_decls or {},
        positions=positions,
    )

    # (view_name, ftype, fname) -> (sql_table, sql_col, via_list, required_ext_aliases)
    matched_fields: dict[
        tuple[str, str, str], tuple[str, str, list[str], set[str]]
    ] = {}
    queue: deque[tuple[str, str, str]] = deque()
    direct_views: dict[str, str] = {}
    view_order: list[str] = []

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
        if dt.sql:
            clean_dt_sql = _SQL_TABLE_NAME_RE.sub(
                r"__lkml_tbl_\1", dt.sql.strip().rstrip(";").strip()
            )
            try:
                for expr in sqlglot.parse(clean_dt_sql):
                    for out_col, origins in _extract_dt_lineage(expr).items():
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
    for sql_tbl in pq.tables:
        raw_table_str = ".".join(
            p for p in (sql_tbl.catalog, sql_tbl.db, sql_tbl.name) if p
        )
        for view_name, view_obj in model_views.items():
            self_names = self_names_by_view[view_name]
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
                view_tbl = _coerce_table(
                    raw_cand_tbl,
                    eff_db,
                    eff_schema,
                    f"LookML view '{view_name}' table '{raw_cand_tbl.name}' cannot be qualified. "
                    f"Specify --lkml-schema and/or --lkml-db (or LKR_LKML_SCHEMA, LKR_LKML_DB) "
                    f"or ensure Looker {conn_info} metadata is accessible.",
                )
                if not _tables_match(sql_tbl, view_tbl):
                    continue
                if dt_col_pair is None and view_name not in direct_views:
                    direct_views[view_name] = raw_table_str
                    view_order.append(view_name)
                for tbl_qual, col_name in query_cols:
                    if dt_col_pair and col_name.lower() != dt_col_pair[1]:
                        continue
                    if tbl_qual and tbl_qual.lower() not in {
                        sql_tbl.name.lower(),
                        (sql_tbl.alias or "").lower(),
                        view_name.lower(),
                    }:
                        continue
                    target_col = dt_col_pair[0] if dt_col_pair else col_name
                    for ftype, fname, fobj in _iter_view_fields(view_obj):
                        tfs = (
                            fobj.timeframes
                            if isinstance(fobj, LookmlDimensionGroup)
                            else None
                        )
                        if not _field_matches_column(
                            target_col, fname, fobj.sql, ftype, tfs
                        ):
                            continue
                        key = (view_name, ftype, fname)
                        if key not in matched_fields:
                            if view_name not in direct_views:
                                direct_views[view_name] = raw_table_str
                                view_order.append(view_name)
                            ext_aliases = {
                                r.split(".", 1)[0].lower()
                                for r in _extract_lookml_refs(fobj.sql)
                                if "." in r
                                and r.split(".", 1)[0].lower() not in self_names
                            }
                            matched_fields[key] = (
                                raw_table_str,
                                col_name,
                                [],
                                ext_aliases,
                            )
                            queue.append(key)

    # Transitive forward ${...} and derived_table propagation
    while queue:
        src_view, src_ftype, src_fname = queue.popleft()
        src_tbl, src_col, src_via, src_ext = matched_fields[
            (src_view, src_ftype, src_fname)
        ]
        src_fobj = getattr(model_views[src_view], src_ftype)[src_fname]
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
                if ckey in matched_fields:
                    continue
                tfs = (
                    c_fobj.timeframes
                    if isinstance(c_fobj, LookmlDimensionGroup)
                    else None
                )
                hits_ndt = any(
                    _field_matches_column(ndt_col, c_fname, c_fobj.sql, c_ftype, tfs)
                    for ndt_col in matched_ndt_cols
                )
                refs = _extract_lookml_refs(c_fobj.sql)
                hits_ref = (
                    not c_fobj._sql_defaulted
                    and bool(refs)
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
                        for r in refs
                    )
                )
                if hits_ndt or hits_ref:
                    own_ext = {
                        r.split(".", 1)[0].lower()
                        for r in refs
                        if "." in r and r.split(".", 1)[0].lower() not in cand_self
                    }
                    matched_fields[ckey] = (
                        src_tbl,
                        src_col,
                        [*src_via, f"{src_view}.{src_fname}"],
                        own_ext if hits_ndt else (src_ext | own_ext),
                    )
                    queue.append(ckey)
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
            f_sql_tbl, col_name, via_list, req_ext = matched_fields[key]
            if not v_sql_tbl:
                v_sql_tbl = f_sql_tbl

            f_loc: LookmlSourceLocation | None = None
            f_sql_loc: LookmlSourceLocation | None = None
            for fpath, _, p_dict in chain:
                type_pos = p_dict.get(ftype, {})
                if isinstance(type_pos, dict) and fname in type_pos:
                    f_pos_dict = type_pos[fname]
                    if isinstance(f_pos_dict, dict):
                        if "$p" in f_pos_dict:
                            f_loc = _make_location(fpath, f_pos_dict["$p"])
                        sql_p = f_pos_dict.get("sql", {})
                        if isinstance(sql_p, dict) and "$p" in sql_p:
                            f_sql_loc = _make_location(fpath, sql_p["$p"])

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
                req_ext,
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
            v_fields.append(
                LookmlFieldMatch(
                    sql_column=col_name,
                    field_type=ftype,
                    field_name=fname,
                    sql=fobj.sql.strip() if fobj.sql else None,
                    via=via_list,
                    file=loc.file,
                    line=loc.line,
                    end_line=loc.end_line,
                    position=loc.position,
                    sql_location=f_sql_loc,
                    explores=exp_matches,
                    tests=test_matches,
                )
            )

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
) -> SqlToLookmlResult:
    """Parse SQL queries and map referenced tables and columns to LookML views/fields with file and line locations."""
    sql_db = sql_db or os.getenv("LKR_SQL_DB")
    sql_schema = sql_schema or os.getenv("LKR_SQL_SCHEMA")
    lkml_conn = lkml_conn or os.getenv("LKR_LKML_CONN")
    lkml_db = lkml_db or os.getenv("LKR_LKML_DB")
    lkml_schema = lkml_schema or os.getenv("LKR_LKML_SCHEMA")

    sql_res = parse_sql(sql=sql, file=sql_file, dialect=dialect)
    project = parse_lookml(path=path, file=lookml_file, lookml=lookml).apply_defaults()

    view_base_decls, view_ref_decls = _collect_declarations(project, "view", LookmlView)
    exp_base_decls, exp_ref_decls = _collect_declarations(
        project, "explore", LookmlExplore
    )
    test_base_decls, test_ref_decls = _collect_declarations(
        project, "test", LookmlTest
    )
    models: dict[str, LookmlModel] = project.model or {}

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
        query_cols = _extract_query_columns(pq, dialect=dialect)
        view_matches = [
            vm
            for model_name, model_obj in models.items()
            for vm in _match_model_views(
                pq,
                query_cols,
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
            )
        ]
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
        mappings.append(
            QueryLookmlMapping(
                raw_sql=pq.raw_sql,
                parsed_query=pq,
                views=view_matches,
                explores=query_explores,
                tests=query_tests,
            )
        )

    return SqlToLookmlResult(
        doc_=SQL_TO_LOOKML_DOC if describe else None,
        queries=mappings,
        dialect=dialect,
    )
