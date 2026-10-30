from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, NamedTuple

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ErrorLevel, SqlglotError
from sqlglot.optimizer.pushdown_projections import pushdown_projections
from sqlglot.optimizer.qualify import qualify
from sqlglot.tokens import Token, TokenType

__all__ = [
    "CTESpec",
    "ColumnSpec",
    "ComplexityLabel",
    "JoinSpec",
    "ParsedQuery",
    "SqlGroupResult",
    "SqlParseResult",
    "SqlQueryGroup",
    "TableRef",
    "compute_sql_complexity",
    "group_sql_queries",
    "parse_sql",
    "query_similarity",
]

ComplexityLabel = Literal[
    "trivial",
    "simple",
    "low_moderate",
    "moderate",
    "moderate_high",
    "complex",
    "very_complex",
]

_COMPLEXITY_TIERS: tuple[tuple[float, int, ComplexityLabel], ...] = (
    (15.0, 1, "trivial"),
    (30.0, 2, "simple"),
    (45.0, 3, "low_moderate"),
    (60.0, 4, "moderate"),
    (75.0, 5, "moderate_high"),
    (90.0, 6, "complex"),
    (101.0, 7, "very_complex"),
)


class TableRef(BaseModel):
    name: str
    db: str | None = None
    catalog: str | None = None
    alias: str | None = None


class JoinSpec(BaseModel):
    table: str
    side: str | None = None
    kind: str | None = None
    on_sql: str | None = None
    left_table: TableRef | None = None
    right_table: TableRef | None = None
    join_type: str = "INNER"
    equi_joins: list[tuple[tuple[str, str], tuple[str, str]]] = Field(
        default_factory=list
    )
    non_equi_conditions: list[str] = Field(default_factory=list)


class ColumnSpec(BaseModel):
    alias: str | None = None
    sql: str
    table: str | None = None
    column: str | None = None
    is_agg: bool = False
    except_: list[str] = Field(default_factory=list)
    replace: dict[str, str] = Field(default_factory=dict)
    rename: dict[str, str] = Field(default_factory=dict)


class CTESpec(BaseModel):
    name: str
    sql: str


class ParsedQuery(BaseModel):
    statement_type: str | None = None
    raw_sql: str
    tables: list[TableRef] = Field(default_factory=list)
    ctes: list[CTESpec] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    columns: list[ColumnSpec] = Field(default_factory=list)
    where: str | None = None
    having: str | None = None
    group_by: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: str | None = None
    error: str | None = None
    frequency: int = 1
    complexity_score: float = 0.0
    complexity_tier: int = 1
    complexity_label: ComplexityLabel = "trivial"


class SqlParseResult(BaseModel):
    queries: list[ParsedQuery] = Field(default_factory=list)
    dialect: str | None = None


class SqlQueryGroup(BaseModel):
    group_id: int
    query_count: int
    total_frequency: int = 0
    complexity_score: float = 0.0
    complexity_tier: int = 1
    complexity_label: ComplexityLabel = "trivial"
    max_query_complexity: float = 0.0
    avg_query_complexity: float = 0.0
    min_similarity: float = 1.0
    avg_similarity: float = 1.0
    statement_type: str | None = None
    representative_sql: str
    tables: list[TableRef] = Field(default_factory=list)
    ctes: list[CTESpec] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    columns: list[ColumnSpec] = Field(default_factory=list)
    where_conditions: list[str] = Field(default_factory=list)
    having_conditions: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: str | None = None
    query_indices: list[int] = Field(default_factory=list)


class SqlGroupResult(BaseModel):
    total_queries: int = 0
    valid_queries: int = 0
    total_frequency: int = 0
    group_count: int = 0
    threshold: float = 0.7
    dialect: str | None = None
    groups: list[SqlQueryGroup] = Field(default_factory=list)
    errors: list[ParsedQuery] = Field(default_factory=list)


def _main_select(expr: exp.Expr) -> exp.Select | None:
    target = (
        expr.expression
        if isinstance(expr, (exp.Create, exp.Insert)) and expr.expression
        else expr
    )
    while isinstance(target, (exp.Subquery, exp.Paren, exp.SetOperation)):
        target = target.this
    return target if isinstance(target, exp.Select) else None


def _all_selects(expr: exp.Expr) -> list[exp.Select]:
    target = (
        expr.expression
        if isinstance(expr, (exp.Create, exp.Insert)) and expr.expression
        else expr
    )
    while isinstance(target, (exp.Subquery, exp.Paren)):
        target = target.this
    if isinstance(target, exp.SetOperation):
        return [
            *(
                _all_selects(target.this)
                if isinstance(target.this, exp.Expr)
                else []
            ),
            *(
                _all_selects(target.expression)
                if isinstance(target.expression, exp.Expr)
                else []
            ),
        ]
    return [target] if isinstance(target, exp.Select) else []


def _split_table_ref(tbl: exp.Table) -> TableRef:
    name = tbl.name.strip("`\"'[] ")
    db = (tbl.db or "").strip("`\"'[] ") or None
    catalog = (tbl.catalog or "").strip("`\"'[] ") or None
    if not db and not catalog and "." in name:
        parts = [p.strip("`\"'[] ") for p in name.split(".") if p.strip("`\"'[] ")]
        catalog, db, name = ([None, None, *parts])[-3:]
    return TableRef(
        name=name or "",
        db=db,
        catalog=catalog,
        alias=tbl.alias or None,
    )


def _apply_default_db_schema(
    tbl: TableRef, db: str | None, schema: str | None
) -> TableRef:
    if tbl.catalog and tbl.db:
        return tbl
    if tbl.db and not tbl.catalog:
        return tbl.model_copy(update={"catalog": db}) if db else tbl
    if not tbl.db and not tbl.catalog and (schema or db):
        return tbl.model_copy(
            update={"db": schema or db, "catalog": db if schema else None}
        )
    if tbl.catalog and not tbl.db and schema:
        return tbl.model_copy(update={"db": schema})
    return tbl


def _get_star(proj: exp.Expr) -> exp.Star | None:
    inner = proj.this if isinstance(proj, exp.Alias) else proj
    if isinstance(inner, exp.Star):
        return inner
    if isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star):
        return inner.this
    return None


def _has_projection_star(expr: exp.Expr) -> bool:
    return any(
        not isinstance(s.parent, exp.AggFunc) for s in expr.find_all(exp.Star)
    )


