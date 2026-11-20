import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    LookmlExplore,
    build_explore_join_graph,
    parse_lookml,
    parse_sql,
    parse_sql_to_lookml,
)
from lkr.parse.dag import _build_chain, _collect_declarations

runner = CliRunner()


def test_sql_join_extraction_with_ctes_and_types() -> None:
    sql = """
    WITH active_users AS (
        SELECT id, country FROM raw.users WHERE active = 1
    ),
    filtered_orders AS (
        SELECT id, user_id, amount FROM analytics.orders WHERE status = 'completed'
    )
    SELECT
        u.country,
        o.amount,
        p.name
    FROM active_users AS u
    LEFT JOIN filtered_orders AS o ON u.id = o.user_id AND o.amount > 100
    FULL OUTER JOIN warehouse.products AS p ON o.id = p.order_id
    CROSS JOIN settings AS s;
    """
    res = parse_sql(sql=sql)
    assert len(res.queries) == 1
    q = res.queries[0]
    assert len(q.joins) == 3

    # Join 0: active_users (raw.users) LEFT JOIN filtered_orders (analytics.orders)
    j0 = q.joins[0]
    assert j0.join_type == "LEFT"
    assert j0.side == "LEFT"
    assert j0.left_table is not None
    assert j0.left_table.name == "users"
    assert j0.left_table.db == "raw"
    assert j0.left_table.alias == "u"
    assert j0.right_table is not None
    assert j0.right_table.name == "orders"
    assert j0.right_table.db == "analytics"
    assert j0.right_table.alias == "o"
    assert j0.equi_joins == [(("users", "id"), ("orders", "user_id"))]
    assert len(j0.non_equi_conditions) == 1
    assert "100" in j0.non_equi_conditions[0]

    # Join 1: FULL JOIN warehouse.products
    j1 = q.joins[1]
    assert j1.join_type == "FULL"
    assert j1.right_table is not None
    assert j1.right_table.name == "products"
    assert j1.right_table.db == "warehouse"
    assert j1.equi_joins == [(("orders", "id"), ("products", "order_id"))]

    # Join 2: CROSS JOIN settings
    j2 = q.joins[2]
    assert j2.join_type == "CROSS"
    assert j2.right_table is not None
    assert j2.right_table.name == "settings"
    assert j2.equi_joins == []


def test_sql_join_extraction_using_clause() -> None:
    sql = """
    SELECT *
    FROM orders
    JOIN order_items USING (order_id, item_id);
    """
    res = parse_sql(sql=sql)
    q = res.queries[0]
    assert len(q.joins) == 1
    j = q.joins[0]
    assert j.join_type == "INNER"
    assert j.left_table is not None
    assert j.left_table.name == "orders"
    assert j.right_table is not None
    assert j.right_table.name == "order_items"
    assert j.equi_joins == [
        (("orders", "order_id"), ("order_items", "order_id")),
        (("orders", "item_id"), ("order_items", "item_id")),
    ]


def test_lookml_explore_join_graph_building() -> None:
    lkml = """
    model: sales {
      explore: orders {
        always_join: [users]
        from: base_orders
        view_name: base_orders

        join: users {
          from: dim_users
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }

        join: order_items {
          type: inner
          relationship: one_to_many
          foreign_key: order_id
          required_joins: [users]
        }

        join: shipments {
          type: full_outer
          relationship: one_to_one
          sql_foreign_key: ${orders.shipping_id} ;;
        }
      }
    }

    view: base_orders { sql_table_name: public.orders ;; }
    view: dim_users {
      sql_table_name: public.users ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }
    view: order_items {
      sql_table_name: public.order_items ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }
    view: shipments {
      sql_table_name: public.shipments ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }
    """
    proj = parse_lookml(lookml=lkml).apply_defaults()
    exp_base, exp_ref = _collect_declarations(proj, "explore", LookmlExplore)
    chain = _build_chain("orders", exp_base, exp_ref)
    assert proj.model is not None
    sales_model = proj.model["sales"]
    assert sales_model.explore is not None
    explore_obj = sales_model.explore["orders"]
    assert isinstance(explore_obj, LookmlExplore)
    model_views = sales_model.view or {}
    views_map = {k: v for k, v in model_views.items() if not isinstance(v, list)}
    graph = build_explore_join_graph(
        "orders",
        explore_obj,
        chain,
        views_map,
        model_name="sales",
    )

    assert graph.explore_name == "orders"
    assert graph.model_name == "sales"
    assert graph.base_view == "base_orders"
    assert graph.always_join == ["users"]
    assert len(graph.joins) == 3

    # users join
    u_join = graph.joins["users"]
    assert u_join.name == "users"
    assert u_join.target_view == "dim_users"
    assert u_join.type == "left_outer"
    assert u_join.relationship == "many_to_one"
    assert u_join.always_join is True
    assert u_join.equi_joins == [(("orders", "user_id"), ("users", "id"))]

    # order_items join (foreign_key)
    oi_join = graph.joins["order_items"]
    assert oi_join.name == "order_items"
    assert oi_join.type == "inner"
    assert oi_join.relationship == "one_to_many"
    assert oi_join.required_joins == ["users"]
    assert oi_join.equi_joins == [(("orders", "order_id"), ("order_items", "id"))]

    # shipments join (sql_foreign_key)
    s_join = graph.joins["shipments"]
    assert s_join.name == "shipments"
    assert s_join.type == "full_outer"
    assert s_join.relationship == "one_to_one"
    assert s_join.equi_joins == [(("orders", "shipping_id"), ("shipments", "id"))]


