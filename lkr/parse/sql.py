from pathlib import Path

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ErrorLevel, SqlglotError
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


def _extract_query(
    expr: exp.Expr, raw_sql: str, dialect: str | None = None
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
        for proj in sel.selects:
            inner = proj.this if isinstance(proj, exp.Alias) else proj
            columns.append(
                ColumnSpec(
                    alias=proj.alias or None,
                    sql=proj.sql(dialect=dialect),
                    table=(inner.table or None)
                    if isinstance(inner, exp.Column)
                    else None,
                    column=(inner.name or None)
                    if isinstance(inner, exp.Column)
                    else None,
                    is_agg=bool(inner.find(exp.AggFunc)),
                )
            )
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
                queries.append(_extract_query(expr, raw_chunk, dialect=used_dialect))

    return SqlParseResult(queries=queries, dialect=dialect)
