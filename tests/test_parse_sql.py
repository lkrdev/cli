import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    SqlGroupResult,
    SqlParseResult,
    compute_sql_complexity,
    group_sql_queries,
    parse_sql,
    query_similarity,
    sql_command,
)

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


def test_parse_sql_star_modifiers_and_cte_expansion():
    res_bq = parse_sql(
        sql=(
            "SELECT * EXCEPT (secret, ssn) REPLACE (LOWER(email) AS email) FROM db.s.users; "
            "SELECT u.* EXCEPT (secret) FROM db.s.users u;"
        ),
        dialect="bigquery",
    )
    c1 = res_bq.queries[0].columns[0]
    assert c1.table is None
    assert c1.column is None
    assert c1.except_ == ["secret", "ssn"]
    assert c1.replace == {"email": "LOWER(email)"}

    c2 = res_bq.queries[1].columns[0]
    assert c2.table == "u"
    assert c2.column is None
    assert c2.except_ == ["secret"]

    res_sf = parse_sql(
        sql="SELECT * EXCLUDE (secret) RENAME (email AS user_email) FROM db.s.users",
        dialect="snowflake",
    )
    c3 = res_sf.queries[0].columns[0]
    assert c3.column is None
    assert c3.except_ == ["secret"]
    assert c3.rename == {"email": "user_email"}

    res_cte = parse_sql(
        sql="""
        WITH base AS (
            SELECT id, email, secret_hash, status
            FROM db.s.users
            WHERE status = 'active'
        )
        SELECT * EXCEPT (secret_hash, status)
        FROM base
        """,
        dialect="bigquery",
    )
    assert [(c.table, c.column) for c in res_cte.queries[0].columns] == [
        ("base", "id"),
        ("base", "email"),
    ]


def test_query_similarity_hierarchy_and_table_isolation():
    q_base = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.status = 'paid' GROUP BY o.user_id"
    )
    # 1. Date / literal filter value changes are 1.0 identical
    q_date_2026 = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.dt > 2026 GROUP BY o.user_id"
    )
    q_date_2025 = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.dt > 2025 GROUP BY o.user_id"
    )
    q_date_lit = (
        "SELECT orders.user_id, SUM(orders.amount) AS total "
        "FROM prod.orders WHERE dt > DATE '2024-01-01' GROUP BY orders.user_id"
    )
    assert query_similarity(q_date_2026, q_date_2025) == 1.0
    assert query_similarity(q_date_2026, q_date_lit) == 1.0

    # 2. Same filter column with different operators (= vs IN vs LIKE)
    q_in = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.status IN ('paid', 'settled') GROUP BY o.user_id"
    )
    q_like = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.status LIKE 'paid%' GROUP BY o.user_id"
    )
    # 3. Different filter column in WHERE
    q_diff_where_col = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.region = 'US' GROUP BY o.user_id"
    )
    # 4. UNION query on the same table
    q_union = (
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.status = 'paid' GROUP BY o.user_id "
        "UNION ALL "
        "SELECT o.user_id, SUM(o.amount) AS total "
        "FROM prod.orders o WHERE o.status = 'refunded' GROUP BY o.user_id"
    )
    # 5. Simple SELECT * from the base table
    q_star = "SELECT * FROM prod.orders"

    sim_same_col_in = query_similarity(q_base, q_in)
    sim_same_col_like = query_similarity(q_base, q_like)
    sim_diff_where = query_similarity(q_base, q_diff_where_col)
    sim_union = query_similarity(q_base, q_union)
    sim_star = query_similarity(q_base, q_star)

    assert sim_same_col_in == sim_same_col_like
    assert 1.0 > sim_same_col_in > sim_diff_where > sim_union > sim_star > 0.0

    # 6. Reversed join order & LEFT vs INNER join with same join condition have very high similarity
    q_left_ab = (
        "SELECT a.id, b.total FROM raw.users a "
        "LEFT JOIN analytics.orders b ON a.id = b.user_id"
    )
    q_inner_ba = (
        "SELECT a.id, b.total FROM analytics.orders b "
        "INNER JOIN raw.users a ON b.user_id = a.id"
    )
    q_right_ba = (
        "SELECT a.id, b.total FROM analytics.orders b "
        "RIGHT JOIN raw.users a ON b.user_id = a.id"
    )
    assert query_similarity(q_left_ab, q_right_ba) == 1.0
    assert query_similarity(q_left_ab, q_inner_ba) >= 0.98

    # Even when selecting a.* vs b.* across FROM A LEFT JOIN B vs FROM B INNER JOIN A:
    q_sel_a = "SELECT a.id FROM raw.users a LEFT JOIN analytics.orders b ON a.id = b.user_id"
    q_sel_b = "SELECT b.total FROM analytics.orders b INNER JOIN raw.users a ON b.user_id = a.id"
    assert query_similarity(q_sel_a, q_sel_b) >= 0.85

    # 7. Table name similarity or different schema/dataset must NOT match (similarity == 0.0)
    assert query_similarity("SELECT * FROM orders", "SELECT * FROM order_items") == 0.0
    assert (
        query_similarity("SELECT * FROM staging.orders", "SELECT * FROM prod.orders")
        == 0.0
    )
    assert (
        query_similarity(
            "SELECT * FROM proj_a.prod.orders", "SELECT * FROM proj_b.prod.orders"
        )
        == 0.0
    )