def test_join_comparison_exact_and_type_mismatch() -> None:
    lkml = """
    model: shop {
      explore: orders {
        join: users {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }
      }
    }
    view: orders {
      sql_table_name: public.orders ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: user_id { sql: ${TABLE}.user_id ;; }
    }
    view: users {
      sql_table_name: public.users ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }
    """
    # Exact match: LEFT JOIN in SQL matches left_outer in LookML
    sql_exact = "SELECT o.id, u.id FROM public.orders o LEFT JOIN public.users u ON o.user_id = u.id"
    res_exact = parse_sql_to_lookml(sql=sql_exact, lookml=lkml, sql_schema="public")
    ja_exact = res_exact.queries[0].join_analysis
    assert len(ja_exact) == 1
    assert ja_exact[0].status == "exact_match"
    assert ja_exact[0].matched_explore_join == "users"
    assert ja_exact[0].sql_join_type == "LEFT"
    assert ja_exact[0].explore_join_type == "left_outer"

    # Type mismatch: INNER JOIN in SQL vs left_outer in LookML
    sql_mismatch = "SELECT o.id, u.id FROM public.orders o JOIN public.users u ON o.user_id = u.id"
    res_mismatch = parse_sql_to_lookml(sql=sql_mismatch, lookml=lkml, sql_schema="public")
    ja_mismatch = res_mismatch.queries[0].join_analysis
    assert len(ja_mismatch) == 1
    assert ja_mismatch[0].status == "type_mismatch"
    assert ja_mismatch[0].matched_explore_join == "users"
    assert ja_mismatch[0].sql_join_type == "INNER"
    assert ja_mismatch[0].explore_join_type == "left_outer"


def test_precedent_discovery() -> None:
    lkml = """
    model: shop {
      explore: orders {
        join: users {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }
      }

      explore: inventory {
        join: suppliers {
          type: left_outer
          relationship: many_to_one
          sql_on: ${inventory.supplier_id} = ${suppliers.id} ;;
        }
      }

      explore: catalog {
        join: suppliers {
          type: inner
          relationship: many_to_one
          sql_on: ${catalog.supplier_id} = ${suppliers.id} ;;
        }
      }
    }
    view: orders { sql_table_name: public.orders ;; dimension: id { sql: ${TABLE}.id ;; } }
    view: users { sql_table_name: public.users ;; dimension: id { sql: ${TABLE}.id ;; } }
    view: inventory { sql_table_name: public.inventory ;; dimension: id { sql: ${TABLE}.id ;; } }
    view: catalog { sql_table_name: public.catalog ;; dimension: id { sql: ${TABLE}.id ;; } }
    view: suppliers { sql_table_name: public.suppliers ;; dimension: id { sql: ${TABLE}.id ;; } }
    """
    # Query joins orders with suppliers (not joined on explore 'orders')
    sql = "SELECT o.id, s.id FROM public.orders o LEFT JOIN public.suppliers s ON o.id = s.id"
    res = parse_sql_to_lookml(sql=sql, lookml=lkml, sql_schema="public")
    q = res.queries[0]
    orders_ja = next(ja for ja in q.join_analysis if ja.explore_name == "orders")
    assert orders_ja.status == "missing_join"
    assert orders_ja.matched_explore_join is None
    assert len(orders_ja.precedents) > 0
    prec_names = {f"{p.explore_name}.{p.join_name}" for p in orders_ja.precedents}
    assert "inventory.suppliers" in prec_names or "catalog.suppliers" in prec_names