def _col_spec_from_proj(proj: exp.Expr, dialect: str | None = None) -> ColumnSpec:
    inner = proj.this if isinstance(proj, exp.Alias) else proj
    star = _get_star(proj)
    if star is not None:
        return ColumnSpec(
            alias=proj.alias or None,
            sql=proj.sql(dialect=dialect),
            table=(inner.table or None) if isinstance(inner, exp.Column) else None,
            column=None,
            is_agg=False,
            except_=[e.name for e in (star.args.get("except_") or []) if e.name],
            replace={
                e.alias: e.this.sql(dialect=dialect)
                for e in (star.args.get("replace") or [])
                if isinstance(e, exp.Alias) and e.alias and e.this
            },
            rename={
                e.this.name: e.alias
                for e in (star.args.get("rename") or [])
                if isinstance(e, exp.Alias) and e.this and e.this.name and e.alias
            },
        )
    return ColumnSpec(
        alias=proj.alias or None,
        sql=proj.sql(dialect=dialect),
        table=(inner.table or None) if isinstance(inner, exp.Column) else None,
        column=(inner.name or None) if isinstance(inner, exp.Column) else None,
        is_agg=bool(inner.find(exp.AggFunc)),
    )


def _optimize_stars(
    expr: exp.Expr,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> exp.Expr:
    if not _has_projection_star(expr):
        return expr
    cte_names = {
        cte.alias_or_name.lower()
        for cte in expr.find_all(exp.CTE)
        if cte.alias_or_name
    }
    if not (schema or cte_names or expr.find(exp.Subquery)):
        return expr

    norm_schema: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        (cat or "").lower() or "__default_cat__": {
            (db or "").lower() or "__default_db__": {
                t.lower(): {k.lower(): v for k, v in cols.items()}
                for t, cols in tbls.items()
                if cols
            }
            for db, tbls in dbs.items()
        }
        for cat, dbs in (schema or {}).items()
    }

    def _run(base_expr: exp.Expr, active_schema: dict[str, Any] | None) -> tuple[exp.Expr, exp.Expr]:
        e = base_expr.copy()
        for tbl in e.find_all(exp.Table):
            if tbl.name and tbl.name.lower() not in cte_names:
                t_ref = _split_table_ref(tbl)
                if not t_ref.name.lower().startswith("__lkml_tbl_"):
                    t_ref = _apply_default_db_schema(t_ref, default_db, default_schema)
                tbl.set("this", exp.to_identifier(t_ref.name))
                if not tbl.alias:
                    tbl.set("alias", exp.TableAlias(this=exp.to_identifier(t_ref.name)))
                tbl.set(
                    "catalog",
                    exp.to_identifier((t_ref.catalog or "").lower() or "__default_cat__"),
                )
                tbl.set(
                    "db",
                    exp.to_identifier((t_ref.db or "").lower() or "__default_db__"),
                )
        q = qualify(
            e,
            schema=active_schema or None,
            infer_schema=True,
            allow_partial_qualification=True,
            validate_qualify_columns=False,
            quote_identifiers=False,
            identify=False,
        )
        p = pushdown_projections(q, schema=active_schema or None)
        for node in (q, p):
            for tbl in node.find_all(exp.Table):
                if tbl.catalog == "__default_cat__":
                    tbl.set("catalog", None)
                if tbl.db == "__default_db__":
                    tbl.set("db", None)
        return q, p

    try:
        q1, p = _run(expr, norm_schema)
        if _has_projection_star(p):
            extra_cols = {"__unmodeled__": "UNKNOWN"}
            for star in p.find_all(exp.Star):
                for r in star.args.get("replace") or []:
                    if isinstance(r, exp.Alias) and r.alias:
                        extra_cols[r.alias.lower()] = "UNKNOWN"
                for r in star.args.get("rename") or []:
                    if isinstance(r, exp.Alias) and r.this and r.this.name:
                        extra_cols[r.this.name.lower()] = "UNKNOWN"
            for tbl in q1.find_all(exp.Table):
                if tbl.name and tbl.name.lower() not in cte_names:
                    cat = (tbl.catalog or "").lower() or "__default_cat__"
                    db = (tbl.db or "").lower() or "__default_db__"
                    norm_schema.setdefault(cat, {}).setdefault(db, {}).setdefault(
                        tbl.name.lower(), dict(extra_cols)
                    )
            _, p = _run(q1, norm_schema)

        sel, opt_sel = _main_select(expr), _main_select(p)
        orig_stars = [s for s in (sel.selects if sel else ()) if _get_star(s) is not None]
        if opt_sel is not None and orig_stars:
            if not any(
                (proj.this if isinstance(proj, exp.Alias) else proj).name != "__unmodeled__"
                and _get_star(proj) is None
                for proj in opt_sel.selects
            ):
                return expr
            new_exprs: list[exp.Expr] = []
            for proj in opt_sel.selects:
                inner = proj.this if isinstance(proj, exp.Alias) else proj
                if isinstance(inner, exp.Column) and inner.name == "__unmodeled__":
                    t_low = (inner.table or "").lower()
                    orig = next(
                        (
                            s
                            for s in orig_stars
                            if (
                                getattr(s.this if isinstance(s, exp.Alias) else s, "table", None)
                                or ""
                            ).lower()
                            == t_low
                        ),
                        orig_stars[0] if orig_stars else None,
                    )
                    if orig is not None:
                        orig_stars.remove(orig)
                        new_exprs.append(orig)
                else:
                    new_exprs.append(proj)
            opt_sel.set("expressions", new_exprs)
        return p
    except Exception:  # noqa: BLE001
        return expr


def _normalize_sql_join_type(side: str | None, kind: str | None) -> str:
    s = (side or "").upper()
    k = (kind or "").upper()
    if "FULL" in s or "FULL" in k:
        return "FULL"
    if "LEFT" in s or "LEFT" in k:
        return "LEFT"
    if "RIGHT" in s or "RIGHT" in k:
        return "RIGHT"
    if "CROSS" in s or "CROSS" in k:
        return "CROSS"
    return "INNER"


def _get_conjuncts(node: exp.Expr | None) -> list[exp.Expr]:
    if node is None:
        return []
    if isinstance(node, exp.And):
        return [*_get_conjuncts(node.left), *_get_conjuncts(node.right)]
    if isinstance(node, exp.Paren):
        return _get_conjuncts(node.this)
    return [node]