def test_sql_complexity_seven_tiers():
    queries = [
        # Tier 1: trivial
        "SELECT id FROM users",
        # Tier 2: simple
        "SELECT id, email FROM users WHERE status = 'active' AND role = 'admin' ORDER BY id LIMIT 10",
        # Tier 3: low_moderate
        "SELECT country, COUNT(id) AS cnt, SUM(age) AS total_age FROM users WHERE active = 1 GROUP BY country",
        # Tier 4: moderate
        """
        SELECT u.country, COUNT(o.id) AS cnt, SUM(o.amount) AS rev
        FROM users u
        JOIN orders o ON u.id = o.user_id
        WHERE o.status = 'paid' AND u.active = 1
        GROUP BY u.country
        HAVING COUNT(o.id) > 5
        ORDER BY rev DESC
        """,
        # Tier 5: moderate_high
        """
        WITH active_u AS (SELECT id, country FROM users WHERE active = 1)
        SELECT u.country, CASE WHEN o.amount > 100 THEN 'high' ELSE 'low' END AS tier,
               COUNT(o.id) AS cnt, SUM(o.amount) AS rev
        FROM active_u u
        LEFT JOIN orders o ON u.id = o.user_id
        LEFT JOIN payments p ON o.id = p.order_id
        WHERE o.status = 'paid' AND p.verified = 1
        GROUP BY 1, 2
        HAVING SUM(o.amount) > 1000
        """,
        # Tier 6: complex
        """
        WITH active_u AS (SELECT id, country FROM users WHERE active = 1),
             recent_o AS (SELECT id, user_id, amount FROM orders WHERE dt > '2025-01-01')
        SELECT u.country,
               SUM(o.amount) AS rev,
               ROW_NUMBER() OVER (PARTITION BY u.country ORDER BY SUM(o.amount) DESC) AS rnk,
               SUM(SUM(o.amount)) OVER (PARTITION BY u.country) AS country_rev
        FROM active_u u
        LEFT JOIN recent_o o ON u.id = o.user_id AND o.amount > 10
        LEFT JOIN products pr ON o.id = pr.id
        WHERE u.country IN (SELECT code FROM countries WHERE region = 'NA')
        GROUP BY u.country
        HAVING SUM(o.amount) > 500
        """,
        # Tier 7: very_complex
        """
        WITH cte1 AS (SELECT id, country FROM users WHERE active = 1),
             cte2 AS (SELECT id, user_id, amount, product_id FROM orders WHERE dt > '2025-01-01'),
             cte3 AS (SELECT id, category FROM products WHERE enabled = 1),
             cte4 AS (SELECT order_id, fee FROM payments WHERE status = 'ok')
        SELECT u.country, pr.category,
               CASE WHEN SUM(o.amount) > 1000 THEN 'vip' ELSE 'std' END AS seg,
               CASE WHEN COUNT(o.id) > 10 THEN 1 ELSE 0 END AS freq_flag,
               SUM(o.amount) AS rev,
               AVG(pm.fee) AS avg_fee,
               ROW_NUMBER() OVER (PARTITION BY u.country ORDER BY SUM(o.amount) DESC) AS r1,
               RANK() OVER (PARTITION BY pr.category ORDER BY COUNT(o.id) DESC) AS r2,
               LAG(SUM(o.amount)) OVER (PARTITION BY u.country ORDER BY pr.category) AS prev_rev
        FROM cte1 u
        LEFT JOIN cte2 o ON u.id = o.user_id AND o.amount > 0
        FULL OUTER JOIN cte3 pr ON o.product_id = pr.id AND pr.category != 'none'
        LEFT JOIN cte4 pm ON o.id = pm.order_id
        WHERE u.id IN (SELECT user_id FROM vip_list)
          AND o.id NOT IN (SELECT order_id FROM fraud_orders)
        GROUP BY u.country, pr.category
        HAVING SUM(o.amount) > 100 AND COUNT(o.id) > 1
        ORDER BY rev DESC
        LIMIT 100
        """,
    ]
    parsed = [parse_sql(sql=q).queries[0] for q in queries]
    tiers = [q.complexity_tier for q in parsed]
    scores = [q.complexity_score for q in parsed]
    assert tiers == [1, 2, 3, 4, 5, 6, 7]
    assert scores == sorted(scores)
    assert all(0.0 < s <= 100.0 for s in scores)
    assert compute_sql_complexity(parsed[0])[2] == "trivial"
    assert compute_sql_complexity(parsed[-1])[2] == "very_complex"