def test_safety_checks_fan_trap_and_required_joins() -> None:
    lkml = """
    model: ecommerce {
      explore: orders {
        join: order_items {
          type: left_outer
          relationship: one_to_many
          sql_on: ${orders.id} = ${order_items.order_id} ;;
          required_joins: [users]
        }
        join: order_discounts {
          type: left_outer
          relationship: one_to_many
          sql_on: ${orders.id} = ${order_discounts.order_id} ;;
        }
        join: users {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }
      }
    }
    view: orders {
      sql_table_name: public.orders ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: user_id { sql: ${TABLE}.user_id ;; }
    }
    view: users { sql_table_name: public.users ;; dimension: id { primary_key: yes sql: ${TABLE}.id ;; } }
    view: order_items { sql_table_name: public.order_items ;; dimension: order_id { sql: ${TABLE}.order_id ;; } }
    view: order_discounts { sql_table_name: public.order_discounts ;; dimension: order_id { sql: ${TABLE}.order_id ;; } }
    """
    # 1. Query joins order_items without users -> triggers missing_required_join & fan_trap
    sql1 = "SELECT o.id, oi.order_id FROM public.orders o LEFT JOIN public.order_items oi ON o.id = oi.order_id"
    res1 = parse_sql_to_lookml(sql=sql1, lookml=lkml, sql_schema="public")
    ja1 = res1.queries[0].join_analysis[0]
    assert ja1.status == "exact_match"
    warning_rules = {w.rule for w in ja1.safety_warnings}
    assert "fan_trap" in warning_rules
    assert "missing_required_join" in warning_rules

    # Verify warning details
    req_warn = next(w for w in ja1.safety_warnings if w.rule == "missing_required_join")
    assert "users" in req_warn.joins

    fan_warn = next(w for w in ja1.safety_warnings if w.rule == "fan_trap")
    assert set(fan_warn.joins) == {"order_items", "order_discounts"}

    # 2. Query joins both order_items AND users -> missing_required_join is resolved
    sql2 = """
    SELECT o.id, oi.order_id, u.id
    FROM public.orders o
    LEFT JOIN public.order_items oi ON o.id = oi.order_id
    LEFT JOIN public.users u ON o.user_id = u.id
    """
    res2 = parse_sql_to_lookml(sql=sql2, lookml=lkml, sql_schema="public")
    oi_ja = next(ja for ja in res2.queries[0].join_analysis if ja.matched_explore_join == "order_items")
    oi_rules = {w.rule for w in oi_ja.safety_warnings}
    assert "missing_required_join" not in oi_rules


def test_cli_sql_lookml_compare_includes_join_analysis() -> None:
    lkml = """
    model: store {
      explore: orders {
        join: customers {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.cust_id} = ${customers.id} ;;
        }
      }
    }
    view: orders {
      sql_table_name: public.orders ;;
      dimension: id { sql: ${TABLE}.id ;; }
      dimension: cust_id { sql: ${TABLE}.cust_id ;; }
    }
    view: customers {
      sql_table_name: public.customers ;;
      dimension: id { sql: ${TABLE}.id ;; }
    }
    """
    sql = "SELECT o.id, c.id FROM public.orders o LEFT JOIN public.customers c ON o.cust_id = c.id"
    res = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--sql",
            sql,
            "--lookml",
            lkml,
            "--sql-schema",
            "public",
            "--describe",
        ],
    )
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert "_doc" in data
    assert "queries[].join_analysis" in data["_doc"]
    assert len(data["queries"]) == 1
    assert "join_analysis" in data["queries"][0]
    ja = data["queries"][0]["join_analysis"]
    assert len(ja) == 1
    assert ja[0]["status"] == "exact_match"
    assert ja[0]["matched_explore_join"] == "customers"
    assert ja[0]["inferred_relationship"] == "many_to_one"


