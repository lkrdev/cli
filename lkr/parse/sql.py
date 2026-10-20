from pathlib import Path
from typing import Any

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
    "JoinSpec",
    "ParsedQuery",
    "SqlParseResult",
    "TableRef",
    "parse_sql",
]


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


class SqlParseResult(BaseModel):
    queries: list[ParsedQuery] = Field(default_factory=list)
    dialect: str | None = None


def _main_select(expr: exp.Expr) -> exp.Select | None:
    target = (
        expr.expression
        if isinstance(expr, (exp.Create, exp.Insert)) and expr.expression
        else expr
    )
    while isinstance(target, (exp.Subquery, exp.Paren, exp.SetOperation)):
        target = target.this
    return target if isinstance(target, exp.Select) else None


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

    sel = _main_select(expr)
    columns: list[ColumnSpec] = []
    joins: list[JoinSpec] = []

    if sel is not None:
        proj_sel = (
            _main_select(
                _optimize_stars(expr, dialect, schema, default_db, default_schema)
            )
            or sel
            if any(_get_star(p) is not None for p in sel.selects)
            else sel
        )
        columns = [_col_spec_from_proj(proj, dialect) for proj in proj_sel.selects]

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

    where_expr = expr.args.get("where") or (
        sel.args.get("where") if sel is not None else None
    )
    having_expr = sel.args.get("having") if sel is not None else None
    group_expr = sel.args.get("group") if sel is not None else None
    order_expr = expr.args.get("order") or (
        sel.args.get("order") if sel is not None else None
    )
    limit_expr = expr.args.get("limit") or (
        sel.args.get("limit") if sel is not None else None
    )

    limit_val: str | None = None
    if isinstance(limit_expr, exp.Limit) and limit_expr.expression is not None:
        limit_val = limit_expr.expression.sql(dialect=dialect)
    elif isinstance(limit_expr, exp.Fetch) and limit_expr.this is not None:
        limit_val = limit_expr.this.sql(dialect=dialect)

    return ParsedQuery(
        statement_type=expr.key.upper(),
        raw_sql=raw_sql,
        tables=tables,
        ctes=ctes,
        joins=joins,
        columns=columns,
        where=where_expr.this.sql(dialect=dialect)
        if isinstance(where_expr, exp.Where) and where_expr.this is not None
        else None,
        having=having_expr.this.sql(dialect=dialect)
        if isinstance(having_expr, exp.Having) and having_expr.this is not None
        else None,
        group_by=[e.sql(dialect=dialect) for e in group_expr.expressions]
        if isinstance(group_expr, exp.Group)
        else [],
        order_by=[e.sql(dialect=dialect) for e in order_expr.expressions]
        if isinstance(order_expr, exp.Order)
        else [],
        limit=limit_val,
    )


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
