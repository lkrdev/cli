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


# ponytail: AST-only star expansion by default; pass schema (seeded from LookML or Looker API) to expand leaf-table stars
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
        for j in sel.args.get("joins") or []:
            on_expr = j.args.get("on")
            joins.append(
                JoinSpec(
                    table=j.this.sql(dialect=dialect) if j.this else "",
                    side=j.side or None,
                    kind=j.kind or None,
                    on_sql=on_expr.sql(dialect=dialect) if on_expr else None,
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