def test_inferred_relationships_and_mismatch_warning() -> None:
    lkml = """
    model: shop {
      explore: orders {
        join: users {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }
        join: order_facts {
          type: left_outer
          relationship: one_to_one
          sql_on: ${orders.id} = ${order_facts.order_id} ;;
        }
        join: order_items {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.id} = ${order_items.order_id} ;;
        }
      }
    }
    view: orders {
      sql_table_name: public.orders ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: user_id { sql: ${TABLE}.user_id ;; }
      dimension: status { sql: ${TABLE}.status ;; }
    }
    view: users {
      sql_table_name: public.users ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }
    view: order_facts {
      sql_table_name: public.order_facts ;;
      dimension: order_id { primary_key: yes sql: ${TABLE}.order_id ;; }
    }
    view: order_items {
      sql_table_name: public.order_items ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: order_id { sql: ${TABLE}.order_id ;; }
      dimension: status { sql: ${TABLE}.status ;; }
    }
    """
    sql = """
    SELECT o.id, u.id, ofa.order_id, oi.id
    FROM public.orders o
    LEFT JOIN public.users u ON o.user_id = u.id
    LEFT JOIN public.order_facts ofa ON o.id = ofa.order_id
    LEFT JOIN public.order_items oi ON o.id = oi.order_id
    LEFT JOIN public.order_items oi_status ON o.status = oi_status.status
    """
    res = parse_sql_to_lookml(sql=sql, lookml=lkml, sql_schema="public")
    ja = res.queries[0].join_analysis
    assert len(ja) == 4

    # 1. orders.user_id = users.id -> many_to_one
    assert ja[0].inferred_relationship == "many_to_one"
    assert ja[0].relationship == "many_to_one"
    assert "relationship_mismatch" not in {w.rule for w in ja[0].safety_warnings}

    # 2. orders.id = order_facts.order_id -> one_to_one
    assert ja[1].inferred_relationship == "one_to_one"
    assert ja[1].relationship == "one_to_one"

    # 3. orders.id = order_items.order_id -> PK infers one_to_many, LookML declared many_to_one -> mismatch warning
    assert ja[2].inferred_relationship == "one_to_many"
    assert ja[2].relationship == "many_to_one"
    assert "relationship_mismatch" in {w.rule for w in ja[2].safety_warnings}

    # 4. orders.status = order_items.status -> neither is PK -> many_to_many
    assert ja[3].inferred_relationship == "many_to_many"


def test_join_analysis_and_usages_resolve_extended_explore_and_join_sql() -> None:
    lkml = """
    model: shop {
      explore: orders_base {
        extension: required
        from: orders
        sql_always_where: ${orders.status} != 'cancelled' ;;
        sql_always_having: ${orders.count} > 0 ;;
        join: users {
          type: left_outer
          relationship: many_to_one
          sql_on: ${orders.user_id} = ${users.id} ;;
        }
      }
      explore: orders_ext {
        extends: [orders_base]
        sql_always_where: ${EXTENDED} AND ${orders.active} = TRUE ;;
        sql_always_having: (${EXTENDED}) AND ${orders.count} < 500 ;;
        join: users {
          sql_on: (${EXTENDED}) AND ${users.deleted_at} IS NULL ;;
        }
      }
      explore: +orders_ext {
        join: users {
          sql_on: (${EXTENDED}) AND ${users.verified} = TRUE ;;
        }
      }
    }
    view: orders {
      sql_table_name: public.orders ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: user_id { sql: ${TABLE}.user_id ;; }
      dimension: status { sql: ${TABLE}.status ;; }
      dimension: active { type: yesno sql: ${TABLE}.active ;; }
      measure: count { type: count }
    }
    view: users {
      sql_table_name: public.users ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: deleted_at { sql: ${TABLE}.deleted_at ;; }
      dimension: verified { type: yesno sql: ${TABLE}.verified ;; }
    }
    """
    proj = parse_lookml(lookml=lkml).apply_defaults()
    exp_base, exp_ref = _collect_declarations(proj, "explore", LookmlExplore)
    chain = _build_chain("orders_ext", exp_base, exp_ref)
    assert proj.model is not None
    shop_model = proj.model["shop"]
    assert shop_model.explore is not None
    explore_obj = shop_model.explore["orders_ext"]
    assert isinstance(explore_obj, LookmlExplore)
    views_map = {
        k: v for k, v in (shop_model.view or {}).items() if not isinstance(v, list)
    }
    graph = build_explore_join_graph(
        "orders_ext", explore_obj, chain, views_map, model_name="shop"
    )
    u_join = graph.joins["users"]
    assert u_join.equi_joins == [(("orders", "user_id"), ("users", "id"))]
    assert (
        u_join.sql_on is not None
        and u_join.sql_on.strip()
        == "((${orders.user_id} = ${users.id}) AND ${users.deleted_at} IS NULL) AND ${users.verified} = TRUE"
    )
    assert u_join.line == 22

    sql = (
        "SELECT o.id, u.id FROM public.orders o "
        "LEFT JOIN public.users u ON o.user_id = u.id"
    )
    res = parse_sql_to_lookml(sql=sql, lookml=lkml, sql_schema="public")
    q = res.queries[0]
    assert len(q.join_analysis) == 1
    assert q.join_analysis[0].status == "exact_match"
    assert q.join_analysis[0].explore_name == "orders_ext"
    assert q.join_analysis[0].matched_explore_join == "users"

    usages_by_prop = {u.matched_property: u for u in q.usages}
    assert "explore.sql_always_where" in usages_by_prop
    assert (
        usages_by_prop["explore.sql_always_where"].expression
        == "(${orders.status} != 'cancelled') AND ${orders.active} = TRUE"
    )
    assert usages_by_prop["explore.sql_always_where"].line == 16
    assert "explore.sql_always_having" in usages_by_prop
    assert (
        usages_by_prop["explore.sql_always_having"].expression
        == "(${orders.count} > 0) AND ${orders.count} < 500"
    )
    assert usages_by_prop["explore.sql_always_having"].line == 17
    assert "join.sql_on" in usages_by_prop
    assert (
        usages_by_prop["join.sql_on"].expression
        == "((${orders.user_id} = ${users.id}) AND ${users.deleted_at} IS NULL) AND ${users.verified} = TRUE"
    )
    assert usages_by_prop["join.sql_on"].line == 24