def _extract_query(
    expr: exp.Expr,
    raw_sql: str,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> ParsedQuery:
    ctes = [
        CTESpec(name=cte.alias_or_name, sql=cte.this.sql(dialect=dialect))
        for cte in expr.find_all(exp.CTE)
        if cte.this is not None
    ]
    cte_names = {c.name.lower() for c in ctes if c.name}

    cte_table_map: dict[str, TableRef] = {}
    for cte in expr.find_all(exp.CTE):
        if cte.alias_or_name and cte.this is not None:
            c_sel = _main_select(cte.this)
            if c_sel is not None:
                c_from = c_sel.args.get("from") or c_sel.args.get("from_")
                if c_from and isinstance(c_from.this, exp.Table):
                    t_ref = _split_table_ref(c_from.this)
                    t_ref = _apply_default_db_schema(t_ref, default_db, default_schema)
                    t_name_low = t_ref.name.lower()
                    if t_name_low in cte_table_map:
                        t_ref = cte_table_map[t_name_low].model_copy(
                            update={"alias": t_ref.alias or t_ref.name}
                        )
                    cte_table_map[cte.alias_or_name.lower()] = t_ref

    def _resolve_table_ref(
        tbl_expr: exp.Expr | None, alias: str | None = None
    ) -> TableRef:
        if isinstance(tbl_expr, exp.Table):
            t_ref = _split_table_ref(tbl_expr)
            t_ref = _apply_default_db_schema(t_ref, default_db, default_schema)
            if alias:
                t_ref = t_ref.model_copy(update={"alias": alias})
            name_low = t_ref.name.lower()
            if name_low in cte_table_map:
                resolved = cte_table_map[name_low].model_copy(
                    update={"alias": t_ref.alias or t_ref.name}
                )
                return _apply_default_db_schema(resolved, default_db, default_schema)
            return t_ref
        elif isinstance(tbl_expr, exp.Subquery):
            sub_sel = _main_select(tbl_expr.this)
            if sub_sel is not None:
                sub_from = sub_sel.args.get("from") or sub_sel.args.get("from_")
                if sub_from and isinstance(sub_from.this, exp.Expr):
                    return _resolve_table_ref(
                        sub_from.this, alias=alias or tbl_expr.alias
                    )
            return TableRef(name=alias or tbl_expr.alias or "subquery", alias=alias or tbl_expr.alias)
        return TableRef(name=str(tbl_expr) if tbl_expr else "", alias=alias)

    tables = [
        _split_table_ref(tbl)
        for tbl in expr.find_all(exp.Table)
        if tbl.name and tbl.name.lower() not in cte_names
    ]

    selects = _all_selects(expr)
    opt_selects = (
        _all_selects(
            _optimize_stars(expr, dialect, schema, default_db, default_schema)
        )
        if any(_get_star(p) is not None for s in selects for p in s.selects)
        else selects
    )
    columns: list[ColumnSpec] = []
    seen_cols: set[tuple[str | None, str, str | None, str | None]] = set()
    joins: list[JoinSpec] = []
    where_parts: list[str] = []
    having_parts: list[str] = []
    group_by: list[str] = []
    order_by: list[str] = []

    for idx, sel in enumerate(selects):
        proj_sel = opt_selects[idx] if idx < len(opt_selects) else sel
        for proj in proj_sel.selects:
            cs = _col_spec_from_proj(proj, dialect)
            ckey = (cs.alias, cs.sql, cs.table, cs.column)
            if ckey not in seen_cols or len(selects) == 1:
                seen_cols.add(ckey)
                columns.append(cs)

        tables_by_alias: dict[str, TableRef] = {}
        tables_in_scope: list[TableRef] = []

        from_clause = sel.args.get("from") or sel.args.get("from_")
        if from_clause and from_clause.this is not None:
            f_this = from_clause.this
            f_alias = (
                getattr(f_this, "alias", None)
                or (getattr(f_this, "name", None) if isinstance(f_this, exp.Table) else "")
            )
            from_tbl_ref = _resolve_table_ref(f_this, alias=f_alias or None)
            if from_tbl_ref.name:
                if from_tbl_ref.alias:
                    tables_by_alias[from_tbl_ref.alias.lower()] = from_tbl_ref
                tables_by_alias[from_tbl_ref.name.lower()] = from_tbl_ref
                tables_in_scope.append(from_tbl_ref)

        for j in sel.args.get("joins") or []:
            on_expr = j.args.get("on")
            using_expr = j.args.get("using")
            j_this = j.this
            j_alias = (
                getattr(j_this, "alias", None)
                or (getattr(j_this, "name", None) if isinstance(j_this, exp.Table) else "")
            )
            right_table = (
                _resolve_table_ref(j_this, alias=j_alias or None)
                if j_this is not None
                else None
            )
            right_keys = {
                k.lower()
                for k in [
                    j_alias,
                    right_table.alias if right_table else None,
                    right_table.name if right_table else None,
                ]
                if k
            }
            if right_table:
                if right_table.alias:
                    tables_by_alias[right_table.alias.lower()] = right_table
                tables_by_alias[right_table.name.lower()] = right_table

            join_type = _normalize_sql_join_type(j.side, j.kind)
            equi_joins: list[tuple[tuple[str, str], tuple[str, str]]] = []
            non_equi: list[str] = []
            detected_left: TableRef | None = None

            if on_expr:
                for conj in _get_conjuncts(on_expr):
                    if (
                        isinstance(conj, exp.EQ)
                        and isinstance(conj.left, exp.Column)
                        and isinstance(conj.right, exp.Column)
                    ):
                        c_left, c_right = conj.left, conj.right
                        t_left = (c_left.table or "").lower()
                        t_right = (c_right.table or "").lower()
                        if t_right in right_keys and t_left not in right_keys:
                            r_col = c_right.name
                            l_col = c_left.name
                            l_ref = tables_by_alias.get(t_left) or TableRef(
                                name=c_left.table or "unknown"
                            )
                            detected_left = detected_left or l_ref
                            r_tbl_name = right_table.name if right_table else ""
                            equi_joins.append(((l_ref.name, l_col), (r_tbl_name, r_col)))
                        elif t_left in right_keys and t_right not in right_keys:
                            r_col = c_left.name
                            l_col = c_right.name
                            l_ref = tables_by_alias.get(t_right) or TableRef(
                                name=c_right.table or "unknown"
                            )
                            detected_left = detected_left or l_ref
                            r_tbl_name = right_table.name if right_table else ""
                            equi_joins.append(((l_ref.name, l_col), (r_tbl_name, r_col)))
                        else:
                            non_equi.append(conj.sql(dialect=dialect))
                    else:
                        non_equi.append(conj.sql(dialect=dialect))

            if using_expr:
                using_cols = (
                    using_expr if isinstance(using_expr, list) else [using_expr]
                )
                def_left = (
                    tables_in_scope[-1]
                    if tables_in_scope
                    else TableRef(name="unknown")
                )
                detected_left = detected_left or def_left
                r_tbl_name = right_table.name if right_table else ""
                for u in using_cols:
                    u_name = (
                        u.name
                        if isinstance(u, (exp.Column, exp.Identifier))
                        else str(u)
                    )
                    equi_joins.append(
                        ((detected_left.name, u_name), (r_tbl_name, u_name))
                    )

            if not detected_left and tables_in_scope:
                detected_left = tables_in_scope[-1]

            if right_table:
                tables_in_scope.append(right_table)

            joins.append(
                JoinSpec(
                    table=j.this.sql(dialect=dialect) if j.this else "",
                    side=j.side or None,
                    kind=j.kind or None,
                    on_sql=on_expr.sql(dialect=dialect) if on_expr else None,
                    left_table=detected_left,
                    right_table=right_table,
                    join_type=join_type,
                    equi_joins=equi_joins,
                    non_equi_conditions=non_equi,
                )
            )

        w_expr = sel.args.get("where")
        if isinstance(w_expr, exp.Where) and w_expr.this is not None:
            w_sql = w_expr.this.sql(dialect=dialect)
            if w_sql not in where_parts:
                where_parts.append(w_sql)
        h_expr = sel.args.get("having")
        if isinstance(h_expr, exp.Having) and h_expr.this is not None:
            h_sql = h_expr.this.sql(dialect=dialect)
            if h_sql not in having_parts:
                having_parts.append(h_sql)
        g_expr = sel.args.get("group")
        if isinstance(g_expr, exp.Group):
            for e in g_expr.expressions:
                gsql = e.sql(dialect=dialect)
                if gsql not in group_by or len(selects) == 1:
                    group_by.append(gsql)
        o_expr = sel.args.get("order")
        if isinstance(o_expr, exp.Order):
            for e in o_expr.expressions:
                osql = e.sql(dialect=dialect)
                if osql not in order_by or len(selects) == 1:
                    order_by.append(osql)

    top_where = expr.args.get("where")
    if isinstance(top_where, exp.Where) and top_where.this is not None:
        tw_sql = top_where.this.sql(dialect=dialect)
        if tw_sql not in where_parts:
            where_parts.append(tw_sql)

    top_order = expr.args.get("order")
    if isinstance(top_order, exp.Order):
        for e in top_order.expressions:
            osql = e.sql(dialect=dialect)
            if osql not in order_by:
                order_by.append(osql)

    sel0 = selects[0] if selects else None
    limit_expr = expr.args.get("limit") or (
        sel0.args.get("limit") if sel0 is not None else None
    )

    limit_val: str | None = None
    if isinstance(limit_expr, exp.Limit) and limit_expr.expression is not None:
        limit_val = limit_expr.expression.sql(dialect=dialect)
    elif isinstance(limit_expr, exp.Fetch) and limit_expr.this is not None:
        limit_val = limit_expr.this.sql(dialect=dialect)

    pq = ParsedQuery(
        statement_type=expr.key.upper(),
        raw_sql=raw_sql,
        tables=tables,
        ctes=ctes,
        joins=joins,
        columns=columns,
        where=" AND ".join(where_parts) if where_parts else None,
        having=" AND ".join(having_parts) if having_parts else None,
        group_by=group_by,
        order_by=order_by,
        limit=limit_val,
    )
    score, tier, label = compute_sql_complexity(pq, expr=expr, dialect=dialect)
    pq.complexity_score = score
    pq.complexity_tier = tier
    pq.complexity_label = label
    return pq


def parse_sql(
    sql: str | None = None,
    file: Path | str | None = None,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> SqlParseResult:
    """Parse one or more semicolon-delimited SQL queries into structured Pydantic models."""
    if bool(sql is not None) == bool(file is not None):
        raise ValueError("Specify exactly one of 'sql' or 'file'")

    sql_text = (
        Path(file).read_text(encoding="utf-8") if file is not None else (sql or "")
    )
    if not sql_text.strip():
        return SqlParseResult(queries=[], dialect=dialect)

    try:
        dialect_obj = Dialect.get_or_raise(dialect)
        tokens = dialect_obj.tokenize(sql_text)
    except SqlglotError as e:
        return SqlParseResult(
            queries=[ParsedQuery(raw_sql=sql_text.strip(), error=str(e))],
            dialect=dialect,
        )

    chunks: list[list[Token]] = [[]]
    for tok in tokens:
        if tok.token_type == TokenType.SEMICOLON:
            chunks.append([])
        else:
            chunks[-1].append(tok)

    queries: list[ParsedQuery] = []
    for chunk in chunks:
        if not chunk:
            continue
        raw_chunk = sql_text[chunk[0].start : chunk[-1].end + 1].strip()
        if not raw_chunk:
            continue
        try:
            parsed_list = sqlglot.parse(
                raw_chunk, read=dialect, error_level=ErrorLevel.RAISE
            )
            used_dialect = dialect
        except SqlglotError as e:
            if dialect is None and "`" in raw_chunk:
                try:
                    parsed_list = sqlglot.parse(
                        raw_chunk, read="bigquery", error_level=ErrorLevel.RAISE
                    )
                    used_dialect = "bigquery"
                except SqlglotError:
                    queries.append(ParsedQuery(raw_sql=raw_chunk, error=str(e)))
                    continue
            else:
                queries.append(ParsedQuery(raw_sql=raw_chunk, error=str(e)))
                continue

        for expr in parsed_list:
            if expr is not None:
                queries.append(
                    _extract_query(
                        expr,
                        raw_chunk,
                        dialect=used_dialect,
                        schema=schema,
                        default_db=default_db,
                        default_schema=default_schema,
                    )
                )

    return SqlParseResult(queries=queries, dialect=dialect)


def _tbl_key(
    t: TableRef, default_db: str | None = None, default_schema: str | None = None
) -> tuple[str, str, str]:
    rt = _apply_default_db_schema(t, default_db, default_schema)
    return ((rt.catalog or "").lower(), (rt.db or "").lower(), rt.name.lower())


def _tbl_fqn(key: tuple[str, str, str]) -> str:
    return ".".join(p for p in key if p)


def _parse_expr_safe(sql_str: str, dialect: str | None = None) -> exp.Expr | None:
    try:
        return sqlglot.parse_one(sql_str, read=dialect, error_level=ErrorLevel.IGNORE)
    except Exception:  # noqa: BLE001
        return None


def _split_conjuncts_sql(
    sql_str: str | None, dialect: str | None = None
) -> list[exp.Expr]:
    if not sql_str or not sql_str.strip():
        return []
    node = _parse_expr_safe(sql_str, dialect=dialect)
    return _get_conjuncts(node) if node is not None else []


def _tier_for_score(score: float) -> tuple[float, int, ComplexityLabel]:
    for upper, tier, label in _COMPLEXITY_TIERS:
        if score < upper:
            return score, tier, label
    return score, 7, "very_complex"


def compute_sql_complexity(
    q: ParsedQuery | SqlQueryGroup,
    expr: exp.Expr | None = None,
    dialect: str | None = None,
) -> tuple[float, int, ComplexityLabel]:
    """Compute a normalized 0-100 complexity score, tier (1-7), and label for a query or group."""
    if isinstance(q, ParsedQuery) and q.error is not None:
        return 0.0, 1, "trivial"

    unique_tables = {_tbl_key(t) for t in q.tables if t.name}
    points = (1.0 + 2.0 * (len(unique_tables) - 1)) if unique_tables else 0.0

    for j in q.joins:
        points += 4.5 if j.join_type in ("FULL", "CROSS") else 3.0
        points += 2.5 * len(j.non_equi_conditions)
        points += 0.5 * max(0, len(j.equi_joins) - 1)

    points += 4.0 * len(q.ctes)

    if (q.statement_type or "").upper() in ("UNION", "INTERSECT", "EXCEPT"):
        set_ops = (
            sum(1 for _ in expr.find_all(exp.SetOperation))
            if expr is not None
            else 1
        )
        points += 5.0 * max(1, set_ops)

    points += 0.5 * len(q.columns)
    points += 1.5 * sum(1 for c in q.columns if c.is_agg)

    raw_sql = (
        q.raw_sql
        if isinstance(q, ParsedQuery)
        else getattr(q, "representative_sql", None)
    )
    ast_node = expr or (
        _parse_expr_safe(raw_sql, dialect=dialect) if raw_sql else None
    )
    nodes = (
        [ast_node]
        if ast_node is not None
        else [
            n
            for c in q.columns
            if (n := _parse_expr_safe(c.sql, dialect=dialect)) is not None
        ]
    )
    for node in nodes:
        points += 3.0 * sum(1 for _ in node.find_all(exp.Window))
        points += 1.5 * sum(1 for _ in node.find_all(exp.Case))
        points += 3.5 * sum(1 for _ in node.find_all(exp.Subquery))

    if isinstance(q, SqlQueryGroup):
        where_cnt = len(q.where_conditions)
        having_cnt = len(q.having_conditions)
    else:
        where_cnt = len(_split_conjuncts_sql(q.where, dialect=dialect)) or (
            1 if q.where else 0
        )
        having_cnt = len(_split_conjuncts_sql(q.having, dialect=dialect)) or (
            1 if q.having else 0
        )

    points += 1.5 * where_cnt
    points += 2.0 * having_cnt
    points += 1.5 * len(q.group_by)
    points += 0.5 * len(q.order_by)
    if q.limit is not None:
        points += 0.5

    score = (
        round(min(100.0, 100.0 * (1.0 - (2.0 ** (-points / 16.0)))), 2)
        if points > 0
        else 0.0
    )
    return _tier_for_score(score)


class _QueryFeatures(NamedTuple):
    statement_type: str
    tables: frozenset[tuple[str, str, str]]
    joins: frozenset[str]
    join_edges: frozenset[str]
    is_star_only: bool
    col_skeletons: frozenset[str]
    group_by: frozenset[str]
    where_cols: frozenset[str]
    where_skeletons: frozenset[str]
    template_key: tuple[Any, ...]


def _build_alias_map(
    q: ParsedQuery,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> tuple[dict[str, str], str]:
    alias_map: dict[str, str] = {}
    fqns: set[str] = set()
    for t in [
        *q.tables,
        *(jt for j in q.joins for jt in (j.left_table, j.right_table) if jt),
    ]:
        if t.name:
            fqn = _tbl_fqn(_tbl_key(t, default_db, default_schema))
            fqns.add(fqn)
            alias_map[t.name.lower()] = fqn
            if t.alias:
                alias_map[t.alias.lower()] = fqn
    default_tbl = next(iter(fqns)) if len(fqns) == 1 else ""
    return alias_map, default_tbl


def _skeletonize_expr(
    sql_str: str,
    alias_map: dict[str, str],
    default_tbl: str,
    strip_literals: bool = True,
    dialect: str | None = None,
) -> tuple[str, frozenset[str]]:
    node = _parse_expr_safe(sql_str, dialect=dialect)
    if node is None:
        return sql_str.strip().lower(), frozenset()

    node = (
        node.this.copy()
        if isinstance(node, exp.Alias) and node.this is not None
        else node.copy()
    )
    cols: set[str] = set()

    def _transform(n: exp.Expr) -> exp.Expr:
        if isinstance(n, exp.Column):
            t_raw = (n.table or "").lower()
            t_res = alias_map.get(t_raw, t_raw or default_tbl)
            is_star = isinstance(n.this, exp.Star)
            c_name = n.name.lower()
            if not is_star and c_name:
                cols.add(f"{t_res}.{c_name}" if t_res else c_name)
            return exp.Column(
                this=exp.Star() if is_star else exp.to_identifier(c_name),
                table=exp.to_identifier(t_res) if t_res else None,
            )
        if strip_literals:
            if (
                isinstance(n, exp.In)
                and n.expressions
                and not any(
                    isinstance(sub, exp.Column)
                    for e in n.expressions
                    for sub in e.find_all(exp.Column)
                )
            ):
                n_copy = n.copy()
                n_copy.set("this", _transform(n_copy.this))
                n_copy.set("expressions", [exp.var("?")])
                return n_copy
            if isinstance(
                n,
                (
                    exp.Cast,
                    exp.TryCast,
                    exp.Date,
                    exp.Timestamp,
                    exp.Datetime,
                    exp.Time,
                    exp.DateStrToDate,
                    exp.TsOrDsToDate,
                ),
            ) and not list(n.find_all(exp.Column)):
                return exp.var("?")
            if isinstance(n, (exp.Literal, exp.Boolean)):
                return exp.var("?")
        return n

    transformed = node.transform(_transform)
    return transformed.sql(dialect=dialect).lower(), frozenset(cols)


def _join_sigs(
    j: JoinSpec,
    alias_map: dict[str, str],
    default_tbl: str,
    dialect: str | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> tuple[str, str]:
    l_fqn = (
        _tbl_fqn(_tbl_key(j.left_table, default_db, default_schema))
        if j.left_table and j.left_table.name
        else ""
    )
    r_fqn = (
        _tbl_fqn(_tbl_key(j.right_table, default_db, default_schema))
        if j.right_table and j.right_table.name
        else alias_map.get(j.table.lower(), j.table.lower())
    )
    tbl_pair = tuple(sorted((l_fqn, r_fqn)))
    equi = tuple(
        sorted(
            tuple(
                sorted(
                    (
                        f"{alias_map.get(lt.lower(), l_fqn or lt.lower())}.{lc.lower()}",
                        f"{alias_map.get(rt.lower(), r_fqn or rt.lower())}.{rc.lower()}",
                    )
                )
            )
            for (lt, lc), (rt, rc) in j.equi_joins
        )
    )
    non_equi = tuple(
        sorted(
            _skeletonize_expr(
                ne, alias_map, default_tbl, strip_literals=True, dialect=dialect
            )[0]
            for ne in j.non_equi_conditions
        )
    )
    edge_sig = f"{tbl_pair}:{equi}:{non_equi}"
    eff_type, eff_l, eff_r = (
        ("LEFT", r_fqn, l_fqn)
        if j.join_type == "RIGHT"
        else (j.join_type, l_fqn, r_fqn)
    )
    if eff_type in ("INNER", "FULL", "CROSS"):
        typed_sig = f"{eff_type}:{tbl_pair}:{equi}:{non_equi}"
    else:
        typed_sig = f"{eff_type}:{eff_l}->{eff_r}:{equi}:{non_equi}"
    return edge_sig, typed_sig


def _extract_features(
    q: ParsedQuery,
    dialect: str | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> _QueryFeatures:
    tables = frozenset(
        _tbl_key(t, default_db, default_schema) for t in q.tables if t.name
    )
    alias_map, default_tbl = _build_alias_map(q, default_db, default_schema)

    join_edges: set[str] = set()
    join_sigs: set[str] = set()
    for j in q.joins:
        edge_sig, typed_sig = _join_sigs(
            j, alias_map, default_tbl, dialect, default_db, default_schema
        )
        join_edges.add(edge_sig)
        join_sigs.add(typed_sig)

    is_star_only = bool(q.columns) and all(
        c.column is None
        and (c.sql.strip() == "*" or c.sql.strip().endswith(".*"))
        and not c.except_
        and not c.replace
        and not c.rename
        for c in q.columns
    )
    col_skeletons: set[str] = set()
    for c in q.columns:
        if c.column is None and (c.sql.strip() == "*" or c.sql.strip().endswith(".*")):
            t_res = (
                alias_map.get(c.table.lower(), c.table.lower())
                if c.table
                else default_tbl
            )
            col_skeletons.add(f"{t_res}.*" if t_res else "*")
        else:
            skel, _ = _skeletonize_expr(
                c.sql, alias_map, default_tbl, strip_literals=True, dialect=dialect
            )
            col_skeletons.add(skel)

    group_by = frozenset(
        _skeletonize_expr(
            g, alias_map, default_tbl, strip_literals=True, dialect=dialect
        )[0]
        for g in q.group_by
    )

    where_cols: set[str] = set()
    where_skeletons: set[str] = set()
    for clause_sql in (q.where, q.having):
        for conj in _split_conjuncts_sql(clause_sql, dialect=dialect):
            skel, c_set = _skeletonize_expr(
                conj.sql(dialect=dialect),
                alias_map,
                default_tbl,
                strip_literals=True,
                dialect=dialect,
            )
            where_skeletons.add(skel)
            where_cols.update(c_set)

    stmt = (q.statement_type or "SELECT").upper()
    joins_fs = frozenset(join_sigs)
    join_edges_fs = frozenset(join_edges)
    cols_fs = frozenset(col_skeletons)
    w_cols_fs = frozenset(where_cols)
    w_skels_fs = frozenset(where_skeletons)

    template_key = (
        stmt,
        tuple(sorted(tables)),
        tuple(sorted(joins_fs)),
        is_star_only,
        tuple(sorted(cols_fs)),
        tuple(sorted(group_by)),
        tuple(sorted(w_cols_fs)),
        tuple(sorted(w_skels_fs)),
    )
    return _QueryFeatures(
        statement_type=stmt,
        tables=tables,
        joins=joins_fs,
        join_edges=join_edges_fs,
        is_star_only=is_star_only,
        col_skeletons=cols_fs,
        group_by=group_by,
        where_cols=w_cols_fs,
        where_skeletons=w_skels_fs,
        template_key=template_key,
    )


def _jaccard(a: frozenset[Any], b: frozenset[Any]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _features_similarity(a: _QueryFeatures, b: _QueryFeatures) -> float:
    if not a.tables or not b.tables or not (a.tables & b.tables):
        return 0.0
    if a.template_key == b.template_key:
        return 1.0

    # 1. Exact (catalog, db, name) table overlap (weight 0.35)
    s_tables = _jaccard(a.tables, b.tables)

    # 2. Statement type & join graph (weight 0.28)
    s_stmt = 1.0 if a.statement_type == b.statement_type else 0.10
    s_joins = 0.85 * _jaccard(a.join_edges, b.join_edges) + 0.15 * _jaccard(
        a.joins, b.joins
    )
    s_struct = 0.65 * s_stmt + 0.35 * s_joins

    # 3. Projections & GROUP BY (weight 0.25)
    if a.is_star_only and b.is_star_only:
        s_cols = 1.0 if a.col_skeletons == b.col_skeletons else 0.80
    elif a.is_star_only != b.is_star_only:
        s_cols = 0.35
    else:
        s_cols = _jaccard(a.col_skeletons, b.col_skeletons)
        if a.join_edges and a.join_edges == b.join_edges and a.tables == b.tables:
            s_cols = max(s_cols, 0.50)
    s_group = _jaccard(a.group_by, b.group_by)
    s_proj = 0.7 * s_cols + 0.3 * s_group

    # 4. Filters: column-aware + literal-stripped operator skeletons (weight 0.12)
    has_w_a = bool(a.where_skeletons)
    has_w_b = bool(b.where_skeletons)
    if not has_w_a and not has_w_b:
        s_where = 1.0
    elif has_w_a != has_w_b:
        s_where = 0.20
    else:
        s_w_cols = _jaccard(a.where_cols, b.where_cols)
        s_w_skels = _jaccard(a.where_skeletons, b.where_skeletons)
        s_where = 0.30 + 0.50 * s_w_cols + 0.20 * s_w_skels

    return round(
        0.35 * s_tables + 0.28 * s_struct + 0.25 * s_proj + 0.12 * s_where,
        4,
    )


def query_similarity(
    q1: ParsedQuery | str,
    q2: ParsedQuery | str,
    dialect: str | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> float:
    """Compute structural similarity in [0.0, 1.0] between two SQL queries."""
    pq1, pq2 = (
        parse_sql(
            sql=q,
            dialect=dialect,
            default_db=default_db,
            default_schema=default_schema,
        ).queries[0]
        if isinstance(q, str)
        else q
        for q in (q1, q2)
    )
    if pq1.error is not None or pq2.error is not None:
        return 0.0
    f1 = _extract_features(pq1, dialect, default_db, default_schema)
    f2 = _extract_features(pq2, dialect, default_db, default_schema)
    return _features_similarity(f1, f2)


def _load_queries_for_grouping(
    sql: str | None = None,
    file: Path | str | None = None,
    path: Path | str | None = None,
    queries: list[ParsedQuery] | None = None,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> list[ParsedQuery]:
    import json

    if queries is not None:
        out: list[ParsedQuery] = []
        for q in queries:
            if q.complexity_score == 0.0 and q.error is None:
                sc, tr, lb = compute_sql_complexity(q, dialect=dialect)
                q = q.model_copy(
                    update={
                        "complexity_score": sc,
                        "complexity_tier": tr,
                        "complexity_label": lb,
                    }
                )
            out.append(q)
        return out

    if sum(x is not None for x in (sql, file, path)) != 1:
        raise ValueError("Specify exactly one of 'sql', 'file', 'path', or 'queries'")

    if sql is not None:
        return parse_sql(
            sql=sql,
            dialect=dialect,
            schema=schema,
            default_db=default_db,
            default_schema=default_schema,
        ).queries

    if path is not None:
        p_dir = Path(path)
        if p_dir.is_file():
            file = p_dir
        else:
            loaded: list[ParsedQuery] = []
            for sql_path in sorted(p_dir.rglob("*.sql")):
                loaded.extend(
                    parse_sql(
                        file=sql_path,
                        dialect=dialect,
                        schema=schema,
                        default_db=default_db,
                        default_schema=default_schema,
                    ).queries
                )
            return loaded

    if file is None:
        return []
    f_path = Path(file)
    suffix = f_path.suffix.lower()

    def _from_item(item: Any) -> list[ParsedQuery]:
        if isinstance(item, str):
            return parse_sql(
                sql=item,
                dialect=dialect,
                schema=schema,
                default_db=default_db,
                default_schema=default_schema,
            ).queries
        if isinstance(item, dict):
            freq = int(item.get("frequency") or item.get("count") or 1)
            if "tables" in item and "raw_sql" in item:
                pq = ParsedQuery.model_validate(item)
                pq.frequency = freq
                if pq.complexity_score == 0.0 and pq.error is None:
                    sc, tr, lb = compute_sql_complexity(pq, dialect=dialect)
                    pq.complexity_score, pq.complexity_tier, pq.complexity_label = (
                        sc,
                        tr,
                        lb,
                    )
                return [pq]
            raw = item.get("sql") or item.get("raw_sql") or item.get("query")
            if isinstance(raw, str) and raw.strip():
                pqs = parse_sql(
                    sql=raw,
                    dialect=dialect,
                    schema=schema,
                    default_db=default_db,
                    default_schema=default_schema,
                ).queries
                for pq in pqs:
                    pq.frequency = freq
                return pqs
        return []

    if suffix == ".json":
        payload = json.loads(f_path.read_text(encoding="utf-8"))
        items = (
            payload.get("queries", [])
            if isinstance(payload, dict)
            else (payload if isinstance(payload, list) else [])
        )
        return [pq for item in items for pq in _from_item(item)]

    if suffix == ".jsonl":
        out_jsonl: list[ParsedQuery] = []
        for line in f_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                obj = line
            out_jsonl.extend(_from_item(obj))
        return out_jsonl

    return parse_sql(
        file=f_path,
        dialect=dialect,
        schema=schema,
        default_db=default_db,
        default_schema=default_schema,
    ).queries


def _synthesize_group(
    group_id: int,
    member_indices: list[int],
    all_queries: list[ParsedQuery],
    all_features: dict[int, _QueryFeatures],
    rep_idx: int,
    dialect: str | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> SqlQueryGroup:
    rep_feat = all_features[rep_idx]
    sims = [_features_similarity(all_features[i], rep_feat) for i in member_indices]
    min_sim = round(min(sims), 4) if sims else 1.0
    avg_sim = round(sum(sims) / len(sims), 4) if sims else 1.0

    # Pick the most comprehensive member as representative_sql (tie-break by medoid similarity & frequency)
    best_idx = max(
        member_indices,
        key=lambda i: (
            not all_features[i].is_star_only,
            all_queries[i].complexity_score,
            _features_similarity(all_features[i], rep_feat),
            all_queries[i].frequency,
        ),
    )
    rep_q = all_queries[best_idx]

    tables_by_key: dict[tuple[str, str, str], TableRef] = {}
    ctes_by_name: dict[str, CTESpec] = {}
    joins_by_sig: dict[str, JoinSpec] = {}
    cols_by_skel: dict[str, ColumnSpec] = {}
    where_by_skel: dict[str, str] = {}
    having_by_skel: dict[str, str] = {}
    group_by_by_skel: dict[str, str] = {}
    order_by_by_skel: dict[str, str] = {}
    limit_val: str | None = rep_q.limit

    # Order members so best_idx comes first to anchor aliases and canonical SQL expressions
    ordered_indices = [best_idx, *[i for i in member_indices if i != best_idx]]

    for i in ordered_indices:
        for t in all_queries[i].tables:
            if t.name:
                tkey = _tbl_key(t, default_db, default_schema)
                if tkey not in tables_by_key:
                    tables_by_key[tkey] = _apply_default_db_schema(
                        t, default_db, default_schema
                    )
                elif tables_by_key[tkey].alias is None and t.alias is not None:
                    tables_by_key[tkey] = tables_by_key[tkey].model_copy(
                        update={"alias": t.alias}
                    )

    fqn_to_canon_alias = {
        _tbl_fqn(tkey): (tref.alias or tref.name)
        for tkey, tref in tables_by_key.items()
    }

    def _rewrite_canon(sql_str: str, alias_map: dict[str, str]) -> str:
        if "." not in sql_str:
            return sql_str
        node = _parse_expr_safe(sql_str, dialect=dialect)
        if node is None:
            return sql_str
        changed = False
        for col in node.find_all(exp.Column):
            if col.table and col.table.lower() in alias_map:
                canon = fqn_to_canon_alias.get(alias_map[col.table.lower()])
                if canon and canon != col.table:
                    col.set("table", exp.to_identifier(canon))
                    changed = True
        return node.sql(dialect=dialect) if changed else sql_str

    def _add_dedup(
        target: dict[str, str],
        items: list[str],
        alias_map: dict[str, str],
        default_tbl: str,
    ) -> None:
        for s in items:
            skel, _ = _skeletonize_expr(
                s, alias_map, default_tbl, strip_literals=True, dialect=dialect
            )
            target.setdefault(skel, _rewrite_canon(s, alias_map))

    for i in ordered_indices:
        q = all_queries[i]
        alias_map, default_tbl = _build_alias_map(q, default_db, default_schema)

        for cte in q.ctes:
            if cte.name and cte.name.lower() not in ctes_by_name:
                ctes_by_name[cte.name.lower()] = cte

        for j in q.joins:
            edge_sig, _ = _join_sigs(
                j, alias_map, default_tbl, dialect, default_db, default_schema
            )
            if edge_sig not in joins_by_sig:
                joins_by_sig[edge_sig] = j

        for c in q.columns:
            skel, _ = _skeletonize_expr(
                c.sql, alias_map, default_tbl, strip_literals=True, dialect=dialect
            )
            c_norm = c.model_copy(
                update={
                    "sql": _rewrite_canon(c.sql, alias_map),
                    "table": fqn_to_canon_alias.get(
                        alias_map.get(c.table.lower(), ""), c.table
                    )
                    if c.table
                    else None,
                }
            )
            if skel not in cols_by_skel or (
                cols_by_skel[skel].alias is None and c_norm.alias is not None
            ):
                cols_by_skel[skel] = c_norm

        _add_dedup(
            where_by_skel,
            [c.sql(dialect=dialect) for c in _split_conjuncts_sql(q.where, dialect)],
            alias_map,
            default_tbl,
        )
        _add_dedup(
            having_by_skel,
            [c.sql(dialect=dialect) for c in _split_conjuncts_sql(q.having, dialect)],
            alias_map,
            default_tbl,
        )
        _add_dedup(group_by_by_skel, q.group_by, alias_map, default_tbl)
        _add_dedup(order_by_by_skel, q.order_by, alias_map, default_tbl)

        if limit_val is None and q.limit is not None:
            limit_val = q.limit

    total_freq = sum(all_queries[i].frequency for i in member_indices)
    q_complexities = [all_queries[i].complexity_score for i in member_indices]
    max_q_comp = round(max(q_complexities), 2) if q_complexities else 0.0
    avg_q_comp = (
        round(
            sum(
                all_queries[i].complexity_score * all_queries[i].frequency
                for i in member_indices
            )
            / max(1, total_freq),
            2,
        )
        if member_indices
        else 0.0
    )

    grp = SqlQueryGroup(
        group_id=group_id,
        query_count=len(member_indices),
        total_frequency=total_freq,
        max_query_complexity=max_q_comp,
        avg_query_complexity=avg_q_comp,
        min_similarity=min_sim,
        avg_similarity=avg_sim,
        statement_type=rep_q.statement_type,
        representative_sql=rep_q.raw_sql,
        tables=list(tables_by_key.values()),
        ctes=list(ctes_by_name.values()),
        joins=list(joins_by_sig.values()),
        columns=list(cols_by_skel.values()),
        where_conditions=list(where_by_skel.values()),
        having_conditions=list(having_by_skel.values()),
        group_by=list(group_by_by_skel.values()),
        order_by=list(order_by_by_skel.values()),
        limit=limit_val,
        query_indices=sorted(member_indices),
    )
    g_score, _, _ = compute_sql_complexity(grp, dialect=dialect)
    grp.complexity_score, grp.complexity_tier, grp.complexity_label = _tier_for_score(
        max(g_score, max_q_comp)
    )
    return grp


def group_sql_queries(
    sql: str | None = None,
    file: Path | str | None = None,
    path: Path | str | None = None,
    queries: list[ParsedQuery] | None = None,
    threshold: float = 0.7,
    dialect: str | None = None,
    schema: dict[str, Any] | None = None,
    default_db: str | None = None,
    default_schema: str | None = None,
) -> SqlGroupResult:
    """Parse and group SQL queries by structural similarity, summing frequency and scoring complexity."""
    raw_queries = _load_queries_for_grouping(
        sql=sql,
        file=file,
        path=path,
        queries=queries,
        dialect=dialect,
        schema=schema,
        default_db=default_db,
        default_schema=default_schema,
    )
    if not raw_queries:
        return SqlGroupResult(threshold=threshold, dialect=dialect)

    errors: list[ParsedQuery] = []
    valid_indices: list[int] = []
    features_by_idx: dict[int, _QueryFeatures] = {}

    # Step 1: O(N) feature extraction & exact template bucketing
    buckets: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    bucket_features: dict[tuple[Any, ...], _QueryFeatures] = {}

    for idx, q in enumerate(raw_queries):
        if q.error is not None or not q.tables:
            errors.append(q)
            continue
        feat = _extract_features(q, dialect, default_db, default_schema)
        valid_indices.append(idx)
        features_by_idx[idx] = feat
        buckets[feat.template_key].append(idx)
        if feat.template_key not in bucket_features:
            bucket_features[feat.template_key] = feat

    # Order unique template buckets so richer/more frequent queries seed medoids first
    sorted_tkeys = sorted(
        buckets.keys(),
        key=lambda tk: (
            not bucket_features[tk].is_star_only,
            sum(raw_queries[i].frequency for i in buckets[tk]),
            len(bucket_features[tk].joins),
            len(bucket_features[tk].col_skeletons),
            len(bucket_features[tk].where_skeletons),
        ),
        reverse=True,
    )

    # Step 2: Inverted index over existing cluster medoids by exact (catalog, db, name) table
    # ponytail: greedy medoid clustering over unique templates; upgrade to full hierarchical linkage if >10k distinct templates per table
    clusters: list[tuple[tuple[Any, ...], list[tuple[Any, ...]]]] = []
    table_to_clusters: dict[tuple[str, str, str], list[int]] = defaultdict(list)

    for tk in sorted_tkeys:
        feat = bucket_features[tk]
        candidate_cids: set[int] = set()
        for tbl in feat.tables:
            candidate_cids.update(table_to_clusters.get(tbl, ()))

        best_cid: int | None = None
        best_sim = -1.0
        for cid in candidate_cids:
            medoid_tk, member_tks = clusters[cid]
            sim = _features_similarity(feat, bucket_features[medoid_tk])
            # Ensure candidate also stays >= threshold against all existing templates in the cluster
            if (
                sim >= threshold
                and sim > best_sim
                and all(
                    _features_similarity(feat, bucket_features[mtk]) >= threshold
                    for mtk in member_tks
                )
            ):
                best_sim = sim
                best_cid = cid

        if best_cid is not None:
            clusters[best_cid][1].append(tk)
        else:
            new_cid = len(clusters)
            clusters.append((tk, [tk]))
            for tbl in feat.tables:
                table_to_clusters[tbl].append(new_cid)

    # Step 3: Refine each cluster's medoid and synthesize SqlQueryGroup
    synthesized: list[SqlQueryGroup] = []
    for _, member_tks in clusters:
        member_q_indices = [i for tk in member_tks for i in buckets[tk]]
        if len(member_tks) > 1:
            best_medoid_tk = max(
                member_tks,
                key=lambda tk: sum(
                    _features_similarity(bucket_features[tk], bucket_features[otk])
                    * sum(raw_queries[i].frequency for i in buckets[otk])
                    for otk in member_tks
                ),
            )
            rep_idx = buckets[best_medoid_tk][0]
        else:
            rep_idx = member_q_indices[0]

        synthesized.append(
            _synthesize_group(
                group_id=0,
                member_indices=member_q_indices,
                all_queries=raw_queries,
                all_features=features_by_idx,
                rep_idx=rep_idx,
                dialect=dialect,
                default_db=default_db,
                default_schema=default_schema,
            )
        )

    # Sort groups by total_frequency DESC, complexity_score DESC, query_count DESC
    synthesized.sort(
        key=lambda g: (g.total_frequency, g.complexity_score, g.query_count),
        reverse=True,
    )
    for gid, grp in enumerate(synthesized, start=1):
        grp.group_id = gid

    return SqlGroupResult(
        total_queries=len(raw_queries),
        valid_queries=len(valid_indices),
        total_frequency=sum(g.total_frequency for g in synthesized),
        group_count=len(synthesized),
        threshold=threshold,
        dialect=dialect,
        groups=synthesized,
        errors=errors,
    )

