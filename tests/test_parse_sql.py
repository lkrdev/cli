import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import SqlParseResult, parse_sql, sql_command

runner = CliRunner()


def test_parse_multiple_queries_and_pieces():
    sql = """
    WITH active_users AS (
        SELECT id, country FROM raw.users WHERE active = 1
    )
    SELECT
        u.country AS user_country,
        COUNT(o.id) AS order_count,
        SUM(o.amount) AS total_amount
    FROM active_users AS u
    LEFT JOIN analytics.orders AS o ON u.id = o.user_id
    WHERE o.status = 'completed;paid'
    GROUP BY u.country
    HAVING COUNT(o.id) > 5
    ORDER BY total_amount DESC
    LIMIT 10;

    SELECT id, name FROM public.products LIMIT 5;
    """
    result = parse_sql(sql=sql, dialect="postgres")
    assert isinstance(result, SqlParseResult)
    assert result.dialect == "postgres"
    assert len(result.queries) == 2

    q1 = result.queries[0]
    assert q1.statement_type == "SELECT"
    assert q1.error is None
    assert len(q1.ctes) == 1
    assert q1.ctes[0].name == "active_users"
    assert {(t.db, t.name, t.alias) for t in q1.tables} == {
        ("raw", "users", None),
        ("analytics", "orders", "o"),
    }
    assert len(q1.joins) == 1
    assert q1.joins[0].side == "LEFT"
    assert q1.joins[0].on_sql == "u.id = o.user_id"
    assert [
        (c.alias, c.table, c.column, c.is_agg) for c in q1.columns
    ] == [
        ("user_country", "u", "country", False),
        ("order_count", None, None, True),
        ("total_amount", None, None, True),
    ]
    assert q1.where == "o.status = 'completed;paid'"
    assert q1.group_by == ["u.country"]
    assert q1.having == "COUNT(o.id) > 5"
    assert q1.order_by == ["total_amount DESC"]
    assert q1.limit == "10"

    q2 = result.queries[1]
    assert q2.statement_type == "SELECT"
    assert q2.tables[0].name == "products"
    assert q2.tables[0].db == "public"
    assert q2.limit == "5"


def test_parse_captures_syntax_errors_per_query():
    sql = "SELECT 1 AS a; SELECT FROM WHERE; SELECT 2 AS b;"
    result = parse_sql(sql=sql)
    assert len(result.queries) == 3
    assert result.queries[0].error is None
    assert result.queries[0].columns[0].alias == "a"
    assert result.queries[1].error is not None
    assert result.queries[2].error is None
    assert result.queries[2].columns[0].alias == "b"


def test_cli_parse_sql_stdout_and_file(tmp_path: Path):
    sql_file = tmp_path / "queries.sql"
    out_file = tmp_path / "out.json"
    sql_file.write_text("SELECT a FROM tbl1; SELECT b FROM tbl2;", encoding="utf-8")

    res_stdout = runner.invoke(app, ["parse", "sql", "--sql", "SELECT x FROM t;"])
    assert res_stdout.exit_code == 0
    payload = json.loads(res_stdout.stdout)
    assert len(payload["queries"]) == 1
    assert payload["queries"][0]["tables"][0]["name"] == "t"

    res_file = runner.invoke(
        app, ["parse", "sql", "--file", str(sql_file), "--output", str(out_file)]
    )
    assert res_file.exit_code == 0
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(saved["queries"]) == 2

    direct_model = sql_command(
        sql="SELECT id FROM users", file=None, output=None, dialect=None
    )
    assert isinstance(direct_model, SqlParseResult)
    assert direct_model.queries[0].tables[0].name == "users"
