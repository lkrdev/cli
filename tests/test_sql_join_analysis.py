import json

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


def test_sql_join_extraction_with_ctes_and_types():
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


def test_sql_join_extraction_using_clause():
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


def test_lookml_explore_join_graph_building():
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


def test_join_comparison_exact_and_type_mismatch():
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


def test_precedent_discovery():
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


def test_safety_checks_fan_trap_and_required_joins():
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


def test_cli_sql_lookml_compare_includes_join_analysis():
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


def test_inferred_relationships_and_mismatch_warning():
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