def test_sql_lookml_compare_check_gate_and_ojof_exemption(tmp_path: Path) -> None:
    from lkr.parse.sql_to_lookml import check_sql_lookml_compare

    base_dir = tmp_path / "base"
    base_dir.mkdir()
    lkml_dir = tmp_path / "lookml"
    (lkml_dir / "bronze" / "explores").mkdir(parents=True)
    (lkml_dir / "gold" / "explores").mkdir(parents=True)
    (lkml_dir / "tests" / "bronze").mkdir(parents=True)

    (lkml_dir / "m.model.lkml").write_text(
        'connection: "bq"\n'
        'include: "/bronze/**/*.view.lkml"\n'
        'include: "/bronze/explores/**/*.explore.lkml"\n'
        'include: "/gold/**/*.view.lkml"\n'
        'include: "/gold/explores/**/*.explore.lkml"\n'
        'include: "/tests/**/*.test.lkml"\n'
    )
    (lkml_dir / "bronze" / "orders.view.lkml").write_text(
        "view: orders {\n"
        "  sql_table_name: `p.d.orders` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: status { type: string sql: ${TABLE}.status ;; }\n"
        "  dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }\n"
        "  measure: total_revenue { type: sum sql: ${sale_price} ;; }\n"
        "  measure: count { type: count }\n"
        "}\n"
    )
    (lkml_dir / "bronze" / "explores" / "orders.explore.lkml").write_text(
        'include: "/bronze/orders.view.lkml"\n'
        "explore: orders {\n"
        "  view_name: orders\n"
        "  query: status_rev {\n"
        "    dimensions: [orders.status]\n"
        "    measures: [orders.total_revenue]\n"
        '    filters: [orders.status: "-Cancelled"]\n'
        "    sorts: [orders.total_revenue: desc]\n"
        "    limit: 10\n"
        "  }\n"
        "}\n"
    )
    (lkml_dir / "tests" / "bronze" / "orders.test.lkml").write_text(
        'include: "/bronze/explores/orders.explore.lkml"\n'
        "test: orders_smoke {\n"
        "  explore_source: orders { column: count { field: orders.count } }\n"
        "  assert: ok { expression: ${orders.count} >= 0 ;; }\n"
        "}\n"
    )

    sql_file = tmp_path / "input.sql"
    sql_file.write_text(
        "SELECT status, SUM(sale_price) AS rev FROM `p.d.orders` WHERE status != 'Cancelled' GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
    )
    data_file = tmp_path / "data.json"
    valid_iq = {
        "model": "m",
        "view": "orders",
        "fields": ["orders.status", "orders.total_revenue"],
        "filters": {"orders.status": "-Cancelled"},
        "sorts": ["orders.total_revenue desc", "pct_share desc"],
        "limit": "10",
        "dynamic_fields": json.dumps([{"table_calculation": "pct_share", "expression": "${orders.total_revenue} / sum(${orders.total_revenue})"}]),
    }
    data_file.write_text(json.dumps({"queries": [{"query_index": 0, "inline_query": valid_iq}]}))

    # 1. Valid project passes --check (with --data-file + --base-path)
    ok_cli = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--offline",
            "--compact",
            "--check",
            "--sql-file",
            str(sql_file),
            "--path",
            str(lkml_dir),
            "--data-file",
            str(data_file),
            "--base-path",
            str(base_dir),
        ],
    )
    assert ok_cli.exit_code == 0, ok_cli.output

    # 2. Quick Start drift (inline_query patched without updating Quick Start query:) -> exits non-zero
    drifted_data = tmp_path / "drifted.json"
    drifted_data.write_text(
        json.dumps({"queries": [{"query_index": 0, "inline_query": {**valid_iq, "limit": "25"}}]})
    )
    bad_qs = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--offline",
            "--compact",
            "--check",
            "--sql-file",
            str(sql_file),
            "--path",
            str(lkml_dir),
            "--data-file",
            str(drifted_data),
        ],
    )
    assert bad_qs.exit_code == 1

    # 3. Missing tests/bronze/orders.test.lkml on newly added Bronze view -> exits non-zero
    (lkml_dir / "tests" / "bronze" / "orders.test.lkml").unlink()
    bad_bronze = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--offline",
            "--compact",
            "--check",
            "--sql-file",
            str(sql_file),
            "--path",
            str(lkml_dir),
            "--data-file",
            str(data_file),
            "--base-path",
            str(base_dir),
        ],
    )
    assert bad_bronze.exit_code == 1

    # 4. Comma-join multi-fanout (pq.joins == []) fails with fan_trap & 0-measure errors, while 3-table OJOF ON FALSE passes
    fan_lkml = """
    model: m {
      explore: bad_gold {
        view_name: w
        join: d1 { from: date_dim type: left_outer relationship: one_to_many sql_on: ${w.wk} = ${d1.wk} ;; }
        join: d2 { from: date_dim type: left_outer relationship: many_to_many sql_on: ${w.wk} = ${d2.wk} ;; }
        query: q { dimensions: [w.wk, d1.ratio] }
      }
      view: w { sql_table_name: p.d.w ;; dimension: wk { primary_key: yes sql: ${TABLE}.wk ;; } }
      view: date_dim {
        sql_table_name: p.d.date_dim ;;
        dimension: wk { sql: ${TABLE}.wk ;; }
        dimension: ratio { type: number sql: ${TABLE}.sales ;; }
      }
    }
    """
    comma_sql = "SELECT w.wk, SUM(d1.sales) FROM p.d.w w, p.d.date_dim d1 WHERE w.wk = d1.wk GROUP BY 1"
    fan_res = parse_sql_to_lookml(sql=comma_sql, lookml=fan_lkml, offline=True)
    fan_errs = check_sql_lookml_compare(fan_res, lookml=fan_lkml)
    assert any("fan_trap" in e for e in fan_errs)
    assert any("chasm_trap" in e for e in fan_errs)
    assert any("zero LookML measures" in e for e in fan_errs)

    ojof_lkml = """
    model: m {
      explore: multi_fact {
        view_name: spine
        join: orders { type: full_outer relationship: many_to_many sql_on: FALSE ;; }
        join: targets { type: full_outer relationship: many_to_many sql_on: FALSE ;; }
        query: q { dimensions: [orders.country] measures: [orders.total_rev, targets.total_target] }
      }
      view: spine { derived_table: { sql: SELECT 0 AS pk ;; } dimension: pk { primary_key: yes hidden: yes sql: ${TABLE}.pk ;; } }
      view: orders {
        sql_table_name: p.d.orders ;;
        dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
        dimension: country { sql: ${TABLE}.country ;; }
        measure: total_rev { type: sum sql: ${TABLE}.rev ;; }
      }
      view: targets {
        sql_table_name: p.d.targets ;;
        dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
        measure: total_target { type: sum sql: ${TABLE}.target ;; }
      }
    }
    """
    ojof_sql = "SELECT o.country, SUM(o.rev), SUM(t.target) FROM p.d.orders o FULL OUTER JOIN p.d.targets t ON o.country = t.country GROUP BY 1"
    ojof_res = parse_sql_to_lookml(sql=ojof_sql, lookml=ojof_lkml, offline=True)
    assert check_sql_lookml_compare(ojof_res, lookml=ojof_lkml) == []