def test_group_sql_queries_synthesis_and_frequency_sorting(tmp_path: Path):
    # 1000+ queries across 3 table families + 1 syntax error
    sql_statements: list[str] = []
    # Family 1: analytics.orders + raw.users (700 queries with varying literals, operators, and projections)
    for i in range(600):
        sql_statements.append(
            f"SELECT u.country, COUNT(o.id) AS order_cnt "
            f"FROM raw.users u LEFT JOIN analytics.orders o ON u.id = o.user_id "
            f"WHERE o.dt > '{2020 + (i % 6)}-01-01' AND o.status = 's_{i % 5}' "
            f"GROUP BY u.country"
        )
    for i in range(100):
        sql_statements.append(
            f"SELECT u.country, COUNT(o.id) AS order_cnt, SUM(o.amount) AS total_amt "
            f"FROM raw.users u LEFT JOIN analytics.orders o ON u.id = o.user_id "
            f"WHERE o.dt > 2025 AND o.status IN ('paid', 'done_{i}') "
            f"GROUP BY u.country"
        )
    # Family 2: billing.invoices (300 queries)
    for i in range(300):
        sql_statements.append(
            f"SELECT account_id, SUM(total) AS billed "
            f"FROM billing.invoices WHERE invoice_date >= '2025-01-{(i % 28) + 1:02d}' "
            f"GROUP BY account_id"
        )
    # Family 3: staging.orders (50 queries - must NOT group with analytics.orders!)
    for i in range(50):
        sql_statements.append(
            f"SELECT user_id, COUNT(id) FROM staging.orders WHERE dt > {2020 + i} GROUP BY user_id"
        )
    sql_statements.append("SELECT FROM WHERE")

    res = group_sql_queries(sql=";\n".join(sql_statements), threshold=0.7)
    assert isinstance(res, SqlGroupResult)
    assert res.total_queries == 1051
    assert res.valid_queries == 1050
    assert res.total_frequency == 1050
    assert len(res.errors) == 1
    assert res.group_count == 3

    # Sorted by total_frequency descending: 700, 300, 50
    assert [g.total_frequency for g in res.groups] == [700, 300, 50]
    assert [g.query_count for g in res.groups] == [700, 300, 50]

    g1 = res.groups[0]
    assert {(t.db, t.name) for t in g1.tables} == {
        ("raw", "users"),
        ("analytics", "orders"),
    }
    assert len(g1.joins) == 1
    # Synthesized group incorporates SUM(o.amount) from the 100-query subset as well as COUNT(o.id) and u.country!
    col_aliases_or_names = {c.alias or c.column for c in g1.columns}
    assert {"country", "order_cnt", "total_amt"} <= col_aliases_or_names
    # 700 date/status filters deduplicate down to distinct operator skeletons (dt > ?, status = ?, status IN (?))
    assert len(g1.where_conditions) == 3
    assert g1.complexity_score > 0
    assert 1 <= g1.complexity_tier <= 7

    # Test JSONL with explicit frequency / count and CLI invocation
    jsonl_file = tmp_path / "log.jsonl"
    out_file = tmp_path / "groups.json"
    jsonl_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "sql": "SELECT id FROM public.items WHERE price > 10",
                        "frequency": 250,
                    }
                ),
                json.dumps(
                    {
                        "sql": "SELECT id FROM public.items WHERE price > 50",
                        "count": 150,
                    }
                ),
                json.dumps(
                    {"sql": "SELECT id FROM archive.items WHERE price > 10", "count": 5}
                ),
            ]
        ),
        encoding="utf-8",
    )
    cli_res = runner.invoke(
        app,
        [
            "parse",
            "sql-group",
            "--file",
            str(jsonl_file),
            "--threshold",
            "0.75",
            "--output",
            str(out_file),
        ],
    )
    assert cli_res.exit_code == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["total_queries"] == 3
    assert payload["total_frequency"] == 405
    assert payload["group_count"] == 2
    assert payload["groups"][0]["total_frequency"] == 400
    assert payload["groups"][0]["query_count"] == 2
    assert payload["groups"][1]["total_frequency"] == 5

    # Test --path directory of .sql files
    sql_dir = tmp_path / "sql_dir"
    sql_dir.mkdir()
    (sql_dir / "q1.sql").write_text(
        "SELECT id, name FROM app.users WHERE active = 1;", encoding="utf-8"
    )
    (sql_dir / "q2.sql").write_text(
        "SELECT id, name, email FROM app.users WHERE active = 0;", encoding="utf-8"
    )
    dir_res = runner.invoke(
        app, ["parse", "sql-group", "--path", str(sql_dir), "--threshold", "0.7"]
    )
    assert dir_res.exit_code == 0
    dir_payload = json.loads(dir_res.stdout)
    assert dir_payload["group_count"] == 1
    assert dir_payload["groups"][0]["total_frequency"] == 2
    assert {c["column"] for c in dir_payload["groups"][0]["columns"]} == {
        "id",
        "name",
        "email",
    }



