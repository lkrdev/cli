import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    LookmlExplore,
    LookmlExploreSource,
    LookmlFile,
    LookmlProject,
    LookmlTest,
    LookmlView,
    lookml_command,
    parse_lookml,
)

runner = CliRunner()


def test_parse_lookml_inline_extensions_refinements_and_positions():
    lkml = """
    view: base_orders {
      extension: required
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension_group: created {
        type: time
        timeframes: [raw, date, month]
        sql: ${TABLE}.created_at ;;
      }
    }
    view: orders {
      extends: [base_orders]
      sql_table_name: public.orders ;;
      dimension: sale_price {}
      measure: count {
        type: count
      }
    }
    view: +orders {
      label: "Refined Orders"
    }
    explore: orders {
      label: "Orders Explore"
    }
    test: order_id_unique {
      explore_source: orders {
        column: id { field: orders.id }
        column: count { field: orders.count }
      }
      assert: unique_id {
        expression: ${orders.count} <= 1 ;;
      }
    }
    """
    project = parse_lookml(lookml=lkml)
    assert isinstance(project, LookmlProject)
    assert project.model is not None
    inline_model = project.model["inline"]
    assert inline_model.view is not None
    orders_view = inline_model.view["orders"]
    assert isinstance(orders_view, LookmlView)
    assert orders_view.label == "Refined Orders"
    assert orders_view.dimension is not None
    assert orders_view.dimension["id"].primary_key is True
    # Raw parse_lookml preserves un-defaulted sql/type
    assert orders_view.dimension["sale_price"].sql is None
    assert orders_view.dimension["sale_price"].type is None
    # with_defaults() returns an ephemeral copy without mutating the original
    defaulted_view = orders_view.with_defaults()
    assert defaulted_view.dimension is not None
    assert defaulted_view.dimension["sale_price"].sql == "${TABLE}.sale_price"
    assert defaulted_view.dimension["sale_price"].type == "string"
    assert orders_view.dimension["sale_price"].sql is None
    # apply_defaults() mutates in place
    project.apply_defaults()
    assert orders_view.dimension["sale_price"].sql == "${TABLE}.sale_price"
    assert orders_view.dimension["sale_price"].type == "string"
    assert orders_view.dimension_group is not None
    assert orders_view.dimension_group["created"].type == "time"
    assert orders_view.measure is not None
    assert orders_view.measure["count"].type == "count"
    assert orders_view.measure["count"].sql is None

    assert inline_model.explore is not None
    orders_explore = inline_model.explore["orders"]
    assert isinstance(orders_explore, LookmlExplore)
    assert orders_explore.label == "Orders Explore"

    assert inline_model.test is not None
    t_obj = inline_model.test["order_id_unique"]
    assert isinstance(t_obj, LookmlTest)
    assert isinstance(t_obj.explore_source, dict)
    assert isinstance(t_obj.explore_source["orders"], LookmlExploreSource)
    assert t_obj.explore_source["orders"].column is not None
    assert t_obj.explore_source["orders"].column["id"].field == "orders.id"
    assert isinstance(t_obj.assert_, dict)
    assert t_obj.assert_["unique_id"].expression == " ${orders.count} <= 1 "

    assert project.positions is not None
    assert "inline.model" in project.positions.file
    pos_view = project.positions.file["inline.model"]["view"]["orders"]
    assert "$p" in pos_view
    assert len(pos_view["$p"]) == 4
    assert "inline" in project.positions.model
    assert project.positions.model["inline"]["view"]["orders"]["$p"] == [
        0,
        *pos_view["$p"],
    ]


def test_parse_lookml_extensions_refinements_sequencing():
    lkml = """
    view: my_view {}
    explore: has_label_a { extension: required label: "A" }
    explore: has_label_b { extension: required label: "B" }
    explore: has_label_a_plus { extension: required label: "A" }
    explore: +has_label_a_plus { label: "A+" }

    explore: a_before_b { from: my_view extends: [has_label_a, has_label_b] }
    explore: b_before_a { from: my_view extends: [has_label_b, has_label_a] }
    explore: b_before_a_plus { from: my_view extends: [has_label_b, has_label_a_plus] }
    explore: a_plus_before_b_plus_d { from: my_view extends: [has_label_a, has_label_b] }
    explore: +a_plus_before_b_plus_d { label: "D+" }
    """
    project = parse_lookml(lookml=lkml)
    assert project.model is not None
    explores = project.model["inline"].explore
    assert explores is not None
    # Abstract explores (extension: required) are removed by removeAbstract
    assert "has_label_a" not in explores
    assert "has_label_b" not in explores
    assert isinstance(explores["a_before_b"], LookmlExplore)
    assert explores["a_before_b"].label == "B"
    assert isinstance(explores["b_before_a"], LookmlExplore)
    assert explores["b_before_a"].label == "A"
    assert isinstance(explores["b_before_a_plus"], LookmlExplore)
    assert explores["b_before_a_plus"].label == "A+"
    assert isinstance(explores["a_plus_before_b_plus_d"], LookmlExplore)
    assert explores["a_plus_before_b_plus_d"].label == "D+"


def test_parse_lookml_path_and_file_cli(tmp_path: Path):
    base_view = tmp_path / "base.view.lkml"
    base_view.write_text(
        "view: base { extension: required dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; } }",
        encoding="utf-8",
    )
    users_view = tmp_path / "users.view.lkml"
    users_view.write_text(
        'include: "base.view.lkml"\n'
        "view: users { extends: [base] dimension: email { type: string sql: ${TABLE}.email ;; } }\n"
        'view: +users { label: "Users Refined" }',
        encoding="utf-8",
    )
    model_file = tmp_path / "shop.model.lkml"
    model_file.write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\nexplore: users { join: orders { type: left_outer relationship: one_to_many sql_on: ${users.id} = ${orders.user_id} ;; } }',
        encoding="utf-8",
    )
    out_file = tmp_path / "assembled.json"

    res_path = runner.invoke(
        app, ["parse", "lookml", "--path", str(tmp_path), "--output", str(out_file)]
    )
    assert res_path.exit_code == 0
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["model"]["shop"]["connection"] == "bq"
    assert saved["model"]["shop"]["view"]["users"]["label"] == "Users Refined"
    assert "id" in saved["model"]["shop"]["view"]["users"]["dimension"]
    assert (
        saved["model"]["shop"]["explore"]["users"]["join"]["orders"]["type"]
        == "left_outer"
    )
    assert "$strings" in saved["file"]["view"]["users"]
    assert "shop" in saved["positions"]["model"]

    direct = lookml_command(path=None, file=users_view, lookml=None, output=None)
    assert isinstance(direct, LookmlProject)
    assert direct.model is not None
    assert direct.model["inline"].view is not None
    assert "users" in direct.model["inline"].view


def test_parse_sql_to_lookml_table_variants_and_locations(tmp_path: Path):
    from lkr.parse import SqlToLookmlResult, parse_sql_to_lookml

    order_items_file = tmp_path / "order_items.view.lkml"
    order_items_file.write_text(
        "view: order_items {\n"
        "  sql_table_name: order_items ;;\n"
        "  dimension: status {\n"
        "    sql: ${TABLE}.status ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    sql = (
        "SELECT status from order_items; "
        "SELECT status from ecomm.order_items; "
        "SELECT status from `looker-private-demo.ecomm.order_items`;"
    )
    res = parse_sql_to_lookml(
        sql=sql,
        lookml_file=order_items_file,
        sql_db="looker-private-demo",
        sql_schema="ecomm",
        lkml_db="looker-private-demo",
        lkml_schema="ecomm",
    )
    assert isinstance(res, SqlToLookmlResult)
    assert len(res.queries) == 3

    for q in res.queries:
        assert len(q.views) == 1
        vm = q.views[0]
        assert vm.view_name == "order_items"
        assert vm.file == "order_items.view.lkml"
        assert vm.line == 1
        assert vm.end_line == 6
        assert vm.position[0] == 0
        assert vm.sql_table_name_location is not None
        assert vm.sql_table_name_location.line == 2
        assert vm.sql_table_name_location.position[0] == 1

        assert len(vm.fields) == 1
        fm = vm.fields[0]
        assert fm.sql_column == "status"
        assert fm.field_type == "dimension"
        assert fm.field_name == "status"
        assert fm.file == "order_items.view.lkml"
        assert fm.line == 3
        assert fm.end_line == 5
        assert fm.position[0] == 2
        assert fm.sql_location is not None
        assert fm.sql_location.line == 4
        assert fm.sql_location.position[0] == 3

    cli_res = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--sql",
            sql,
            "--lookml-file",
            str(order_items_file),
            "--sql-db",
            "looker-private-demo",
            "--sql-schema",
            "ecomm",
            "--lkml-db",
            "looker-private-demo",
            "--lkml-schema",
            "ecomm",
        ],
    )
    assert cli_res.exit_code == 0
    payload = json.loads(cli_res.stdout)
    assert len(payload["queries"]) == 3
    assert payload["queries"][2]["views"][0]["fields"][0]["line"] == 3


def test_parse_sql_to_lookml_explores_aliases_and_field_sets():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: order_items {
      sql_table_name: ecomm.order_items ;;
      set: summary_fields {
        fields: [status]
      }
      dimension: id {
        sql: ${TABLE}.id ;;
      }
      dimension: status {
        sql: ${TABLE}.status ;;
      }
    }

    view: order_items_cohorts {
      extends: [order_items]
    }

    view: unused_order_items {
      extends: [order_items]
    }

    explore: order_items {}

    explore: kitten_order_items {
      extends: [order_items]
    }

    explore: journey_mapping {
      view_name: order_items
      join: next_order_items {
        from: order_items
        fields: [summary_fields*]
      }
    }

    explore: cohorts {
      view_name: users
      join: order_items {
        from: order_items_cohorts
        fields: [order_items.id]
      }
    }
    """
    res = parse_sql_to_lookml(
        sql="SELECT status FROM order_items", lookml=lkml, sql_schema="ecomm"
    )
    q = res.queries[0]
    views_by_name = {v.view_name: v for v in q.views}
    assert set(views_by_name) == {
        "order_items",
        "order_items_cohorts",
        "unused_order_items",
    }

    # Unreachable or field-excluded views still appear in views with empty explores
    assert views_by_name["order_items_cohorts"].fields[0].explores == []
    assert views_by_name["unused_order_items"].fields[0].explores == []

    # Reachable explore fields with proper aliasing
    exp_fields = {(e.explore_name, e.field, e.join_name) for e in q.explores}
    assert exp_fields == {
        ("order_items", "order_items.status", None),
        ("kitten_order_items", "kitten_order_items.status", None),
        ("journey_mapping", "order_items.status", None),
        ("journey_mapping", "next_order_items.status", "next_order_items"),
    }


def test_parse_sql_to_lookml_transitive_refs_and_default_sql():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: order_items {
      sql_table_name: ecomm.order_items ;;
      dimension: sale_price {
        type: number
      }
      measure: total_sale_price {
        type: sum
        sql: ${sale_price} ;;
      }
    }

    view: inventory_items {
      sql_table_name: ecomm.inventory_items ;;
      dimension: cost {
        type: number
      }
      dimension: gross_margin {
        type: number
        sql: ${order_items.sale_price} - ${cost} ;;
      }
      measure: total_gross_margin {
        type: sum
        sql: ${gross_margin} ;;
      }
    }

    explore: order_items {
      join: inventory_items {
        sql_on: ${order_items.id} = ${inventory_items.id} ;;
      }
    }

    explore: inventory_only {
      view_name: inventory_items
    }
    """
    res = parse_sql_to_lookml(
        sql="SELECT sale_price FROM order_items", lookml=lkml, sql_schema="ecomm"
    )
    q = res.queries[0]
    views_by_name = {v.view_name: v for v in q.views}
    assert set(views_by_name) == {"order_items", "inventory_items"}

    oi_fields = {f.field_name: f for f in views_by_name["order_items"].fields}
    assert set(oi_fields) == {"sale_price", "total_sale_price"}
    assert oi_fields["sale_price"].sql == "${TABLE}.sale_price"
    assert oi_fields["sale_price"].via == []
    assert oi_fields["total_sale_price"].via == ["order_items.sale_price"]

    # inventory_items.gross_margin and total_gross_margin match, but NOT inventory_items.cost
    ii_fields = {f.field_name: f for f in views_by_name["inventory_items"].fields}
    assert set(ii_fields) == {"gross_margin", "total_gross_margin"}
    assert "cost" not in ii_fields
    assert ii_fields["gross_margin"].via == ["order_items.sale_price"]
    assert ii_fields["total_gross_margin"].via == [
        "order_items.sale_price",
        "inventory_items.gross_margin",
    ]

    # Cross-view ref requires order_items in the explore, so inventory_only is excluded
    ii_explores = {e.explore_name for e in ii_fields["gross_margin"].explores}
    assert ii_explores == {"order_items"}


def test_parse_sql_to_lookml_tests_dag_association():
    from lkr.parse import LookmlTestMatch, parse_sql_to_lookml

    lkml = """
    view: order_items {
      sql_table_name: ecomm.order_items ;;
      dimension: id { primary_key: yes }
      dimension: sale_price { type: number }
      dimension_group: created {
        type: time
        timeframes: [date, week, month]
        sql: ${TABLE}.created_at ;;
      }
      measure: count { type: count }
      measure: total_sale_price {
        type: sum
        sql: ${sale_price} ;;
      }
    }

    view: inventory_items {
      sql_table_name: ecomm.inventory_items ;;
      dimension: id { primary_key: yes }
      dimension: cost { type: number }
      dimension: gross_margin {
        type: number
        sql: ${order_items.sale_price} - ${cost} ;;
      }
      measure: total_gross_margin {
        type: sum
        sql: ${gross_margin} ;;
      }
    }

    explore: order_items {
      join: inventory_items {
        sql_on: ${order_items.id} = ${inventory_items.id} ;;
      }
    }

    test: test_order_pk {
      explore_source: order_items {
        column: id { field: order_items.id }
        column: count {}
        filters: [order_items.created_date: "last 7 days"]
      }
      assert: pk_unique {
        expression: ${count} <= 1 ;;
      }
    }

    test: test_revenue_pos {
      explore_source: order_items {
        column: total_sale_price {}
      }
      assert: rev_pos {
        expression: ${order_items.total_sale_price} >= 0 ;;
      }
    }

    test: test_margin_pos {
      explore_source: order_items {
        column: total_gross_margin { field: inventory_items.total_gross_margin }
      }
      assert: margin_pos {
        expression: ${total_gross_margin} >= 0 ;;
      }
    }

    test: test_unrelated_inventory {
      explore_source: order_items {
        column: cost { field: inventory_items.cost }
      }
      assert: cost_pos {
        expression: ${cost} >= 0 ;;
      }
    }
    """

    # 1. Changing sale_price affects DAG fields: total_sale_price, gross_margin, total_gross_margin
    res1 = parse_sql_to_lookml(
        sql="SELECT sale_price FROM order_items", lookml=lkml, sql_schema="ecomm"
    )
    q1 = res1.queries[0]
    test_names1 = [t.test_name for t in q1.tests]
    assert test_names1 == ["test_revenue_pos", "test_margin_pos"]
    assert all(isinstance(t, LookmlTestMatch) for t in q1.tests)

    # test_revenue_pos checks total_sale_price
    t_rev = q1.tests[0]
    assert t_rev.test_name == "test_revenue_pos"
    assert t_rev.explore_name == "order_items"
    assert t_rev.field == "order_items.total_sale_price"
    assert t_rev.fields == ["order_items.total_sale_price"]
    assert t_rev.line > 0

    # test_margin_pos checks downstream total_gross_margin in inventory_items
    t_margin = q1.tests[1]
    assert t_margin.test_name == "test_margin_pos"
    assert t_margin.explore_name == "order_items"
    assert t_margin.field == "inventory_items.total_gross_margin"
    assert t_margin.fields == ["inventory_items.total_gross_margin"]

    # Field-level tests on order_items view
    oi_views = next(v for v in q1.views if v.view_name == "order_items")
    oi_fields = {f.field_name: f for f in oi_views.fields}
    assert [t.test_name for t in oi_fields["total_sale_price"].tests] == [
        "test_revenue_pos"
    ]
    assert oi_fields["sale_price"].tests == []

    # Field-level tests on inventory_items view
    ii_views = next(v for v in q1.views if v.view_name == "inventory_items")
    ii_fields = {f.field_name: f for f in ii_views.fields}
    assert [t.test_name for t in ii_fields["total_gross_margin"].tests] == [
        "test_margin_pos"
    ]

    # 2. Changing id and created_at affects id and created_date in test_order_pk
    res2 = parse_sql_to_lookml(
        sql="SELECT id, created_at FROM order_items", lookml=lkml, sql_schema="ecomm"
    )
    q2 = res2.queries[0]
    assert [t.test_name for t in q2.tests] == ["test_order_pk"]
    t_pk = q2.tests[0]
    assert t_pk.test_name == "test_order_pk"
    assert set(t_pk.fields) == {"order_items.id", "order_items.created_date"}

    # Field-level tests for res2
    oi_fields2 = {f.field_name: f for f in q2.views[0].fields}
    assert [t.test_name for t in oi_fields2["id"].tests] == ["test_order_pk"]
    assert [t.test_name for t in oi_fields2["created"].tests] == ["test_order_pk"]


def test_parse_sql_to_lookml_describe_doc():
    from typer.testing import CliRunner

    from lkr.parse import SQL_TO_LOOKML_DOC, group, parse_sql_to_lookml

    lkml = "view: users { sql_table_name: users ;; dimension: id {} } explore: users {}"

    # 1. Python API with describe=False / True
    res_normal = parse_sql_to_lookml(
        sql="SELECT id FROM users",
        lookml=lkml,
        describe=False,
        sql_schema="public",
        lkml_schema="public",
    )
    assert res_normal.doc is None
    payload_normal = json.loads(
        res_normal.model_dump_json(by_alias=True, exclude_none=True)
    )
    assert "_doc" not in payload_normal

    res_desc = parse_sql_to_lookml(
        sql="SELECT id FROM users",
        lookml=lkml,
        describe=True,
        sql_schema="public",
        lkml_schema="public",
    )
    assert res_desc.doc == SQL_TO_LOOKML_DOC
    payload_desc = json.loads(
        res_desc.model_dump_json(by_alias=True, exclude_none=True)
    )
    assert "_doc" in payload_desc
    assert "queries[].views[].fields[].via" in payload_desc["_doc"]
    assert "queries[].tests" in payload_desc["_doc"]

    # 2. CLI with --describe
    runner = CliRunner()
    cli_desc = runner.invoke(
        group,
        [
            "sql-lookml-compare",
            "--sql",
            "SELECT id FROM users",
            "--lookml",
            lkml,
            "--describe",
            "--sql-schema",
            "public",
            "--lkml-schema",
            "public",
        ],
    )
    assert cli_desc.exit_code == 0
    cli_payload = json.loads(cli_desc.stdout)
    assert "_doc" in cli_payload
    assert cli_payload["_doc"] == SQL_TO_LOOKML_DOC


def test_parse_lookml_to_api_inline_and_cli(tmp_path: Path):
    from lkr.parse import (
        lookml_to_all_lookml_models,
        lookml_to_lookml_model_explore,
        parse_lookml_to_api,
    )

    (tmp_path / "manifest.lkml").write_text(
        'project_name: "demo_proj"\n', encoding="utf-8"
    )
    (tmp_path / "users.view.lkml").write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "  }\n"
        "  dimension: age_tier {\n"
        "    type: tier\n"
        "    tiers: [18, 65]\n"
        "    style: integer\n"
        "    sql: ${TABLE}.age ;;\n"
        "  }\n"
        "  dimension: is_active {\n"
        "    type: yesno\n"
        "    sql: ${TABLE}.active ;;\n"
        "  }\n"
        "  dimension: coords {\n"
        "    type: location\n"
        "    sql_latitude: ${TABLE}.lat ;;\n"
        "    sql_longitude: ${TABLE}.lon ;;\n"
        "  }\n"
        "  measure: count {\n"
        "    type: count\n"
        "  }\n"
        "  measure: total_spend {\n"
        "    type: sum\n"
        "    sql: ${TABLE}.spend ;;\n"
        "    value_format_name: usd\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "orders.view.lkml").write_text(
        "view: orders {\n"
        "  sql_table_name: public.orders ;;\n"
        "  set: summary {\n"
        "    fields: [id, count]\n"
        "  }\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "  }\n"
        "  dimension: user_id {\n"
        "    type: number\n"
        "  }\n"
        "  dimension_group: created {\n"
        "    type: time\n"
        "    timeframes: [raw, date, day_of_week]\n"
        "    sql: ${TABLE}.created_at ;;\n"
        "  }\n"
        "  measure: count {\n"
        "    type: count\n"
        "    alias: [order_count]\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "shop.model.lkml").write_text(
        'connection: "snowflake"\n'
        'label: "Shop Model"\n'
        'include: "*.view.lkml"\n'
        "explore: orders {\n"
        '  description: "Orders explore"\n'
        "  join: buyers {\n"
        "    from: users\n"
        "    type: left_outer\n"
        "    relationship: many_to_one\n"
        "    sql_on: ${orders.user_id} = ${buyers.id} ;;\n"
        "  }\n"
        "  query: by_date {\n"
        "    dimensions: [created_date]\n"
        "    measures: [count]\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    models = lookml_to_all_lookml_models(path=tmp_path)
    assert len(models) == 1
    assert models[0].name == "shop"
    assert models[0].label == "Shop Model"
    assert models[0].project_name == "demo_proj"
    assert models[0].allowed_db_connection_names == ["snowflake"]
    assert len(models[0].explores) == 1
    assert models[0].explores[0].name == "orders"

    exp = lookml_to_lookml_model_explore("shop", "orders", path=tmp_path)
    assert exp.id == "shop::orders"
    assert exp.sql_table_name == "public.orders  AS orders"
    assert exp.aliases[0].name == "order_count"
    assert exp.aliases[0].value == "orders.count"
    assert len(exp.turtle_looks) == 1
    assert exp.turtle_looks[0].name == "turtle::by_date"
    assert exp.turtle_looks[0].can_turtle is True

    dims_by_name = {d.name: d for d in exp.fields.dimensions}
    assert dims_by_name["orders.user_id"].sql == "orders.user_id"
    assert dims_by_name["buyers.is_active"].label_short == "Is Active (Yes / No)"
    assert dims_by_name["buyers.age_tier"].sql_case is not None
    assert (
        dims_by_name["buyers.coords"].sql
        == "Latitude:\n${TABLE}.lat \n\nLongitude:\n${TABLE}.lon "
    )

    meas_by_name = {m.name: m for m in exp.fields.measures}
    # Base view count has type="count" and sql=None; joined many_to_one view rewrites to symmetric aggregates
    assert meas_by_name["orders.count"].type == "count"
    assert meas_by_name["orders.count"].sql is None
    assert meas_by_name["buyers.count"].type == "count_distinct"
    assert meas_by_name["buyers.count"].sql == "buyers.id "
    assert meas_by_name["buyers.total_spend"].type == "sum_distinct"
    assert meas_by_name["buyers.total_spend"].value_format == "$#,##0.00"
    assert "buyers.coords_latitude_min" in meas_by_name

    cli_res = runner.invoke(
        app,
        [
            "parse",
            "lookml-to-api",
            "--path",
            str(tmp_path),
            "--model",
            "shop",
            "--explore",
            "orders",
        ],
    )
    assert cli_res.exit_code == 0
    payload = json.loads(cli_res.stdout)
    assert payload["all_lookml_models"][0]["name"] == "shop"
    assert (
        payload["lookml_model_explores"]["shop::orders"]["joins"][0]["from"] == "users"
    )

    api_res = parse_lookml_to_api(path=tmp_path, model="shop", explore="orders")
    assert "shop::orders" in api_res.lookml_model_explores

    # Dotted field name scenario (e.g. dimension: foo.id with omitted sql)
    dotted_lkml = """
    view: order_items {
      dimension: foo.id {
        label: "ID"
        description: "Unique identifier for each order item (5 digits)"
        primary_key: yes
        type: number
        value_format: "00000"
      }
    }
    explore: order_items {}
    """
    raw_proj = parse_lookml(lookml=dotted_lkml)
    assert raw_proj.model is not None
    raw_views = raw_proj.model["inline"].view
    assert raw_views is not None
    raw_view = raw_views["order_items"]
    assert isinstance(raw_view, LookmlView)
    assert raw_view.dimension is not None
    raw_dim = raw_view.dimension["foo.id"]
    assert raw_dim.sql is None
    assert raw_dim.with_defaults().sql == "${TABLE}.`foo.id`"
    assert raw_dim.sql is None

    dotted_exp = lookml_to_lookml_model_explore(
        "inline", "order_items", project=raw_proj
    )
    # Passing project=raw_proj uses with_defaults() ephemerally without mutating raw_proj
    assert raw_dim.sql is None
    d_foo = dotted_exp.fields.dimensions[0]
    assert d_foo.name == "foo.id"
    assert d_foo.view == "order_items"
    assert d_foo.original_view == "order_items"
    assert d_foo.scope == "foo"
    assert d_foo.suggest_dimension == "foo.id"
    assert d_foo.suggest_explore == "order_items"
    assert d_foo.label == "Order Items ID"
    assert d_foo.label_short == "ID"
    assert d_foo.sql == "order_items.`foo.id`"
    assert "foo" in dotted_exp.scopes


def test_parse_lookml_to_api_thelookevent_parity():
    import pytest

    from lkr.parse import lookml_to_all_lookml_models, lookml_to_lookml_model_explore

    proj_dir = Path("tmp/thelookevent")
    models_json = Path("tmp/all_lookml_models.json")
    explore_json = Path("tmp/lookml_model_explore_thelook_order_items.json")
    if not (proj_dir.exists() and models_json.exists() and explore_json.exists()):
        pytest.skip("tmp/thelookevent reference fixtures not present")

    expected_models = json.loads(models_json.read_text(encoding="utf-8"))
    expected_thelook = next(m for m in expected_models if m["name"] == "thelook")
    actual_models = lookml_to_all_lookml_models(path=proj_dir, model="thelook")
    assert len(actual_models) == 1
    actual_m = actual_models[0].model_dump()

    for k in (
        "name",
        "label",
        "has_content",
        "unlimited_db_connections",
        "allowed_db_connection_names",
    ):
        assert actual_m[k] == expected_thelook[k]

    exp_nav_by_name = {e["name"]: e for e in expected_thelook["explores"]}
    act_nav_by_name = {e["name"]: e for e in actual_m["explores"]}
    assert set(act_nav_by_name) == set(exp_nav_by_name)
    for ename, exp_nav in exp_nav_by_name.items():
        act_nav = act_nav_by_name[ename]
        for k in ("name", "label", "description", "hidden", "group_label"):
            assert act_nav[k] == exp_nav[k], f"Mismatch on explore {ename}.{k}"

    expected_exp = json.loads(explore_json.read_text(encoding="utf-8"))
    actual_exp = lookml_to_lookml_model_explore(
        "thelook", "order_items", path=proj_dir
    ).model_dump(by_alias=True)

    for k in (
        "id",
        "name",
        "description",
        "connection_name",
        "null_sort_treatment",
        "source_file",
        "model_name",
        "view_name",
        "hidden",
        "sql_table_name",
        "group_label",
        "label",
        "title",
        "always_join",
        "tags",
    ):
        assert actual_exp[k] == expected_exp[k], f"Top-level mismatch on {k}"

    assert set(actual_exp["scopes"]) == set(expected_exp["scopes"])
    assert {(a["name"], a["value"]) for a in actual_exp["aliases"]} == {
        (a["name"], a["value"]) for a in expected_exp["aliases"]
    }

    exp_joins = {j["name"]: j for j in expected_exp["joins"]}
    act_joins = {j["name"]: j for j in actual_exp["joins"]}
    assert set(act_joins) == set(exp_joins)
    for jname, ej in exp_joins.items():
        aj = act_joins[jname]
        for jk in (
            "name",
            "from",
            "type",
            "relationship",
            "sql_on",
            "foreign_key",
            "view_label",
            "outer_only",
            "required_joins",
            "fields",
        ):
            assert aj[jk] == ej[jk], f"Join {jname}.{jk} mismatch"
        assert set(aj["dependent_fields"]) == set(ej["dependent_fields"])

    exp_sets = {s["name"]: set(s["value"]) for s in expected_exp["sets"]}
    act_sets = {s["name"]: set(s["value"]) for s in actual_exp["sets"]}
    assert act_sets == exp_sets
    exp_sets_list = {s["name"]: s["value"] for s in expected_exp["sets"]}
    act_sets_list = {s["name"]: s["value"] for s in actual_exp["sets"]}
    assert act_sets_list["user_order_facts"] == exp_sets_list["user_order_facts"]

    exp_tl = {t["name"]: t for t in expected_exp["turtle_looks"]}
    act_tl = {t["name"]: t for t in actual_exp["turtle_looks"]}
    assert set(act_tl) == set(exp_tl)
    for tname, et in exp_tl.items():
        at = act_tl[tname]
        for tk in (
            "name",
            "label",
            "label_short",
            "description",
            "dimensions",
            "measures",
            "pivots",
            "filters",
            "limit",
            "sorts",
            "can_turtle",
            "type",
        ):
            assert at[tk] == et[tk], f"Turtle look {tname}.{tk} mismatch"

    compare_field_keys = (
        "align",
        "can_filter",
        "category",
        "default_filter_value",
        "description",
        "enumerations",
        "field_group_label",
        "fill_style",
        "fiscal_month_offset",
        "has_allowed_values",
        "hidden",
        "is_filter",
        "is_numeric",
        "label",
        "label_from_parameter",
        "label_short",
        "map_layer",
        "name",
        "strict_value_format",
        "requires_refresh_on_sort",
        "sortable",
        "suggestions",
        "tags",
        "type",
        "user_attribute_filter_types",
        "value_format",
        "value_format_name",
        "view",
        "view_label",
        "dynamic",
        "week_start_day",
        "original_view",
        "dimension_group",
        "error",
        "field_group_variant",
        "measure",
        "parameter",
        "primary_key",
        "scope",
        "suggest_dimension",
        "suggest_explore",
        "suggestable",
        "is_fiscal",
        "is_timeframe",
        "can_time_filter",
        "time_interval",
        "source_file",
        "sql",
        "sql_case",
        "filters",
    )
    for section in ("dimensions", "measures", "filters", "parameters"):
        exp_flds = {f["name"]: f for f in expected_exp["fields"][section]}
        act_flds = {f["name"]: f for f in actual_exp["fields"][section]}
        assert set(act_flds) == set(exp_flds), f"Field set mismatch in {section}"
        for fname, ef in exp_flds.items():
            af = act_flds[fname]
            for fk in compare_field_keys:
                assert af[fk] == ef[fk], (
                    f"Field {fname}.{fk} mismatch: {af[fk]!r} != {ef[fk]!r}"
                )


def test_parse_lookml_to_api_discrepancy_fixes():
    from lkr.parse import lookml_to_lookml_model_explore

    lkml = """
    view: order_items {
      view_label: "Order Items"
      set: detail {
        fields: [order_id, status, created_date, sale_price, products.brand, products.item_name, users.portrait, users.name, users.email]
      }
      set: expanded_detail {
        fields: [detail*, -sale_price]
      }
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: sale_price {
        type: number
        sql: ${TABLE}.sale_price ;;
      }
      dimension: price_bucket_case {
        case: {
          when: {
            sql: ${sale_price} < 20 ;;
            label: "Low"
          }
          when: {
            sql: ${sale_price} < 100 ;;
            label: "Medium"
          }
          else: "High"
        }
      }
      dimension_group: created {
        type: time
        timeframes: [raw, time, date]
        sql: ${TABLE}.created_at ;;
      }
      dimension_group: shipped {
        type: time
        timeframes: [raw, date]
        sql: ${TABLE}.shipped_at ;;
      }
      dimension_group: shipping_duration {
        type: duration
        intervals: [hour, day]
        sql_start: ${created_raw} ;;
        sql_end: ${shipped_raw} ;;
      }
      parameter: metric_selector {
        type: unquoted
        default_value: "sale_price"
        allowed_value: {
          label: "Sale Price"
          value: "sale_price"
        }
        allowed_value: {
          label: "Gross Margin"
          value: "gross_margin"
        }
      }
      dimension: dynamic_metric_dim {
        type: number
        label_from_parameter: metric_selector
        sql: ${TABLE}.{% parameter metric_selector %} ;;
      }
      dimension: warehouse_to_user_distance {
        type: distance
        start_location_field: distribution_centers.location
        end_location_field: users.location
        units: kilometers
      }
    }
    explore: order_items {
      label: "(1) Orders, Items and Users"
      view_name: order_items
      always_filter: {
        filters: [order_items.status: "Complete"]
      }
      conditionally_filter: {
        filters: [order_items.created_date: "7 days"]
        unless: [order_items.id]
      }
    }
    """
    exp = lookml_to_lookml_model_explore(
        "inline", "order_items", lookml=lkml
    ).model_dump(by_alias=True)

    # Error 1: always_filter & conditionally_filter
    assert exp["always_filter"] == [{"name": "order_items.status", "value": "Complete"}]
    assert exp["conditionally_filter"] == [
        {"name": "order_items.created_date", "value": "7 days"}
    ]

    # Error 2: set* expansion and -field exclusion
    sets_by_name = {s["name"]: s["value"] for s in exp["sets"]}
    assert sets_by_name["order_items.expanded_detail"] == [
        "order_items.order_id",
        "order_items.status",
        "order_items.created_date",
        "products.brand",
        "products.item_name",
        "users.portrait",
        "users.name",
        "users.email",
    ]

    dims = {d["name"]: d for d in exp["fields"]["dimensions"]}
    params = {p["name"]: p for p in exp["fields"]["parameters"]}

    # Error 3: case dimension
    case_dim = dims["order_items.price_bucket_case"]
    assert case_dim["enumerations"] == [
        {"label": "Low", "value": "Low"},
        {"label": "Medium", "value": "Medium"},
        {"label": "High", "value": "High"},
    ]
    assert case_dim["fill_style"] == "enumeration"
    assert (
        case_dim["sql"]
        == "CASE\nWHEN ${sale_price} < 20  THEN 'Low'\nWHEN ${sale_price} < 100  THEN 'Medium'\nELSE 'High'\nEND"
    )
    assert case_dim["sql_case"] == [
        {"value": "Low", "condition": "${sale_price} < 20 "},
        {"value": "Medium", "condition": "${sale_price} < 100 "},
        {"value": "High", "condition": "else"},
    ]
    assert case_dim["suggestions"] == ["Low", "Medium", "High"]

    # Error 4: duration dimension_group
    assert "order_items.shipping_duration_hour" not in dims
    for iv_plural, iv_singular, variant in (
        ("days", "day", "Days"),
        ("hours", "hour", "Hours"),
    ):
        d_dur = dims[f"order_items.{iv_plural}_shipping_duration"]
        assert d_dur["type"] == f"duration_{iv_singular}"
        assert d_dur["label"] == f"Order Items {variant} Shipping Duration"
        assert d_dur["label_short"] == f"{variant} Shipping Duration"
        assert d_dur["field_group_label"] == "Duration Shipping Duration"
        assert d_dur["field_group_variant"] == variant
        assert d_dur["dimension_group"] == "order_items.shipping_duration"
        assert d_dur["sql"] == "Start:\n${created_raw} \n\nEnd:\n${shipped_raw} "
        assert d_dur["is_numeric"] is True
        assert d_dur["align"] == "right"

    # Error 5: parameter default_value/allowed_value and dimension label_from_parameter
    p_sel = params["order_items.metric_selector"]
    assert p_sel["default_filter_value"] == "sale^_price"
    assert p_sel["has_allowed_values"] is True
    assert p_sel["enumerations"] == [
        {"label": "Sale Price", "value": "sale^_price"},
        {"label": "Gross Margin", "value": "gross^_margin"},
    ]
    assert (
        dims["order_items.dynamic_metric_dim"]["label_from_parameter"]
        == "metric_selector"
    )

    # Error 6: distance units value_format
    assert (
        dims["order_items.warehouse_to_user_distance"]["value_format"]
        == '#,##0.00" km"'
    )

    # Batch 2 (ERRORS_1.md) cases
    lkml_b2 = """
    view: users {
      sql_table_name: `looker-private-demo.ecomm.users` ;;
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
    }
    view: products {
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: sku {
        type: string
        sql: ${TABLE}.sku ;;
      }
      dimension: brand {
        type: string
        sql: ${TABLE}.brand ;;
      }
    }
    view: order_items {
      view_label: "Order Items"
      set: set_with_dg_and_view_wildcard {
        fields: [created, products*, -products.sku]
      }
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: sale_price {
        type: number
        sql: ${TABLE}.sale_price ;;
      }
      dimension: status {
        type: string
        sql: ${TABLE}.status ;;
      }
      dimension_group: created {
        type: time
        timeframes: [raw, date]
        sql: ${TABLE}.created_at ;;
      }
      dimension: tier_classic_dim {
        type: tier
        tiers: [10, 50, 100]
        style: classic
        sql: ${sale_price} ;;
      }
      dimension: tier_relational_dim {
        type: tier
        tiers: [10, 50, 100]
        style: relational
        sql: ${sale_price} ;;
      }
      dimension: non_suggestable_dim {
        type: string
        suggestable: no
        sql: ${status} ;;
      }
      dimension: standalone_date_dim {
        type: date
        sql: DATE(${created_raw}) ;;
      }
      dimension: case_alpha_sort_dim {
        alpha_sort: yes
        case: {
          when: {
            sql: ${sale_price} < 20 ;;
            label: "Zebra"
          }
          when: {
            sql: ${sale_price} < 100 ;;
            label: "Apple"
          }
        }
      }
      dimension: case_no_else_dim {
        case: {
          when: {
            sql: ${sale_price} < 20 ;;
            label: "Low"
          }
        }
      }
      measure: first_order_date {
        type: date
        sql: MIN(${created_date}) ;;
      }
      measure: is_big_order {
        type: yesno
        sql: SUM(${sale_price}) > 1000 ;;
      }
      measure: status_summary_str {
        type: string
        sql: STRING_AGG(DISTINCT ${status}, ', ') ;;
      }
    }
    explore: order_items {
      view_name: order_items
      join: fk_users {
        from: users
        foreign_key: order_items.user_id
      }
      join: products {
        type: left_outer
        relationship: many_to_one
        sql_on: ${order_items.id} = ${products.id} ;;
      }
    }
    """
    exp2 = lookml_to_lookml_model_explore(
        "inline", "order_items", lookml=lkml_b2
    ).model_dump(by_alias=True)

    # B2 Error 1: join sql_table_name is None unless specified on the join
    joins2 = {j["name"]: j for j in exp2["joins"]}
    assert joins2["fk_users"]["sql_table_name"] is None
    assert joins2["fk_users"]["dependent_fields"] == ["order_items.user_id"]

    dims2 = {d["name"]: d for d in exp2["fields"]["dimensions"]}
    meas2 = {m["name"]: m for m in exp2["fields"]["measures"]}
    sets2 = {s["name"]: s["value"] for s in exp2["sets"]}

    # B2 Error 2: tier style: classic and style: relational
    tc = dims2["order_items.tier_classic_dim"]
    assert tc["enumerations"] == [
        {"label": "T00 (-inf,10.0)", "value": "T00 (-inf,10.0)"},
        {"label": "T01 [10.0,50.0)", "value": "T01 [10.0,50.0)"},
        {"label": "T02 [50.0,100.0)", "value": "T02 [50.0,100.0)"},
        {"label": "T03 [100.0,inf)", "value": "T03 [100.0,inf)"},
        {"label": "TXX Undefined", "value": "TXX Undefined"},
    ]
    assert tc["suggestions"] == [
        "T00 (-inf,10.0)",
        "T01 [10.0,50.0)",
        "T02 [50.0,100.0)",
        "T03 [100.0,inf)",
        "TXX Undefined",
    ]
    tr = dims2["order_items.tier_relational_dim"]
    assert tr["enumerations"] == [
        {"label": "< 10.0", "value": "< 10.0"},
        {"label": ">= 10.0 and < 50.0", "value": ">= 10.0 and < 50.0"},
        {"label": ">= 50.0 and < 100.0", "value": ">= 50.0 and < 100.0"},
        {"label": ">= 100.0", "value": ">= 100.0"},
        {"label": "Undefined", "value": "Undefined"},
    ]
    assert (
        tr["sql"]
        == "CASE\nWHEN ${sale_price}  < 10.0 THEN '< 10.0'\nWHEN ${sale_price}  >= 10.0 AND ${sale_price}  < 50.0 THEN '>= 10.0 and < 50.0'\nWHEN ${sale_price}  >= 50.0 AND ${sale_price}  < 100.0 THEN '>= 50.0 and < 100.0'\nWHEN ${sale_price}  >= 100.0 THEN '>= 100.0'\nELSE 'Undefined'\nEND"
    )

    # B2 Error 3 & 4: non-numeric measures (date, yesno, string)
    m_date = meas2["order_items.first_order_date"]
    assert m_date["align"] == "left"
    assert m_date["is_numeric"] is False
    assert m_date["time_interval"] == {"name": "day", "count": 1}
    assert m_date["user_attribute_filter_types"] == [
        "datetime",
        "advanced_filter_datetime",
    ]

    m_yn = meas2["order_items.is_big_order"]
    assert m_yn["align"] == "left"
    assert m_yn["is_numeric"] is False
    assert m_yn["label"] == "Order Items Is Big Order (Yes / No)"
    assert m_yn["label_short"] == "Is Big Order (Yes / No)"
    assert m_yn["user_attribute_filter_types"] == ["string", "advanced_filter_string"]

    m_str = meas2["order_items.status_summary_str"]
    assert m_str["align"] == "left"
    assert m_str["is_numeric"] is False
    assert m_str["user_attribute_filter_types"] == ["string", "advanced_filter_string"]

    # B2 Error 5: suggestable: no override
    assert dims2["order_items.non_suggestable_dim"]["suggestable"] is False

    # B2 Error 6: standalone dimension type: date
    d_date = dims2["order_items.standalone_date_dim"]
    assert d_date["fill_style"] == "range"
    assert d_date["time_interval"] == {"name": "day", "count": 1}

    # B2 Error 7: case without else + alpha_sort vs default sort field in view set
    d_alpha = dims2["order_items.case_alpha_sort_dim"]
    assert (
        d_alpha["sql"]
        == "CASE\nWHEN ${sale_price} < 20  THEN 'Zebra'\nWHEN ${sale_price} < 100  THEN 'Apple'\n\nEND"
    )
    assert "order_items.case_alpha_sort_dim__sort_" not in sets2["order_items"]
    assert "order_items.case_no_else_dim__sort_" in sets2["order_items"]

    # B2 Error 8: set expansion with built-in view wildcard (products*) and exclusion (-products.sku)
    assert sets2["order_items.set_with_dg_and_view_wildcard"] == [
        "order_items.created",
        "products.id",
        "products.brand",
    ]

    # Batch 3 (ERRORS_2.md) cases
    lkml_b3 = """
    fiscal_month_offset: 3
    week_start_day: sunday

    named_value_format: custom_eur {
      value_format: "€#,##0.00"
      strict_value_format: yes
    }

    map_layer: custom_sales_regions {
      file: "/maps/regions.topojson"
      property_key: "region_code"
    }

    view: products {
      suggestions: no
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: category {
        type: string
        sql: ${TABLE}.category ;;
      }
      dimension: brand {
        type: string
        suggestable: yes
        sql: ${TABLE}.brand ;;
      }
      measure: median_price {
        type: median
        sql: ${TABLE}.retail_price ;;
      }
      measure: p90_price {
        type: percentile
        percentile: 90
        sql: ${TABLE}.retail_price ;;
      }
    }

    view: order_items {
      view_label: "Order Items"
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: sale_price {
        type: number
        synonyms: ["revenue", "price"]
        value_format_name: custom_eur
        sql: ${TABLE}.sale_price ;;
      }
      dimension: sales_region {
        type: string
        map_layer_name: custom_sales_regions
        sql: ${TABLE}.sales_region ;;
      }
      dimension: state_built_in_layer {
        type: string
        map_layer_name: us_states
        sql: ${TABLE}.state ;;
      }
      dimension: price_bin_dim {
        type: bin
        bins: [10, 50, 100]
        sql: ${sale_price} ;;
      }
      dimension: created_by_user {
        type: string
        sql: ${TABLE}.created_by_user ;;
      }
      dimension: suggest_from_status {
        type: string
        suggest_dimension: status
        sql: ${TABLE}.status ;;
      }
      dimension: status {
        type: string
        sql: ${TABLE}.status ;;
      }
      dimension: custom_hours_wait {
        type: duration_hour
        sql_start: ${created_raw} ;;
        sql_end: ${shipped_raw} ;;
      }
      dimension_group: shipped {
        type: time
        timeframes: [raw, date, yesno]
        sql: ${TABLE}.shipped_at ;;
      }
      dimension_group: created {
        type: time
        allow_fill: no
        synonyms: ["order_date"]
        timeframes: [
          raw, date, second, minute15, hour6, millisecond, microsecond,
          day_of_week, day_of_week_index,
          fiscal_year, fiscal_quarter, fiscal_month_num, fiscal_quarter_of_year
        ]
        sql: ${TABLE}.created_at ;;
      }
      dimension_group: default_dur {
        type: duration
        sql_start: ${created_raw} ;;
        sql_end: ${shipped_raw} ;;
      }
      measure: first_created {
        type: time
        timeframes: [raw, time, date]
        sql: MIN(${created_raw}) ;;
      }
      measure: pop_sales {
        type: percent_of_previous
        sql: ${sale_price} ;;
      }
      measure: running_sales {
        type: running_total
        sql: ${sale_price} ;;
      }
      measure: zip_measure {
        type: zipcode
        sql: MAX(${TABLE}.zip) ;;
      }
      measure: total_sales {
        type: sum
        sql: ${sale_price} ;;
      }
      measure: deal_size_tier {
        case: {
          when: {
            sql: ${total_sales} < 100 ;;
            label: "Small"
          }
          else: "Large"
        }
      }
      measure: suggested_measure {
        type: string
        suggest_dimension: products.category
        suggest_explore: custom_exp
        suggestions: ["A", "B"]
        sql: MAX(${status}) ;;
      }
      filter: status_filter {
        type: string
        suggest_dimension: status
        suggestions: ["Complete", "Pending"]
      }
    }

    explore: orders_aliased {
      view_name: order_items
      conditionally_filter: {
        filters: [order_items.shipped_date: "7 days"]
        unless: [id]
      }
      join: products {
        type: one_to_many
        relationship: one_to_many
        sql_on: ${order_items.id} = ${products.id} ;;
        sql_where: ${products.category} = ${order_items.status} ;;
      }
    }
    """
    exp3 = lookml_to_lookml_model_explore(
        "inline", "orders_aliased", lookml=lkml_b3
    ).model_dump(by_alias=True)

    # Error 18, 19, 25: index_fields, join dependent_fields with sql_where first, scopes with explore_name
    assert exp3["index_fields"] == [
        "order_items.id",
        "order_items.shipped",
        "order_items.shipped_date",
    ]
    assert exp3["scopes"][0] == "orders_aliased"
    assert "order_items" in exp3["scopes"]
    joins3 = {j["name"]: j for j in exp3["joins"]}
    assert joins3["products"]["dependent_fields"] == [
        "products.category",
        "order_items.status",
        "order_items.id",
        "products.id",
    ]

    dims3 = {d["name"]: d for d in exp3["fields"]["dimensions"]}
    meas3 = {m["name"]: m for m in exp3["fields"]["measures"]}
    filts3 = {f["name"]: f for f in exp3["fields"]["filters"]}
    sets3 = {s["name"]: s["value"] for s in exp3["sets"]}

    # Error 1 & 17: fiscal_month_offset & week_start_day + rotated day_of_week enumerations
    d_dow = dims3["order_items.created_day_of_week"]
    assert d_dow["fiscal_month_offset"] == 3
    assert d_dow["week_start_day"] == "sunday"
    assert d_dow["enumerations"][0] == {"label": "Sunday", "value": "Sunday"}
    assert dims3["order_items.created_day_of_week_index"]["enumerations"][0] == {
        "label": "0 - Sunday",
        "value": "0",
    }

    # Error 2: named_value_format
    d_sp = dims3["order_items.sale_price"]
    assert d_sp["value_format"] == "€#,##0.00"
    assert d_sp["strict_value_format"] is True
    assert d_sp["synonyms"] == ["revenue", "price"]

    # Error 3: map_layer
    assert (
        dims3["order_items.sales_region"]["map_layer"]["name"] == "custom_sales_regions"
    )
    assert (
        dims3["order_items.sales_region"]["map_layer"]["url"]
        == "/maps/regions.topojson"
    )
    assert dims3["order_items.state_built_in_layer"]["map_layer"]["name"] == "us_states"

    # Error 4 & 5: dimension_group synonyms and allow_fill: no
    assert dims3["order_items.created_date"]["synonyms"] == ["order_date"]
    assert dims3["order_items.created_date"]["fill_style"] is None
    assert dims3["order_items.created_day_of_week"]["fill_style"] is None

    # Error 6: type: bin / bins:
    d_bin = dims3["order_items.price_bin_dim"]
    assert d_bin["type"] == "tier"
    assert d_bin["fill_style"] == "enumeration"
    assert d_bin["suggestable"] is True
    assert len(d_bin["enumerations"]) == 5

    # Error 7: yesno timeframe
    d_yn_tf = dims3["order_items.shipped"]
    assert d_yn_tf["type"] == "yesno"
    assert d_yn_tf["field_group_variant"] == "Yes / No"
    assert d_yn_tf["label_short"] == "Shipped (Yes / No)"

    # Error 8: fiscal and granular timeframes
    assert dims3["order_items.created_fiscal_year"]["is_fiscal"] is True
    assert dims3["order_items.created_fiscal_month_num"]["is_numeric"] is True
    assert dims3["order_items.created_fiscal_quarter_of_year"]["fill_style"] is None
    assert dims3["order_items.created_minute15"]["time_interval"] == {
        "name": "minute",
        "count": 15,
    }
    assert dims3["order_items.created_minute15"]["can_time_filter"] is True

    # Error 9 & 20: default duration order & standalone duration_* dimension
    dur_names = [f for f in sets3["order_items"] if f.endswith("_default_dur")]
    assert dur_names == [
        f"order_items.{u}s_default_dur"
        for u in ("year", "quarter", "month", "week", "day", "hour", "minute", "second")
    ]
    assert dims3["order_items.days_default_dur"]["value_format"] == "0"
    d_ch = dims3["order_items.custom_hours_wait"]
    assert d_ch["sql"] == "Start:\n${created_raw} \n\nEnd:\n${shipped_raw} "
    assert d_ch["value_format"] == "0"

    # Error 10: view suggestions: no vs field suggestable: yes
    assert dims3["products.category"]["suggestable"] is False
    assert dims3["products.brand"]["suggestable"] is True

    # Error 11 & 13: measure type: time expansion and non-numeric date_* measures
    m_fc_date = meas3["order_items.first_created_date"]
    assert m_fc_date["type"] == "date_date"
    assert m_fc_date["is_numeric"] is False
    assert m_fc_date["align"] == "left"
    assert m_fc_date["can_time_filter"] is False
    assert meas3["order_items.first_created_time"]["can_time_filter"] is False

    # Error 12 & 21: percent_of_previous, running_total, zipcode measure
    m_pop = meas3["order_items.pop_sales"]
    assert m_pop["can_filter"] is False
    assert m_pop["requires_refresh_on_sort"] is True
    assert m_pop["user_attribute_filter_types"] == []
    assert m_pop["value_format"] == '#,##0"%"'
    m_rt = meas3["order_items.running_sales"]
    assert m_rt["can_filter"] is False
    assert m_rt["requires_refresh_on_sort"] is True
    assert m_rt["user_attribute_filter_types"] == []
    m_zip = meas3["order_items.zip_measure"]
    assert m_zip["is_numeric"] is False
    assert m_zip["align"] == "left"
    assert m_zip["user_attribute_filter_types"] == ["string", "advanced_filter_string"]

    # Error 14: measure with case:
    m_case = meas3["order_items.deal_size_tier"]
    assert m_case["enumerations"] == [
        {"label": "Small", "value": "Small"},
        {"label": "Large", "value": "Large"},
    ]
    assert m_case["fill_style"] == "enumeration"
    assert m_case["suggestable"] is True
    assert "order_items.deal_size_tier__sort_" in sets3["order_items"]

    # Error 15: symmetric join median_distinct & percentile_distinct
    assert meas3["products.median_price"]["type"] == "median_distinct"
    assert meas3["products.p90_price"]["type"] == "percentile_distinct"

    # Error 16: _titleize("created_by_user") capitalizes "By"
    assert dims3["order_items.created_by_user"]["label_short"] == "Created By User"

    # Error 22: suggest_dimension qualification and measure/filter suggest metadata
    assert (
        dims3["order_items.suggest_from_status"]["suggest_dimension"]
        == "order_items.status"
    )
    assert (
        meas3["order_items.suggested_measure"]["suggest_dimension"]
        == "products.category"
    )
    assert meas3["order_items.suggested_measure"]["suggest_explore"] == "custom_exp"
    assert meas3["order_items.suggested_measure"]["suggestions"] == ["A", "B"]
    assert (
        filts3["order_items.status_filter"]["suggest_dimension"] == "order_items.status"
    )
    assert filts3["order_items.status_filter"]["suggestions"] == ["Complete", "Pending"]


def test_parse_sql_to_lookml_unqualified_sql_error():
    import pytest

    from lkr.parse import parse_sql_to_lookml

    lkml = "view: foo { sql_table_name: db.schema.foo ;; dimension: a {} }"
    with pytest.raises(ValueError, match="SQL table 'foo' is unqualified"):
        parse_sql_to_lookml(sql="SELECT a FROM foo", lookml=lkml)

    # CLI exit code 1
    cli_res = runner.invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", "SELECT a FROM foo", "--lookml", lkml],
    )
    assert cli_res.exit_code == 1


def test_parse_sql_to_lookml_unqualified_lookml_error():
    import pytest

    from lkr.parse import parse_sql_to_lookml

    lkml = "view: foo { sql_table_name: foo ;; dimension: a {} }"
    with pytest.raises(
        ValueError, match="LookML view 'foo' table 'foo' cannot be qualified"
    ):
        parse_sql_to_lookml(sql="SELECT a FROM db.schema.foo", lookml=lkml)


def test_parse_sql_to_lookml_database_mismatch():
    from lkr.parse import parse_sql_to_lookml

    # databaseA.schema1.foo vs databaseB.schema2.foo must NOT match
    lkml = "view: foo { sql_table_name: databaseB.schema2.foo ;; dimension: a {} }"
    res = parse_sql_to_lookml(sql="SELECT a FROM databaseA.schema1.foo", lookml=lkml)
    assert len(res.queries) == 1
    assert len(res.queries[0].views) == 0


def test_parse_sql_to_lookml_fully_qualified_no_flags():
    from lkr.parse import parse_sql_to_lookml

    # When both sides are fully qualified, no flags or connection are required
    lkml = "view: foo { sql_table_name: databaseA.schema1.foo ;; dimension: a {} }"
    res = parse_sql_to_lookml(sql="SELECT a FROM databaseA.schema1.foo", lookml=lkml)
    assert len(res.queries) == 1
    assert len(res.queries[0].views) == 1
    assert res.queries[0].views[0].view_name == "foo"


def test_parse_sql_to_lookml_connection_coercion(monkeypatch):
    import lkr.parse.sql_to_lookml as s2l
    from lkr.parse import parse_sql_to_lookml

    monkeypatch.setattr(
        s2l,
        "_fetch_connection_metadata_sandbox",
        lambda conn_name: (
            {"database": "db_live", "schema": "schema_live"}
            if conn_name == "thelook"
            else None
        ),
    )

    lkml = """
    connection: "thelook"
    view: foo {
      sql_table_name: foo ;;
      dimension: a {}
    }
    """
    res = parse_sql_to_lookml(sql="SELECT a FROM db_live.schema_live.foo", lookml=lkml)
    assert len(res.queries) == 1
    assert len(res.queries[0].views) == 1
    assert res.queries[0].views[0].view_name == "foo"


def test_parse_sql_to_lookml_native_derived_table():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id {
        type: number
      }
    }
    view: customer_order_summary {
      derived_table: {
        explore_source: orders {
          column: user_id {
            field: orders.customer_id
          }
        }
      }
      dimension: ordering_user_id {
        type: number
        primary_key: yes
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "orders" in views_by_name
    assert "customer_order_summary" in views_by_name
    ndt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in ndt_fields
    assert ndt_fields["ordering_user_id"].via == ["orders.customer_id"]


def test_parse_sql_to_lookml_sql_derived_table():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id {
        type: number
      }
    }
    view: customer_order_summary {
      derived_table: {
        sql: SELECT customer_id as user_id FROM ${orders.SQL_TABLE_NAME} ;;
      }
      dimension: ordering_user_id {
        type: number
        primary_key: yes
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "orders" in views_by_name
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields
    assert dt_fields["ordering_user_id"].via == ["orders.customer_id"]


def test_parse_sql_to_lookml_ndt_with_derived_column():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id { type: number }
      dimension: account_id { type: number }
    }
    view: customer_order_summary {
      derived_table: {
        explore_source: orders {
          column: user_id {
            field: orders.customer_id
          }
          column: account_id {
            field: orders.account_id
          }
          derived_column: account_key { sql: CONCAT(STRING(account_id),'::',STRING(account_id)) ;; }
        }
      }
      dimension: ordering_user_id {
        type: number
        primary_key: yes
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "orders" in views_by_name
    assert "customer_order_summary" in views_by_name
    ndt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in ndt_fields


def test_parse_sql_to_lookml_ndt_chained_derived_column():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id { type: number }
    }
    view: customer_order_summary {
      derived_table: {
        explore_source: orders {
          column: user_id {
            field: orders.customer_id
          }
          derived_column: base_key {
            sql: STRING(user_id) ;;
          }
          derived_column: composite_key {
            sql: CONCAT(base_key, '::1') ;;
          }
        }
      }
      dimension: composite_user_key {
        type: string
        sql: ${TABLE}.composite_key ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "orders" in views_by_name
    assert "customer_order_summary" in views_by_name
    ndt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "composite_user_key" in ndt_fields
    assert ndt_fields["composite_user_key"].via == ["orders.customer_id"]


def test_parse_sql_to_lookml_dt_cte_column_alias():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id { type: number }
    }
    view: customer_order_summary {
      derived_table: {
        sql:
          WITH base_orders AS (
            SELECT customer_id AS cid
            FROM ${orders.SQL_TABLE_NAME}
          )
          SELECT cid AS user_id
          FROM base_orders ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_dt_subquery_column_alias():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id { type: number }
    }
    view: customer_order_summary {
      derived_table: {
        sql:
          SELECT sub.cid AS user_id
          FROM (
            SELECT customer_id AS cid
            FROM ${orders.SQL_TABLE_NAME}
          ) sub ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_dt_union_all_second_branch():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: orders {
      sql_table_name: a.b.orders ;;
      dimension: customer_id { type: number }
    }
    view: archived_orders {
      sql_table_name: a.b.archived_orders ;;
      dimension: archived_customer_id { type: number }
    }
    view: all_customer_orders {
      derived_table: {
        sql:
          SELECT customer_id AS user_id FROM ${orders.SQL_TABLE_NAME}
          UNION ALL
          SELECT archived_customer_id AS user_id FROM ${archived_orders.SQL_TABLE_NAME} ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(
        sql="SELECT archived_customer_id FROM a.b.archived_orders", lookml=lkml
    )
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "all_customer_orders" in views_by_name
    dt_fields = {f.field_name: f for f in views_by_name["all_customer_orders"].fields}
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_dt_raw_table_without_sql_table_name_macro():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: customer_order_summary {
      derived_table: {
        sql: SELECT customer_id AS user_id FROM a.b.orders ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_dt_chained_cte_raw_table():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: customer_order_summary {
      derived_table: {
        sql:
          WITH raw_orders AS (
            SELECT customer_id AS cid
            FROM a.b.orders
          ),
          deduped_orders AS (
            SELECT DISTINCT cid AS unique_cid
            FROM raw_orders
          )
          SELECT unique_cid AS user_id
          FROM deduped_orders ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_dt_join_subquery_raw_table():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: customer_order_summary {
      derived_table: {
        sql:
          SELECT o.cid AS user_id
          FROM a.b.users u
          JOIN (
            SELECT customer_id AS cid
            FROM a.b.orders
          ) o ON u.id = o.cid ;;
      }
      dimension: ordering_user_id {
        type: number
        sql: ${TABLE}.user_id ;;
      }
    }
    """
    res = parse_sql_to_lookml(sql="SELECT customer_id FROM a.b.orders", lookml=lkml)
    views_by_name = {v.view_name: v for v in res.queries[0].views}
    assert "customer_order_summary" in views_by_name
    dt_fields = {
        f.field_name: f for f in views_by_name["customer_order_summary"].fields
    }
    assert "ordering_user_id" in dt_fields


def test_parse_sql_to_lookml_star_and_modifiers():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    view: users {
      sql_table_name: db.s.users ;;
      dimension: id { type: number }
      dimension: email { type: string }
      dimension: secret_hash { type: string }
      dimension: status { type: string }
    }
    view: orders {
      sql_table_name: db.s.orders ;;
      dimension: user_id { type: number }
      dimension: amount { type: number }
      dimension: internal_note { type: string }
    }
    view: active_users_dt {
      derived_table: {
        sql: SELECT * EXCEPT (secret_hash) FROM ${users.SQL_TABLE_NAME} WHERE status = 'active' ;;
      }
      dimension: email { sql: ${TABLE}.email ;; }
      dimension: secret_hash { sql: ${TABLE}.secret_hash ;; }
    }
    """

    # 1. Outer select over CTE with EXCEPT and WHERE
    res_cte = parse_sql_to_lookml(
        sql="""
        WITH base AS (
            SELECT id, email, secret_hash, status
            FROM db.s.users
            WHERE status = 'active'
        )
        SELECT * EXCEPT (secret_hash, status)
        FROM base
        """,
        lookml=lkml,
        dialect="bigquery",
    )
    u_fields_cte = {
        f.field_name
        for v in res_cte.queries[0].views
        if v.view_name == "users"
        for f in v.fields
    }
    assert u_fields_cte == {"id", "email", "status"}
    dt_fields_cte = {
        f.field_name: f
        for v in res_cte.queries[0].views
        if v.view_name == "active_users_dt"
        for f in v.fields
    }
    assert set(dt_fields_cte) == {"email"}
    assert dt_fields_cte["email"].via == ["users.email"]

    # 2. Direct physical table SELECT * EXCEPT / REPLACE (BigQuery) and EXCLUDE / RENAME (Snowflake)
    res_phys = parse_sql_to_lookml(
        sql="SELECT * EXCEPT (secret_hash, status) REPLACE (LOWER(email) AS email) FROM db.s.users",
        lookml=lkml,
        dialect="bigquery",
    )
    u_fields_phys = {
        f.field_name
        for v in res_phys.queries[0].views
        if v.view_name == "users"
        for f in v.fields
    }
    assert u_fields_phys == {"id", "email"}

    res_sf = parse_sql_to_lookml(
        sql="SELECT * EXCLUDE (secret_hash, status) RENAME (email AS user_email) FROM db.s.users",
        lookml=lkml,
        dialect="snowflake",
    )
    u_fields_sf = {
        f.field_name
        for v in res_sf.queries[0].views
        if v.view_name == "users"
        for f in v.fields
    }
    assert u_fields_sf == {"id", "email"}

    # 3. Multi-hop CTEs over physical tables
    res_chain = parse_sql_to_lookml(
        sql="""
        WITH raw_users AS (
            SELECT * EXCEPT (secret_hash, status) FROM db.s.users
        ),
        enriched AS (
            SELECT r.*, o.amount, o.internal_note
            FROM raw_users r
            JOIN db.s.orders o ON r.id = o.user_id
        )
        SELECT * EXCEPT (internal_note)
        FROM enriched
        """,
        lookml=lkml,
        dialect="bigquery",
    )
    by_view = {
        v.view_name: {f.field_name for f in v.fields}
        for v in res_chain.queries[0].views
    }
    assert by_view["users"] == {"id", "email"}
    assert by_view["orders"] == {"user_id", "amount"}

    # 4. Multi-table join with qualified stars, including an unmodeled joined table
    res_join = parse_sql_to_lookml(
        sql="""
        SELECT u.* EXCEPT (secret_hash, status), x.* EXCEPT (internal_note)
        FROM db.s.users u
        JOIN db.s.unmodeled_tbl x ON u.id = x.user_id
        """,
        lookml=lkml,
        dialect="bigquery",
    )
    u_fields_join = {
        f.field_name
        for v in res_join.queries[0].views
        if v.view_name == "users"
        for f in v.fields
    }
    assert u_fields_join == {"id", "email"}

    # 5. Live DB connection_columns gap analysis (unmodeled_db_columns / missing_db_columns)
    from unittest.mock import patch

    import lkr.parse.sql_to_lookml as s2l

    with patch.object(
        s2l,
        "_fetch_table_columns_sandbox",
        side_effect=lambda conn, db, schema, tbl: (
            {"id": "INT64", "email": "STRING", "new_db_col": "STRING"}
            if tbl == "users"
            else None
        ),
    ):
        res_gap = parse_sql_to_lookml(
            sql="SELECT * FROM db.s.users",
            lookml="""
            connection: "bq_conn"
            view: users {
              sql_table_name: `db.s.users` ;;
              dimension: id { primary_key: yes }
              dimension: email { sql: ${TABLE}.email ;; }
              dimension: dropped_col { sql: ${TABLE}.dropped_col ;; }
              dimension: static_label { sql: "constant" ;; }
            }
            """,
            dialect="bigquery",
        )
        v_gap = res_gap.queries[0].views[0]
        assert v_gap.unmodeled_db_columns == ["new_db_col"]
        assert v_gap.missing_db_columns == ["dropped_col"]
        assert {f.field_name for f in v_gap.fields} == {"id", "email"}


def test_parse_sql_to_lookml_aggregate_tables_and_explore_queries():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
    connection: "bq"
    view: users {
      sql_table_name: db.s.users ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: country { type: string sql: ${TABLE}.country ;; }
      dimension: tier { type: string sql: ${TABLE}.tier ;; }
    }
    view: orders {
      sql_table_name: db.s.orders ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: user_id { type: number sql: ${TABLE}.user_id ;; }
      dimension: status { type: string sql: ${TABLE}.status ;; }
      dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }
      dimension_group: created {
        type: time
        timeframes: [raw, date, month, year]
        sql: ${TABLE}.created_at ;;
      }
      measure: total_revenue {
        type: sum
        sql: ${sale_price} ;;
      }
    }
    explore: orders {
      join: users {
        type: left_outer
        relationship: many_to_one
        sql_on: ${orders.user_id} = ${users.id} ;;
      }
      aggregate_table: monthly_rollup {
        query: {
          dimensions: [created_month, users.country]
          measures: [total_revenue]
          filters: [orders.status: "complete"]
          timeframe_granularity: month
        }
        materialization: {
          datagroup_trigger: orders_datagroup
          increment_key: "created_date"
        }
      }
      aggregate_table: trigger_partial {
        query: {
          dimensions: [users.country]
          measures: [total_revenue]
        }
        materialization: {
          sql_trigger_value: SELECT MAX(o.created_at) FROM db.s.orders o ;;
        }
      }
      query: exact_summary {
        dimensions: [created_month, users.country]
        measures: [total_revenue]
        filters: [orders.status: "complete"]
        sorts: [total_revenue: desc]
      }
      query: partial_with_pivots {
        dimensions: [users.country]
        measures: [total_revenue]
        pivots: [users.tier]
      }
    }
    """
    sql = """
    SELECT u.country, DATE_TRUNC(o.created_at, MONTH) AS m, SUM(o.sale_price) AS rev
    FROM db.s.orders o
    JOIN db.s.users u ON o.user_id = u.id
    WHERE o.status = 'complete'
    GROUP BY 1, 2
    """
    res = parse_sql_to_lookml(sql=sql, lookml=lkml, dialect="bigquery")
    q = res.queries[0]

    aggs = {a.aggregate_table_name: a for a in q.aggregate_tables}
    assert set(aggs) == {"monthly_rollup", "trigger_partial"}

    mr = aggs["monthly_rollup"]
    assert mr.coverage == "hit_candidate"
    assert mr.missing_query_fields == []
    assert mr.timeframe_granularity == "month"
    assert mr.datagroup_trigger == "orders_datagroup"
    assert mr.increment_key == "created_date"
    assert {(u.field, u.used_in) for u in mr.matched_fields} == {
        ("orders.created_month", "dimensions"),
        ("users.country", "dimensions"),
        ("orders.total_revenue", "measures"),
        ("orders.status", "filters"),
        ("orders.created_date", "increment_key"),
    }

    tp = aggs["trigger_partial"]
    assert tp.coverage == "partial_overlap"
    assert tp.missing_query_fields == ["orders.status"]
    assert tp.sql_trigger_value == "SELECT MAX(o.created_at) FROM db.s.orders o"
    assert ("orders.created", "sql_trigger_value") in {
        (u.field, u.used_in) for u in tp.matched_fields
    }

    eqs = {e.query_name: e for e in q.explore_queries}
    assert set(eqs) == {"exact_summary", "partial_with_pivots"}

    es = eqs["exact_summary"]
    assert es.coverage == "exact"
    assert es.unmatched_explore_query_fields == []
    assert es.missing_query_fields == []
    assert ("orders.total_revenue", "sorts") in {
        (u.field, u.used_in) for u in es.matched_fields
    }

    pwp = eqs["partial_with_pivots"]
    assert pwp.coverage == "partial_overlap"
    assert pwp.unmatched_explore_query_fields == ["users.tier"]
    assert set(pwp.missing_query_fields) == {"orders.created", "orders.status"}

    orders_view = next(v for v in q.views if v.view_name == "orders")
    rev_field = next(f for f in orders_view.fields if f.field_name == "total_revenue")
    assert {a.aggregate_table_name for a in rev_field.aggregate_tables} == {
        "monthly_rollup",
        "trigger_partial",
    }
    assert {e.query_name for e in rev_field.explore_queries} == {
        "exact_summary",
        "partial_with_pivots",
    }


def test_parse_sql_to_lookml_property_level_impact_and_usages():
    from lkr.parse import parse_sql_to_lookml

    lkml = """
datagroup: orders_dg {
  sql_trigger: SELECT MAX(id) FROM db.s.orders ;;
  interval_trigger: "12 hours"
}

explore: orders {
  sql_always_where: ${orders.status} = 'active' ;;
  sql_always_having: ${orders.total_amount} > 0 ;;
  access_filter: {
    field: orders.brand
    user_attribute: brand
  }
  persist_with: orders_dg
  join: users {
    sql_on: ${orders.user_id} = ${users.id} ;;
    sql_where: ${users.active} = 1 ;;
  }
  join: items {
    foreign_key: item_id
  }
}

view: users {
  sql_table_name: db.s.users ;;
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
  }
  dimension: active {
    type: number
    sql: ${TABLE}.active ;;
  }
}

view: items {
  sql_table_name: db.s.items ;;
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
  }
}

view: orders {
  sql_table_name: db.s.orders ;;
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
  }
  dimension: user_id {
    type: number
    sql: ${TABLE}.user_id ;;
  }
  dimension: item_id {
    type: number
    sql: ${TABLE}.item_id ;;
  }
  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }
  dimension: brand {
    type: string
    sql: ${TABLE}.brand ;;
  }
  dimension: status_label {
    case: {
      when: {
        sql: ${TABLE}.status = 'open' ;;
        label: "Open"
      }
      else: "Closed"
    }
  }
  dimension_group: duration_group {
    type: duration
    sql_start: ${TABLE}.created_at ;;
    sql_end: ${TABLE}.delivered_at ;;
  }
  measure: total_amount {
    type: sum
    sql: ${TABLE}.amount ;;
  }
  measure: active_count {
    type: count
    filters: [status: "active"]
  }
  measure: deal_tier {
    case: {
      when: {
        sql: ${TABLE}.amount > 100 ;;
        label: "Big"
      }
    }
  }
  filter: date_filter {
    type: string
    sql: ${TABLE}.created_at > '2020-01-01' ;;
  }
}

view: summary {
  derived_table: {
    sql: SELECT * FROM db.s.orders ;;
    sql_trigger_value: SELECT MAX(id) FROM db.s.orders ;;
  }
  dimension: id {
    type: number
    sql: ${TABLE}.id ;;
  }
}
"""
    sql = "SELECT id, user_id, item_id, status, brand, created_at, delivered_at, amount FROM db.s.orders"
    res = parse_sql_to_lookml(sql=sql, lookml=lkml, dialect="bigquery")
    q = res.queries[0]
    orders_vm = next(v for v in q.views if v.view_name == "orders")
    f_map = {f.field_name: f for f in orders_vm.fields}

    assert f_map["status_label"].matched_property == "dimension.case.when.sql"
    assert (
        f_map["status_label"].property_path
        == "view.orders.dimension.status_label.case.when.sql"
    )
    assert f_map["status_label"].expression == "${TABLE}.status = 'open'"
    assert f_map["status_label"].sql_location is not None

    assert f_map["deal_tier"].matched_property == "measure.case.when.sql"
    assert (
        f_map["deal_tier"].property_path
        == "view.orders.measure.deal_tier.case.when.sql"
    )

    assert f_map["active_count"].matched_property == "measure.filters"
    assert (
        f_map["active_count"].property_path
        == "view.orders.measure.active_count.filters"
    )
    assert "orders.status" in f_map["active_count"].via

    dur_f = f_map["duration_group"]
    assert dur_f.matched_property in (
        "dimension_group.sql_start",
        "dimension_group.sql_end",
    )

    assert f_map["date_filter"].matched_property == "filter.sql"

    u_props = {u.matched_property for u in q.usages}
    assert "join.sql_on" in u_props
    assert "join.foreign_key" in u_props
    assert "explore.sql_always_where" in u_props
    assert "explore.sql_always_having" in u_props
    assert "explore.access_filter" in u_props
    assert "datagroup.sql_trigger" in u_props
    assert "datagroup.interval_trigger" in u_props
    assert "derived_table.sql_trigger_value" in u_props

    sql_on_u = next(u for u in q.usages if u.matched_property == "join.sql_on")
    assert sql_on_u.property_path == "explore.orders.join.users.sql_on"
    assert sql_on_u.join_name == "users"

    where_u = next(
        u for u in q.usages if u.matched_property == "explore.sql_always_where"
    )
    assert where_u.property_path == "explore.orders.sql_always_where"

    dg_u = next(u for u in q.usages if u.matched_property == "datagroup.sql_trigger")
    assert dg_u.property_path == "datagroup.orders_dg.sql_trigger"
    assert dg_u.datagroup_name == "orders_dg"


def test_parse_lookml_separate_test_file(tmp_path: Path):
    model_file = tmp_path / "ecommerce.model.lkml"
    model_file.write_text(
        'connection: "test_db"\n'
        'include: "*.view.lkml"\n'
        'include: "tests/**/*.test.lkml"\n'
        "explore: orders {}\n",
        encoding="utf-8",
    )
    view_file = tmp_path / "orders.view.lkml"
    view_file.write_text(
        "view: orders {\n"
        "  sql_table_name: public.orders ;;\n"
        "  dimension: id { primary_key: yes }\n"
        "  measure: count { type: count }\n"
        "}\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests" / "silver"
    tests_dir.mkdir(parents=True)
    test_file = tests_dir / "orders.test.lkml"
    test_file.write_text(
        "test: orders_pk_is_unique {\n"
        "  explore_source: orders {\n"
        "    column: id { field: orders.id }\n"
        "    column: count { field: orders.count }\n"
        "  }\n"
        "  assert: count_is_one {\n"
        "    expression: ${orders.count} = 1 ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    proj = parse_lookml(path=tmp_path)
    assert proj.model is not None and "ecommerce" in proj.model
    m = proj.model["ecommerce"]
    assert m.test is not None and "orders_pk_is_unique" in m.test
    assert isinstance(proj.file, LookmlFile) and proj.file.test is not None
    assert any("orders" in k for k in proj.file.test)

    from lkr.parse.sql_to_lookml import parse_sql_to_lookml

    res = parse_sql_to_lookml(
        sql="SELECT id, count FROM public.orders",
        path=tmp_path,
        sql_schema="public",
    )
    q = res.queries[0]
    test_names = {t.test_name for t in q.tests}
    assert "orders_pk_is_unique" in test_names


def test_parse_sql_to_lookml_liquid_table_and_field_sql():
    from lkr.parse.sql_to_lookml import parse_sql_to_lookml

    lkml = """
explore: share_of_net_return {}

view: order_items {
  sql_table_name: `db.ecomm.order_items` ;;
  dimension_group: created {
    type: time
    timeframes: [raw, date, month]
    sql: ${TABLE}.created_at ;;
  }
  dimension_group: returned {
    type: time
    timeframes: [raw, date]
    sql: ${TABLE}.returned_at ;;
  }
  dimension: sale_price {
    type: number
    sql: ${TABLE}.sale_price ;;
  }
  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }
}

view: share_of_net_return {
  extends: [order_items]
  derived_table: {
    sql:
      SELECT
        'orders' as tbl,
        {{ returned_raw._sql }} dt,
        {{ sale_price._sql }} as amount
      FROM ${order_items.SQL_TABLE_NAME} as {{ _table }}
      UNION ALL
      SELECT
        'reversals' as tbl,
        {{ created_date._sql }} dt,
        {{ sale_price._sql }}*-1 as amount
      FROM ${order_items.SQL_TABLE_NAME} as {{ _table }}
      WHERE {{ status._sql }} IN ('Returned', 'Cancelled')
    ;;
  }
  dimension_group: dt {
    type: time
    timeframes: [raw, date]
    sql: ${TABLE}.dt ;;
  }
  dimension: tbl { hidden: yes }
  dimension: amount {
    type: number
    sql: ${TABLE}.amount ;;
  }
  measure: daily_net_return {
    type: sum
    sql: ${amount} ;;
  }
  measure: daily_revenue {
    type: sum
    sql: ${amount} ;;
    filters: [tbl: "orders"]
  }
  measure: daily_net_return_rate {
    type: number
    sql: ${daily_net_return} / NULLIF(${daily_revenue}, 0) ;;
  }
}
"""
    res = parse_sql_to_lookml(
        sql="SELECT returned_at, created_at, sale_price, status FROM `db.ecomm.order_items`",
        lookml=lkml,
        dialect="bigquery",
    )
    q = res.queries[0]
    snr_vm = next(v for v in q.views if v.view_name == "share_of_net_return")
    f_by_name = {f.field_name: f for f in snr_vm.fields}
    assert "amount" in f_by_name
    assert f_by_name["amount"].via == ["order_items.sale_price"]
    assert "dt" in f_by_name
    assert "daily_net_return_rate" in f_by_name
    assert "share_of_net_return.amount" in f_by_name["daily_net_return_rate"].via


def test_parse_lookml_constants_quoted_unquoted_and_positions(tmp_path: Path):
    (tmp_path / "manifest.lkml").write_text(
        'project_name: "const_proj"\n'
        "constant: conn_name {\n"
        '  value: "bigquery_prod"\n'
        "  export: override_required\n"
        "}\n"
        "constant: bq_dataset {\n"
        '  value: "analytics_prod.ecomm"\n'
        "  export: override_optional\n"
        "}\n"
        "constant: dg_name {\n"
        '  value: "daily_dg"\n'
        "}\n"
        "constant: base_view_name {\n"
        '  value: "base_entity"\n'
        "}\n"
        "constant: is_secret_hidden {\n"
        '  value: "yes"\n'
        "}\n"
        "constant: col_prefix {\n"
        '  value: "order"\n'
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "orders.view.lkml").write_text(
        "view: base_entity {\n"
        "  extension: required\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.@{col_prefix}_id ;;\n"
        "  }\n"
        "}\n"
        "view: orders {\n"
        "  extends: [@{base_view_name}]\n"
        "  sql_table_name: `@{bq_dataset}.orders` ;;\n"
        '  label: "Orders (@{bq_dataset})"\n'
        "  dimension: secret_code {\n"
        "    hidden: @{is_secret_hidden}\n"
        "    type: string\n"
        "    sql: ${TABLE}.secret_code ;;\n"
        "  }\n"
        "  dimension: status {\n"
        "    type: string\n"
        "    sql: ${TABLE}.status ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "ecomm.model.lkml").write_text(
        'connection: "@{conn_name}"\n'
        'include: "*.view.lkml"\n'
        "datagroup: daily_dg {\n"
        "  sql_trigger: SELECT CURRENT_DATE() ;;\n"
        "}\n"
        "explore: orders {\n"
        "  persist_with: @{dg_name}\n"
        "}\n",
        encoding="utf-8",
    )

    proj = parse_lookml(path=tmp_path)
    assert proj.errors is None
    assert proj.manifest is not None
    assert proj.manifest.project_name == "const_proj"
    assert proj.manifest.constant is not None
    assert proj.manifest.constant["conn_name"].value == "bigquery_prod"
    assert proj.manifest.constant["conn_name"].export == "override_required"
    assert proj.manifest.constant["bq_dataset"].export == "override_optional"

    assert proj.model is not None
    model = proj.model["ecomm"]
    assert model.connection == "bigquery_prod"
    assert model.explore is not None
    exp = model.explore["orders"]
    assert isinstance(exp, LookmlExplore)
    assert exp.persist_with == "daily_dg"

    assert model.view is not None
    orders_v = model.view["orders"]
    assert isinstance(orders_v, LookmlView)
    assert (orders_v.sql_table_name or "").strip() == "`analytics_prod.ecomm.orders`"
    assert orders_v.label == "Orders (analytics_prod.ecomm)"
    assert orders_v.dimension is not None
    assert orders_v.dimension["id"].primary_key is True
    assert (orders_v.dimension["id"].sql or "").strip() == "${TABLE}.order_id"
    assert orders_v.dimension["secret_code"].hidden is True
    assert (orders_v.dimension["status"].sql or "").strip() == "${TABLE}.status"

    # Verify source positions remain exact despite @{bq_dataset} expanding in length
    assert proj.positions is not None
    v_pos = proj.positions.file["orders.view"]["view"]["orders"]
    # dimension: status starts at 0-indexed line 17 (1-indexed line 18)
    assert v_pos["dimension"]["status"]["$p"][0] == 17


def test_parse_lookml_manifest_dependency_override_constants(tmp_path: Path):
    from lkr.parse import LookmlLocalDependency, LookmlRemoteDependency

    imp_dir = tmp_path / "imported_projects" / "core_hub"
    imp_dir.mkdir(parents=True)
    (imp_dir / "manifest.lkml").write_text(
        'project_name: "core_hub"\n'
        "constant: schema_name {\n"
        '  value: "default_core_schema"\n'
        "  export: override_optional\n"
        "}\n"
        "constant: conn {\n"
        '  value: "default_conn"\n'
        "  export: override_required\n"
        "}\n",
        encoding="utf-8",
    )
    (imp_dir / "users.view.lkml").write_text(
        "view: users_core {\n"
        "  sql_table_name: @{schema_name}.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    (tmp_path / "manifest.lkml").write_text(
        'project_name: "spoke_project"\n'
        "constant: parent_conn {\n"
        '  value: "spoke_bq_conn"\n'
        "}\n"
        "local_dependency: {\n"
        '  project: "core_hub"\n'
        "  override_constant: schema_name {\n"
        '    value: "spoke_prod_schema"\n'
        "  }\n"
        "  override_constant: conn {\n"
        '    value: "@{parent_conn}"\n'
        "  }\n"
        "}\n"
        "remote_dependency: shared_ext {\n"
        '  url: "https://github.com/example/shared_ext.git"\n'
        '  ref: "main"\n'
        "  override_constant: ext_table {\n"
        '    value: "spoke_prod_schema.events"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "spoke.model.lkml").write_text(
        'connection: "@{conn}"\n'
        'include: "/imported_projects/core_hub/*.view.lkml"\n'
        "explore: users_core {}\n",
        encoding="utf-8",
    )

    proj = parse_lookml(path=tmp_path)
    # Root manifest is preserved (not overwritten by imported_projects/core_hub/manifest.lkml)
    assert proj.manifest is not None
    assert proj.manifest.project_name == "spoke_project"
    assert isinstance(proj.manifest.local_dependency, LookmlLocalDependency)
    assert proj.manifest.local_dependency.project == "core_hub"
    assert proj.manifest.local_dependency.override_constant is not None
    assert (
        proj.manifest.local_dependency.override_constant["schema_name"].value
        == "spoke_prod_schema"
    )
    assert isinstance(proj.manifest.remote_dependency, dict)
    assert "shared_ext" in proj.manifest.remote_dependency
    assert isinstance(
        proj.manifest.remote_dependency["shared_ext"], LookmlRemoteDependency
    )

    assert proj.model is not None
    m = proj.model["spoke"]
    assert m.connection == "spoke_bq_conn"
    assert m.view is not None
    users_v = m.view["users_core"]
    assert isinstance(users_v, LookmlView)
    assert (users_v.sql_table_name or "").strip() == "spoke_prod_schema.users"


def test_parse_lookml_manifest_autodiscovery_and_cli_overrides(tmp_path: Path):
    from lkr.parse import (
        parse_lookml_database_compare,
        parse_lookml_to_api,
        parse_sql_to_lookml,
    )

    (tmp_path / "manifest.lkml").write_text(
        'project_name: "auto_proj"\n'
        "constant: target_schema {\n"
        '  value: "manifest_schema"\n'
        "  export: override_optional\n"
        "}\n"
        "constant: target_conn {\n"
        '  value: "manifest_conn"\n'
        "}\n",
        encoding="utf-8",
    )
    views_dir = tmp_path / "views"
    views_dir.mkdir()
    view_file = views_dir / "items.view.lkml"
    view_file.write_text(
        "view: items {\n"
        "  sql_table_name: @{target_schema}.items ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.model.lkml").write_text(
        'connection: "@{target_conn}"\n'
        'include: "/views/*.view.lkml"\n'
        "explore: items {}\n",
        encoding="utf-8",
    )

    # 1. Single --file inside a subdirectory auto-discovers ../manifest.lkml
    proj_from_file = parse_lookml(file=view_file)
    assert proj_from_file.model is not None
    assert proj_from_file.model["inline"].view is not None
    v_from_file = proj_from_file.model["inline"].view["items"]
    assert isinstance(v_from_file, LookmlView)
    assert (v_from_file.sql_table_name or "").strip() == "manifest_schema.items"

    # 2. Python constants override takes highest precedence
    proj_override = parse_lookml(
        file=view_file, constants={"target_schema": "override_schema"}
    )
    assert proj_override.model is not None
    assert proj_override.model["inline"].view is not None
    v_override = proj_override.model["inline"].view["items"]
    assert isinstance(v_override, LookmlView)
    assert (v_override.sql_table_name or "").strip() == "override_schema.items"

    # 3. sql-lookml-compare resolves constants from manifest & CLI --constant override
    sql_cmp_default = parse_sql_to_lookml(
        sql="SELECT id FROM manifest_schema.items",
        lookml_file=view_file,
    )
    assert len(sql_cmp_default.queries[0].views) == 1
    assert sql_cmp_default.queries[0].views[0].view_name == "items"

    cli_sql_cmp = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--sql",
            "SELECT id FROM custom_cli_schema.items",
            "--lookml-file",
            str(view_file),
            "--constant",
            "target_schema=custom_cli_schema",
        ],
    )
    assert cli_sql_cmp.exit_code == 0
    cmp_payload = json.loads(cli_sql_cmp.stdout)
    assert len(cmp_payload["queries"][0]["views"]) == 1
    assert (
        cmp_payload["queries"][0]["views"][0]["sql_table"] == "custom_cli_schema.items"
    )

    # 4. lookml-to-api resolves constants and CLI --constant override
    api_res = parse_lookml_to_api(
        path=tmp_path,
        constants={"target_conn": "override_conn", "target_schema": "override_schema"},
    )
    assert api_res.all_lookml_models[0].allowed_db_connection_names == ["override_conn"]
    assert (
        api_res.lookml_model_explores["main::items"].sql_table_name
        == "override_schema.items  AS items"
    )

    cli_api = runner.invoke(
        app,
        [
            "parse",
            "lookml-to-api",
            "--path",
            str(tmp_path),
            "-C",
            "target_conn=cli_conn",
            "-C",
            "target_schema=cli_schema",
        ],
    )
    assert cli_api.exit_code == 0
    api_payload = json.loads(cli_api.stdout)
    assert api_payload["all_lookml_models"][0]["allowed_db_connection_names"] == [
        "cli_conn"
    ]
    assert (
        api_payload["lookml_model_explores"]["main::items"]["sql_table_name"]
        == "cli_schema.items  AS items"
    )

    # 5. lookml-database-compare resolves constants and CLI --constant override
    db_cmp = parse_lookml_database_compare(
        path=tmp_path,
        columns=True,
        constants={"target_schema": "db_cmp_schema", "target_conn": "db_cmp_conn"},
    )
    assert len(db_cmp.tables) == 1
    assert db_cmp.tables[0].table == "db_cmp_schema.items"
    assert db_cmp.tables[0].schema_ == "db_cmp_schema"
    assert db_cmp.tables[0].connection == "db_cmp_conn"


def test_lookml_to_api_duplicate_field_logic_and_count_star_matching(tmp_path: Path):
    from typer.testing import CliRunner

    from lkr.main import app
    from lkr.parse import lookml_to_lookml_model_explore, parse_sql_to_lookml

    runner = CliRunner()

    dup_lkml = """
    view: order_items {
      sql_table_name: `looker-private-demo.ecomm.order_items` ;;
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: sale_price {
        type: number
        sql: ${TABLE}.sale_price ;;
      }
      dimension: price_alias {
        type: number
        sql: ${sale_price} ;;
      }
      measure: count {
        type: count
      }
      measure: total_line_items_sold {
        type: count
        label: "Total Line Items Sold"
      }
      measure: total_revenue {
        type: sum
        sql: ${TABLE}.sale_price ;;
      }
      measure: gross_sales {
        type: sum
        sql: ${sale_price} ;;
      }
    }
    explore: order_items {}
    """
    exp = lookml_to_lookml_model_explore("inline", "order_items", lookml=dup_lkml)
    assert exp.errors is not None
    error_msgs = [e["message"] for e in exp.errors]
    assert any(
        "order_items.count" in m and "order_items.total_line_items_sold" in m
        for m in error_msgs
    )
    assert any(
        "order_items.total_revenue" in m and "order_items.gross_sales" in m
        for m in error_msgs
    )
    assert any(
        "order_items.sale_price" in m and "order_items.price_alias" in m
        for m in error_msgs
    )

    (tmp_path / "dup.model.lkml").write_text(
        'connection: "c"\n' + dup_lkml, encoding="utf-8"
    )
    cli_fail = runner.invoke(
        app,
        ["parse", "lookml-to-api", "--path", str(tmp_path), "--validate"],
    )
    assert cli_fail.exit_code == 1

    clean_lkml = """
    view: order_items {
      sql_table_name: `looker-private-demo.ecomm.order_items` ;;
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: status {
        type: string
        sql: ${TABLE}.status ;;
      }
      measure: count {
        type: count
      }
    }
    explore: order_items {
      query: by_status {
        dimensions: [status]
        measures: [count]
      }
    }
    """
    (tmp_path / "dup.model.lkml").write_text(
        'connection: "c"\n' + clean_lkml, encoding="utf-8"
    )
    cli_ok = runner.invoke(
        app,
        ["parse", "lookml-to-api", "--path", str(tmp_path), "--validate"],
    )
    assert cli_ok.exit_code == 0

    cmp_res = parse_sql_to_lookml(
        sql="SELECT status, COUNT(*) AS total_line_items_sold FROM `looker-private-demo.ecomm.order_items` GROUP BY 1",
        path=tmp_path,
    )
    matched_fields = {
        (f.field_name, f.field_type) for f in cmp_res.queries[0].views[0].fields
    }
    assert ("count", "measure") in matched_fields
    assert ("status", "dimension") in matched_fields
    eq = cmp_res.queries[0].explore_queries[0]
    assert eq.coverage == "exact"


def test_parse_lookml_to_api_exclude_hidden_flag(tmp_path: Path):
    from typer.testing import CliRunner

    from lkr.main import app

    runner = CliRunner()
    lkml = """
    view: orders {
      sql_table_name: ecomm.orders ;;
      dimension: id {
        primary_key: yes
        hidden: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: status {
        type: string
        sql: ${TABLE}.status ;;
      }
      dimension_group: created {
        type: time
        timeframes: [raw, date, month]
        sql: ${TABLE}.created_at ;;
      }
      dimension: store_loc {
        type: location
        sql_latitude: ${TABLE}.lat ;;
        sql_longitude: ${TABLE}.lon ;;
      }
      measure: count {
        type: count
      }
      measure: internal_cost {
        type: sum
        hidden: yes
        sql: ${TABLE}.cost ;;
      }
    }
    explore: orders_base {
      view_name: orders
      hidden: yes
    }
    explore: orders {
      extends: [orders_base]
      view_name: orders
      hidden: no
    }
    """
    (tmp_path / "shop.model.lkml").write_text(
        'connection: "bq"\n' + lkml, encoding="utf-8"
    )

    res = runner.invoke(
        app,
        ["parse", "lookml-to-api", "--path", str(tmp_path), "--exclude-hidden"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)

    assert [e["name"] for e in payload["all_lookml_models"][0]["explores"]] == [
        "orders"
    ]
    assert list(payload["lookml_model_explores"].keys()) == ["shop::orders"]

    fields = payload["lookml_model_explores"]["shop::orders"]["fields"]
    dim_names = [d["name"] for d in fields["dimensions"]]
    meas_names = [m["name"] for m in fields["measures"]]

    assert "orders.id" not in dim_names
    assert "orders.created_raw" not in dim_names
    assert {
        "orders.status",
        "orders.created_date",
        "orders.created_month",
        "orders.store_loc",
    } <= set(dim_names)
    assert meas_names == ["orders.count"]


def test_lookml_to_api_alias_expansion_and_collision_validation(tmp_path: Path):
    from typer.testing import CliRunner

    from lkr.main import app
    from lkr.parse import lookml_to_lookml_model_explore

    runner = CliRunner()
    valid_lkml = """
    view: orders {
      sql_table_name: ecomm.orders ;;
      dimension_group: ordered {
        alias: [created]
        type: time
        timeframes: [date, yesno]
        sql: ${TABLE}.created_at ;;
      }
      dimension_group: ship_lag {
        alias: [wait]
        type: duration
        intervals: [day]
        sql_start: ${TABLE}.created_at ;;
        sql_end: ${TABLE}.shipped_at ;;
      }
      measure: last_order {
        alias: [latest]
        type: time
        timeframes: [date]
        sql: MAX(${TABLE}.created_at) ;;
      }
      filter: cohort_filter {
        alias: [old_cohort]
        type: string
      }
      parameter: grain {
        alias: [old_grain]
        type: unquoted
      }
    }
    explore: orders {}
    """
    exp = lookml_to_lookml_model_explore("inline", "orders", lookml=valid_lkml)
    assert exp.errors is None
    assert {(a.name, a.value) for a in exp.aliases} == {
        ("created_date", "orders.ordered_date"),
        ("created", "orders.ordered"),
        ("days_wait", "orders.days_ship_lag"),
        ("latest_date", "orders.last_order_date"),
        ("old_cohort", "orders.cohort_filter"),
        ("old_grain", "orders.grain"),
    }

    collide_lkml = """
    view: orders {
      sql_table_name: ecomm.orders ;;
      dimension: status { sql: ${TABLE}.status ;; }
      dimension: state { alias: [status] sql: ${TABLE}.state ;; }
      measure: rev_a { alias: [rev] type: sum sql: ${TABLE}.a ;; }
      measure: rev_b { alias: [rev] type: sum sql: ${TABLE}.b ;; }
    }
    explore: orders {}
    """
    (tmp_path / "m.model.lkml").write_text(
        'connection: "bq"\n' + collide_lkml, encoding="utf-8"
    )
    res = runner.invoke(
        app, ["parse", "lookml-to-api", "--path", str(tmp_path), "--validate"]
    )
    assert res.exit_code == 1
    bad_exp = lookml_to_lookml_model_explore("m", "orders", path=tmp_path)
    assert bad_exp.errors is not None
    by_alias = {e["alias"]: e for e in bad_exp.errors if e["type"] == "alias_collision"}
    assert by_alias["orders.status"]["fields"] == ["orders.state", "orders.status"]
    assert by_alias["orders.rev"]["fields"] == ["orders.rev_a", "orders.rev_b"]


def test_count_pk_coverage_and_raw_sql_aggregate_validation(tmp_path: Path):
    from typer.testing import CliRunner

    from lkr.main import app
    from lkr.parse import lookml_to_lookml_model_explore, parse_sql_to_lookml

    runner = CliRunner()
    lkml = """
    view: orders {
      sql_table_name: `bigquery-public-data.thelook_ecommerce.orders` ;;
      dimension: order_id {
        primary_key: yes
        type: number
        sql: ${TABLE}.order_id ;;
      }
      dimension: num_of_item {
        type: number
        sql: ${TABLE}.num_of_item ;;
      }
      dimension: shipped_at {
        type: string
        sql: ${TABLE}.shipped_at ;;
      }
      measure: count {
        type: count
      }
      measure: p99_items {
        type: percentile
        percentile: 99
        sql: ${num_of_item} ;;
      }
      measure: approx_buyers {
        type: number
        sql: APPROX_COUNT_DISTINCT(${order_id}) ;;
      }
      measure: _num_of_item_sum {
        hidden: yes
        type: sum
        sql: ${num_of_item} ;;
      }
      measure: _num_of_item_sum_of_squares {
        hidden: yes
        type: sum
        sql: POWER(${num_of_item}, 2) ;;
      }
      measure: stddev_items {
        type: number
        sql: SQRT(GREATEST(${_num_of_item_sum_of_squares} - (POWER(${_num_of_item_sum}, 2) / NULLIF(${count}, 0)), 0) / NULLIF(${count} - 1, 0)) ;;
      }
    }
    view: order_items {
      sql_table_name: `bigquery-public-data.thelook_ecommerce.order_items` ;;
      dimension: id {
        primary_key: yes
        type: number
        sql: ${TABLE}.id ;;
      }
      dimension: order_id {
        type: number
        sql: ${TABLE}.order_id ;;
      }
      dimension: status {
        type: string
        sql: ${TABLE}.status ;;
      }
      measure: count {
        type: count
      }
    }
    explore: orders {
      join: order_items {
        type: left_outer
        relationship: one_to_many
        sql_on: ${orders.order_id} = ${order_items.order_id} ;;
      }
      query: order_volume_by_basket_size {
        dimensions: [orders.num_of_item]
        measures: [orders.count]
      }
      query: orders_by_item_status {
        dimensions: [order_items.status]
        measures: [orders.count]
      }
    }
    """
    (tmp_path / "shop.model.lkml").write_text(
        'connection: "bq"\n' + lkml, encoding="utf-8"
    )

    # 1. COUNT(pk) -> exact coverage on orders.count without requiring orders.order_id dimension
    r_pk = parse_sql_to_lookml(
        sql="SELECT num_of_item AS basket_size, COUNT(order_id) AS orders_at_this_size FROM `bigquery-public-data.thelook_ecommerce.orders` GROUP BY 1",
        path=tmp_path,
    )
    eq_pk = next(
        q
        for q in r_pk.queries[0].explore_queries
        if q.query_name == "order_volume_by_basket_size"
    )
    assert eq_pk.coverage == "exact"
    assert eq_pk.unmatched_explore_query_fields == []
    assert eq_pk.missing_query_fields == []

    # 2. COUNT(DISTINCT o.order_id) across join -> exact coverage scoped to orders.count
    r_dist = parse_sql_to_lookml(
        sql="SELECT oi.status, COUNT(DISTINCT o.order_id) FROM `bigquery-public-data.thelook_ecommerce.order_items` oi JOIN `bigquery-public-data.thelook_ecommerce.orders` o ON oi.order_id = o.order_id GROUP BY 1",
        path=tmp_path,
    )
    eq_dist = next(
        q
        for q in r_dist.queries[0].explore_queries
        if q.query_name == "orders_by_item_status"
    )
    assert eq_dist.coverage == "exact"
    assert eq_dist.missing_query_fields == []

    # 3. pk used outside COUNT(...) -> orders.order_id still required
    r_outside = parse_sql_to_lookml(
        sql="SELECT num_of_item, COUNT(order_id) FROM `bigquery-public-data.thelook_ecommerce.orders` WHERE order_id > 100 GROUP BY 1",
        path=tmp_path,
    )
    eq_out = next(
        q
        for q in r_outside.queries[0].explore_queries
        if q.query_name == "order_volume_by_basket_size"
    )
    assert eq_out.coverage == "partial_overlap"
    assert eq_out.missing_query_fields == ["orders.order_id"]

    # 4. COUNT(non_pk_col) -> does not map to unfiltered orders.count
    r_non_pk = parse_sql_to_lookml(
        sql="SELECT COUNT(shipped_at) FROM `bigquery-public-data.thelook_ecommerce.orders`",
        path=tmp_path,
    )
    assert ("count", "measure") not in {
        (f.field_name, f.field_type) for f in r_non_pk.queries[0].views[0].fields
    }

    # 5. Clean symmetric STDDEV + native percentile + APPROX_COUNT_DISTINCT pass --validate
    assert (
        runner.invoke(
            app, ["parse", "lookml-to-api", "--path", str(tmp_path), "--validate"]
        ).exit_code
        == 0
    )

    # 6. Raw SQL percentile/stddev/variance in type: number fail --validate
    bad_lkml = """
    view: v {
      sql_table_name: t ;;
      dimension: x { type: number sql: ${TABLE}.x ;; }
      measure: m_std { type: number sql: STDDEV(${x}) ;; }
      measure: m_var { type: number sql: VAR_POP(${x}) ;; }
      measure: m_pct { type: number sql: PERCENTILE_CONT(${x}, 0.99) OVER() ;; }
      measure: m_pdisc { type: number sql: PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY ${x}) ;; }
      measure: m_approx { type: number sql: APPROX_QUANTILES(${x}, 100)[OFFSET(99)] ;; }
      measure: m_med { type: number sql: MEDIAN(${x}) ;; }
    }
    explore: v {}
    """
    (tmp_path / "bad.model.lkml").write_text(
        'connection: "bq"\n' + bad_lkml, encoding="utf-8"
    )
    bad_exp = lookml_to_lookml_model_explore("bad", "v", path=tmp_path)
    assert bad_exp.errors is not None
    flagged = {
        e["field"]: e["functions"]
        for e in bad_exp.errors
        if e["type"] == "raw_sql_aggregate"
    }
    assert set(flagged) == {
        "v.m_std",
        "v.m_var",
        "v.m_pct",
        "v.m_pdisc",
        "v.m_approx",
        "v.m_med",
    }
    assert (
        runner.invoke(
            app,
            [
                "parse",
                "lookml-to-api",
                "--path",
                str(tmp_path),
                "-m",
                "bad",
                "--validate",
            ],
        ).exit_code
        == 1
    )

    # 7. '* 100' scaling paired with literal '"%"' value_format fails --validate (direct + indirect via dimension),
    #    while unscaled ratio + value_format_name: percent_2 passes
    pct_lkml = r"""
    view: products {
      sql_table_name: products ;;
      dimension: cost { type: number sql: ${TABLE}.cost ;; }
      dimension: retail_price { type: number sql: ${TABLE}.retail_price ;; }
      dimension: markup_ratio {
        type: number
        sql: (${retail_price} - ${cost}) / NULLIF(${cost}, 0) ;;
        value_format_name: percent_2
      }
      measure: avg_markup_ratio {
        type: average
        sql: ${markup_ratio} ;;
        value_format_name: percent_2
      }
      dimension: markup_greed_pct {
        hidden: yes
        type: number
        sql: ((${retail_price} - ${cost}) / NULLIF(${cost}, 0)) * 100 ;;
        value_format: "0.00\"%\""
      }
      measure: avg_markup_greed_pct {
        type: average
        sql: ${markup_greed_pct} ;;
        value_format: "0.00\"%\""
      }
      measure: direct_pct_bad {
        type: number
        sql: 100.0 * ${avg_markup_ratio} ;;
        value_format: "0.0\\%"
      }
    }
    explore: products {}
    """
    (tmp_path / "pct.model.lkml").write_text(
        'connection: "bq"\n' + pct_lkml, encoding="utf-8"
    )
    pct_exp = lookml_to_lookml_model_explore("pct", "products", path=tmp_path)
    assert pct_exp.errors is not None
    pct_flagged = {
        e["field"] for e in pct_exp.errors if e["type"] == "percent_scaled_value_format"
    }
    assert pct_flagged == {
        "products.markup_greed_pct",
        "products.avg_markup_greed_pct",
        "products.direct_pct_bad",
    }
    assert (
        runner.invoke(
            app,
            [
                "parse",
                "lookml-to-api",
                "--path",
                str(tmp_path),
                "-m",
                "pct",
                "--exclude-hidden",
                "--validate",
            ],
        ).exit_code
        == 1
    )

    # 8. --base-path suppresses pre-existing baseline errors while failing on net-new errors
    base_dir = tmp_path / "base_pct"
    base_dir.mkdir()
    (base_dir / "pct.model.lkml").write_text(
        'connection: "bq"\n' + pct_lkml, encoding="utf-8"
    )
    assert (
        runner.invoke(
            app,
            [
                "parse",
                "lookml-to-api",
                "--path",
                str(tmp_path),
                "--base-path",
                str(base_dir),
                "-m",
                "pct",
                "--validate",
            ],
        ).exit_code
        == 0
    )
    head_dir = tmp_path / "head_pct"
    head_dir.mkdir()
    (head_dir / "pct.model.lkml").write_text(
        'connection: "bq"\n'
        + pct_lkml.replace(
            "explore: products {}",
            r'view: +products { measure: new_bad_pct { type: number sql: 100 * ${avg_markup_ratio} ;; value_format: "0.00\"%\"" } }'
            + "\nexplore: products {}",
        ),
        encoding="utf-8",
    )
    assert (
        runner.invoke(
            app,
            [
                "parse",
                "lookml-to-api",
                "--path",
                str(head_dir),
                "--base-path",
                str(base_dir),
                "-m",
                "pct",
                "--validate",
            ],
        ).exit_code
        == 1
    )

    # 9. sql-lookml-compare --offline skips live Looker sandbox lookups
    import pytest

    import lkr.parse.sql_to_lookml as s2l

    def _fail(*_a, **_kw):
        raise AssertionError("live lookup called")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(s2l, "_fetch_table_columns_sandbox", _fail)
        assert (
            runner.invoke(
                app,
                [
                    "parse",
                    "sql-lookml-compare",
                    "--sql",
                    "SELECT num_of_item FROM `bigquery-public-data.thelook_ecommerce.orders`",
                    "--path",
                    str(tmp_path),
                    "--offline",
                ],
            ).exit_code
            == 0
        )


def test_sql_lookml_compare_refinement_file_attribution_and_compact(tmp_path: Path):
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    runner = CliRunner()
    bronze = tmp_path / "bronze"
    bronze.mkdir()
    (bronze / "orders.view.lkml").write_text(
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }\n"
        "}\n",
        encoding="utf-8",
    )
    (bronze / "orders.refinement.lkml").write_text(
        'include: "orders.view.lkml"\n'
        "view: +orders {\n"
        "  measure: total_revenue {\n"
        "    type: sum\n"
        "    sql: ${sale_price} ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "shop.model.lkml").write_text(
        'connection: "bq"\ninclude: "/bronze/*.lkml"\nexplore: orders {}\n',
        encoding="utf-8",
    )

    full_res = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--sql",
            "SELECT SUM(sale_price) AS rev FROM `proj.ds.orders`",
            "--path",
            str(tmp_path),
            "--offline",
        ],
    )
    assert full_res.exit_code == 0, full_res.output
    compact_res = runner.invoke(
        app,
        [
            "parse",
            "sql-lookml-compare",
            "--sql",
            "SELECT SUM(sale_price) AS rev FROM `proj.ds.orders`",
            "--path",
            str(tmp_path),
            "--offline",
            "--compact",
        ],
    )
    assert compact_res.exit_code == 0, compact_res.output
    assert len(compact_res.output) < len(full_res.output)

    compact_data = json.loads(compact_res.output)
    q0 = compact_data["queries"][0]
    assert "raw_sql" not in q0.get("parsed_query", {})
    assert "usages" not in q0
    flds = {f["field_name"]: f for f in q0["views"][0]["fields"]}
    rev_fld = flds["total_revenue"]
    assert rev_fld["file"].endswith("bronze/orders.refinement.lkml")
    assert rev_fld["line"] == 3
    assert "position" not in rev_fld
    assert "explores" not in rev_fld


def test_iter3_value_format_validation_compact_explores_and_diff_tests(tmp_path: Path):
    import importlib.util
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    runner = CliRunner()
    (tmp_path / "orders.view.lkml").write_text(
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: status { type: string sql: ${TABLE}.status ;; }\n"
        "  dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }\n"
        "  measure: count { type: count }\n"
        '  measure: cancelled_orders { type: count filters: [status: "Cancelled"] }\n'
        "  measure: ratio_ok { type: number sql: ${sale_price} ;; value_format_name: decimal_3 }\n"
        "  measure: combo { type: number sql: ${count} + ${ratio_ok} ;; }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "shop.model.lkml").write_text(
        'connection: "bq"\n'
        'include: "*.view.lkml"\n'
        "explore: orders {\n"
        "  query: q_exact { dimensions: [status] measures: [count, ratio_ok] }\n"
        "  query: q_sibling { measures: [count] }\n"
        "  query: q_remorse { measures: [cancelled_orders] }\n"
        "}\n",
        encoding="utf-8",
    )
    assert (
        runner.invoke(
            app, ["parse", "lookml-to-api", "--path", str(tmp_path), "--validate"]
        ).exit_code
        == 0
    )

    comp_qs = json.loads(
        runner.invoke(
            app,
            [
                "parse",
                "sql-lookml-compare",
                "--sql",
                (
                    "SELECT status, COUNT(*) AS c, SUM(sale_price) AS s FROM `proj.ds.orders` GROUP BY 1; "
                    "SELECT COUNT(id) AS c FROM `proj.ds.orders` WHERE status = 'Cancelled'; "
                    "SELECT u.country, o.status, COUNT(*) AS c, SUM(o.sale_price) AS s "
                    "FROM `proj.ds.users` u JOIN `proj.ds.orders` o ON u.id = o.id GROUP BY 1, 2"
                ),
                "--path",
                str(tmp_path),
                "--offline",
                "--compact",
            ],
        ).output
    )["queries"]
    comp, comp_remorse, comp_join = comp_qs[0], comp_qs[1], comp_qs[2]
    assert len(comp["explores"]) == 1
    assert set(comp["explores"][0]["fields"]) >= {"orders.status", "orders.count"}
    assert [eq["query_name"] for eq in comp["explore_queries"]] == ["q_exact"]
    assert [
        (eq["query_name"], eq["coverage"]) for eq in comp_remorse["explore_queries"]
    ] == [("q_remorse", "exact")]
    assert "explore_queries" not in comp_join
    assert (
        comp_join["join_analysis"][0]["sql_join"]
        == "proj.ds.users INNER proj.ds.orders"
    )
    combo_hits = [
        f for f in comp_join["views"][0]["fields"] if f["field_name"] == "combo"
    ]
    assert len(combo_hits) == 1 and set(combo_hits[0]["via"]) >= {
        "orders.count",
        "orders.ratio_ok",
    }

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "orders.view.lkml").write_text(
        "view: orders {\n"
        "  measure: bad_fmt { type: number sql: 1 ;; value_format_name: decimal_9 }\n"
        "}\n",
        encoding="utf-8",
    )
    (bad_dir / "shop.model.lkml").write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\nexplore: orders {}\n',
        encoding="utf-8",
    )
    bad_res = runner.invoke(
        app, ["parse", "lookml-to-api", "--path", str(bad_dir), "--validate"]
    )
    assert bad_res.exit_code == 1

    spec = importlib.util.spec_from_file_location(
        "diff_lookml_tests",
        Path(__file__).resolve().parents[1]
        / "skills/agentic-lookml-workflow/scripts/diff_lookml_tests.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base_lkml = (
        "# comment with { brace }\n"
        "test: legacy_test {\n"
        '  explore_source: events { filters: { field: events.status value: "a{b}" } }\n'
        "  assert: ok { expression: ${events.status} != 'x}y' ;; }\n"
        "}\n"
    )
    head_lkml = (
        base_lkml + "\ntest: new_pr_test {\n"
        "  explore_source: events {}\n"
        "  assert: ok { expression: ${events.count} > 0 ;; }\n"
        "}\n"
    )
    base_blocks = mod.extract_test_blocks(base_lkml)
    head_blocks = mod.extract_test_blocks(head_lkml)
    changed = [n for n, b in head_blocks.items() if base_blocks.get(n) != b]
    assert changed == ["new_pr_test"]


def test_validate_join_all_fields_base_path_cross_explore_and_scratch_ignore(
    tmp_path: Path,
):
    from typer.testing import CliRunner

    from lkr.main import app
    from lkr.parse.lookml import parse_lookml

    runner = CliRunner()

    # 1. ALL_FIELDS* inside join: { fields: [...] } fails offline --validate
    bad_join_lkml = (
        "view: orders { dimension: id { primary_key: yes type: number } dimension: p_id { type: number } }\n"
        "view: products { dimension: id { primary_key: yes type: number } dimension: secret { type: string } }\n"
        "explore: orders {\n"
        "  join: products { sql_on: ${orders.p_id} = ${products.id} ;; fields: [ALL_FIELDS*, -products.secret] }\n"
        "}\n"
    )
    res_bad_join = runner.invoke(
        app, ["parse", "lookml-to-api", "--lookml", bad_join_lkml, "--validate"]
    )
    assert res_bad_join.exit_code == 1

    # 2. --base-path suppresses pre-existing view error when joined onto another explore with -e,
    #    and ignores ./data/<run>/lookml/** scratch trees inside base_path.
    base_dir = tmp_path / "repo"
    cand_dir = base_dir / "data" / "run_1" / "lookml"
    cand_dir.mkdir(parents=True)
    legacy_products = (
        "view: products {\n"
        "  dimension: id { primary_key: yes type: number }\n"
        "  measure: legacy_pct { type: number sql: 100.0 * 1 ;; value_format: '0.00\"%\"' }\n"
        "}\n"
    )
    orders_view = "view: orders { dimension: id { primary_key: yes type: number } dimension: p_id { type: number } }\n"
    (base_dir / "products.view.lkml").write_text(legacy_products, encoding="utf-8")
    (base_dir / "orders.view.lkml").write_text(orders_view, encoding="utf-8")
    (base_dir / "shop.model.lkml").write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\nexplore: orders {}\nexplore: products {}\n',
        encoding="utf-8",
    )
    (cand_dir / "products.view.lkml").write_text(legacy_products, encoding="utf-8")
    (cand_dir / "orders.view.lkml").write_text(orders_view, encoding="utf-8")
    (cand_dir / "shop.model.lkml").write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\n'
        "explore: orders { join: products { sql_on: ${orders.p_id} = ${products.id} ;; relationship: many_to_one } }\n"
        "explore: ghost_only_in_scratch { view_name: orders }\n",
        encoding="utf-8",
    )

    parsed_base = parse_lookml(path=base_dir)
    assert parsed_base.model is not None
    assert "ghost_only_in_scratch" not in (parsed_base.model["shop"].explore or {})

    scoped_res = runner.invoke(
        app,
        [
            "parse",
            "lookml-to-api",
            "--path",
            str(cand_dir),
            "--base-path",
            str(base_dir),
            "-m",
            "shop",
            "-e",
            "orders",
            "--validate",
        ],
    )
    assert scoped_res.exit_code == 0, scoped_res.output


def test_compact_sql_to_lookml_pk_type_hidden_via_and_dedup_tests():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: users {\n"
        "  sql_table_name: `proj.ds.users` ;;\n"
        "  dimension: id { primary_key: yes hidden: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: country { type: string sql: ${TABLE}.country ;; }\n"
        "  measure: count { type: count }\n"
        "}\n"
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: id { primary_key: yes hidden: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "}\n"
        "view: orders_users_fields {\n"
        "  dimension: pk { primary_key: yes hidden: yes sql: CONCAT(${users.id}, '_', ${orders.id}) ;; }\n"
        "}\n"
        "explore: orders {\n"
        "  join: users { sql_on: ${orders.user_id} = ${users.id} ;; relationship: many_to_one }\n"
        "  join: orders_users_fields { sql: ;; relationship: one_to_one }\n"
        "  query: q_count_only { dimensions: [users.country] measures: [users.count] }\n"
        "}\n"
        "test: t_users { explore_source: orders { column: count { field: users.count } } assert: ok { expression: ${users.count} >= 0 ;; } }\n"
    )
    sql = (
        "SELECT u.id, COUNT(*) AS c FROM `proj.ds.users` u LEFT JOIN `proj.ds.orders` o ON u.id = o.user_id GROUP BY 1; "
        "SELECT id FROM `proj.ds.orders`; "
        "SELECT COUNT(id) AS c FROM `proj.ds.users`"
    )
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    q0, q1, q2 = json.loads(res.output)["queries"]
    assert "left_table" not in q0["parsed_query"]["joins"][0]
    assert [v["view_name"] for v in q0["views"]] == ["users", "orders"]
    assert "explore_queries" not in q0
    id_fld = next(f for f in q0["views"][0]["fields"] if f["field_name"] == "id")
    assert id_fld["lookml_type"] == "number" and id_fld["primary_key"] is True
    assert "tests" in q0 and "tests" not in q1 and "tests" not in q2


def test_compact_sql_to_lookml_ndt_count_extends_dedup_and_count_ratio_prune():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: events {\n"
        "  sql_table_name: `proj.ds.events` ;;\n"
        "  dimension: id { primary_key: yes hidden: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension_group: created { type: time timeframes: [raw, year] sql: ${TABLE}.created_at ;; }\n"
        "  dimension: session_id { type: string sql: ${TABLE}.session_id ;; }\n"
        "  dimension: browser { type: string sql: ${TABLE}.browser ;; }\n"
        "  measure: count { type: count }\n"
        '  measure: ie_events { type: count filters: [browser: "IE"] }\n'
        "  measure: ie_share { type: number sql: 1.0 * ${ie_events} / NULLIF(${count}, 0) ;; }\n"
        "}\n"
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "}\n"
        "view: events_orders_fields {\n"
        '  measure: unord_events { type: count_distinct sql: ${events.session_id} ;; filters: [orders.id: "NULL"] }\n'
        "}\n"
        "explore: events_base {\n"
        "  hidden: yes\n"
        "  view_name: events\n"
        "  query: q_base { dimensions: [session_id] measures: [count] sorts: [events.count: desc] }\n"
        "}\n"
        "view: session_facts {\n"
        "  derived_table: { explore_source: events_base { column: session_id {} } }\n"
        "  dimension: session_id { primary_key: yes type: string }\n"
        "  measure: count { type: count }\n"
        "}\n"
        "explore: events {\n"
        "  extends: [events_base]\n"
        "  view_name: events\n"
        "  join: session_facts { sql_on: ${events.session_id} = ${session_facts.session_id} ;; relationship: many_to_one }\n"
        "  join: orders { sql_on: ${events.id} = ${orders.id} ;; relationship: many_to_one }\n"
        "  join: events_orders_fields { sql: ;; relationship: one_to_one }\n"
        "}\n"
    )
    sql = "WITH c1 AS (SELECT session_id, MAX(created_at) AS mc FROM `proj.ds.events` GROUP BY 1) SELECT COUNT(*) AS c FROM c1"
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    q0 = json.loads(res.output)["queries"][0]
    assert "raw_sql" not in q0 and q0["parsed_query"]["ctes"] == ["c1"]
    assert [v["view_name"] for v in q0["views"]] == ["events", "session_facts"]
    ev_by_name = {f["field_name"]: f for f in q0["views"][0]["fields"]}
    assert "ie_share" not in ev_by_name
    assert ev_by_name["created"]["timeframes"] == ["raw", "year"]
    sf_flds = {f["field_name"] for f in q0["views"][1]["fields"]}
    assert "count" in sf_flds
    assert {e["explore_name"] for e in q0["explores"]} == {"events"}
    eqs = [eq for eq in q0["explore_queries"] if eq["query_name"] == "q_base"]
    assert len(eqs) == 1 and eqs[0]["explore_name"] == "events"
    assert eqs[0]["matched_fields"] == ["events.session_id", "events.count"]


def test_compact_sql_to_lookml_pk_count_join_filter_and_precedent_pruning():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: order_items {\n"
        "  sql_table_name: `proj.ds.order_items` ;;\n"
        "  dimension: id { primary_key: yes hidden: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: order_id { type: number sql: ${TABLE}.order_id ;; }\n"
        "  dimension: product_id { type: number sql: ${TABLE}.product_id ;; }\n"
        "  dimension: status { type: string sql: ${TABLE}.status ;; }\n"
        "  dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }\n"
        "  dimension_group: created { type: time timeframes: [raw, hour] sql: ${TABLE}.created_at ;; }\n"
        "  measure: count { type: count }\n"
        "  measure: distinct_orders { type: count_distinct sql: ${order_id} ;; }\n"
        "  measure: total_revenue { type: sum sql: ${sale_price} ;; }\n"
        '  measure: returned_revenue { type: sum sql: ${sale_price} ;; filters: [status: "Returned"] }\n'
        '  measure: night_revenue { type: sum sql: ${sale_price} ;; filters: [created_hour: "0"] }\n'
        "  measure: night_share { type: number sql: 1.0 * ${night_revenue} / NULLIF(${total_revenue}, 0) ;; }\n"
        "}\n"
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: order_id { primary_key: yes type: number sql: ${TABLE}.order_id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "}\n"
        "view: products {\n"
        "  sql_table_name: `proj.ds.products` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: category { type: string sql: ${TABLE}.category ;; }\n"
        "}\n"
        "view: users {\n"
        "  sql_table_name: `proj.ds.users` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "}\n"
        "view: shipments {\n"
        "  sql_table_name: `proj.ds.shipments` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "}\n"
        "view: order_items_products_fields {\n"
        '  measure: sock_rev { type: sum sql: ${order_items.sale_price} ;; filters: [products.category: "Socks"] }\n'
        "  measure: sock_share { type: number sql: 1.0 * ${sock_rev} / NULLIF(${order_items.total_revenue}, 0) ;; }\n"
        "}\n"
        "explore: orders {}\n"
        "explore: products {}\n"
        "explore: shipments {\n"
        "  view_name: shipments\n"
        "  join: order_items { sql_on: ${shipments.id} = ${order_items.id} ;; relationship: one_to_many }\n"
        "}\n"
        "explore: order_items_base {\n"
        "  hidden: yes\n"
        "  view_name: order_items\n"
        "  join: products { sql_on: ${order_items.product_id} = ${products.id} ;; relationship: many_to_one }\n"
        "}\n"
        "explore: order_items {\n"
        "  extends: [order_items_base]\n"
        "  view_name: order_items\n"
        "  join: order_items_products_fields { sql: ;; relationship: one_to_one }\n"
        "}\n"
        "explore: users {\n"
        "  view_name: users\n"
        "  join: orders { sql_on: ${users.id} = ${orders.user_id} ;; relationship: one_to_many }\n"
        "}\n"
    )
    sql = (
        "SELECT p.category, COUNT(oi.id) AS items, "
        "SUM(CASE WHEN oi.status = 'Returned' THEN oi.sale_price ELSE 0 END) AS ret_rev "
        "FROM `proj.ds.order_items` oi "
        "INNER JOIN `proj.ds.orders` o ON oi.order_id = o.order_id "
        "INNER JOIN `proj.ds.products` p ON oi.product_id = p.id "
        "GROUP BY 1"
    )
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    q0 = json.loads(res.output)["queries"][0]
    assert [v["view_name"] for v in q0["views"]] == ["order_items", "orders", "products"]
    oi_flds = {f["field_name"]: f for f in q0["views"][0]["fields"]}
    assert oi_flds["id"]["primary_key"] is True
    assert "returned_revenue" in oi_flds
    assert {"distinct_orders", "night_revenue", "night_share"}.isdisjoint(oi_flds)
    assert {e["explore_name"] for e in q0["explores"]} == {"order_items", "orders", "products"}
    jas = q0["join_analysis"]
    assert {j["explore_name"] for j in jas} == {"order_items"}
    miss_orders = next(j for j in jas if j["status"] == "missing_join")
    assert [p["target_view"] for p in miss_orders.get("precedents", [])] == ["orders"]


def test_cross_view_fields_exact_query_coverage_and_explore_oriented_inferred_rel():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: Users {\n"
        "  sql_table_name: `proj.ds.users` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: age { type: number sql: ${TABLE}.age ;; }\n"
        "  dimension: latitude { type: number sql: ${TABLE}.latitude ;; }\n"
        "  dimension: abs_latitude { type: number sql: ABS(${latitude}) ;; }\n"
        "  measure: avg_abs_latitude { type: average sql: ${abs_latitude} ;; }\n"
        "}\n"
        "view: order_items {\n"
        "  sql_table_name: `proj.ds.order_items` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "  dimension: sale_price { type: number sql: ${TABLE}.sale_price ;; }\n"
        "  dimension_group: created { type: time timeframes: [raw, hour] sql: ${TABLE}.created_at ;; }\n"
        "  measure: count { type: count }\n"
        '  measure: night_revenue { type: sum sql: ${sale_price} ;; filters: [created_hour: "0"] }\n'
        "  measure: night_share { type: number sql: 1.0 * ${night_revenue} / NULLIF(${count}, 0) ;; }\n"
        "}\n"
        "view: order_items_users_fields {\n"
        "  measure: avg_weighted_age { type: average sql: ${users.age} ;; }\n"
        "  measure: lat_price_corr { type: number sql: CORR(${users.abs_latitude}, ${order_items.sale_price}) ;; }\n"
        "  measure: age_price_corr { type: number sql: CORR(${users.age}, ${order_items.sale_price}) ;; }\n"
        "}\n"
        "explore: order_items {\n"
        "  view_name: order_items\n"
        "  join: users { from: Users type: left_outer relationship: many_to_one sql_on: ${order_items.user_id} = ${users.id} ;; }\n"
        "  join: order_items_users_fields { sql: ;; relationship: one_to_one }\n"
        "  query: lat_age_corr {\n"
        '    measures: [order_items_users_fields.lat_price_corr, order_items_users_fields.age_price_corr, users.avg_abs_latitude]\n'
        '    filters: [users.id: "NOT NULL"]\n'
        "  }\n"
        "  query: midnight_owl { measures: [order_items.count, order_items.night_revenue, order_items.night_share] }\n"
        "}\n"
        "explore: items_unjoined { view_name: order_items }\n"
    )
    sql = (
        "SELECT ROUND(CORR(ABS(u.latitude), oi.sale_price), 4) AS lat_corr, "
        "ROUND(CORR(u.age, oi.sale_price), 4) AS age_corr, "
        "ROUND(AVG(ABS(u.latitude)), 2) AS avg_lat "
        "FROM `proj.ds.users` u INNER JOIN `proj.ds.order_items` oi ON u.id = oi.user_id; "
        "SELECT COUNT(id) AS cnt, SUM(sale_price) AS rev FROM `proj.ds.order_items`"
    )
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    assert res.exit_code == 0, res.output
    q0, q1 = json.loads(res.output)["queries"]
    xf_view = next(v for v in q0["views"] if v["view_name"] == "order_items_users_fields")
    assert "sql_table" not in xf_view
    assert [(eq["query_name"], eq["coverage"]) for eq in q0["explore_queries"]] == [("lat_age_corr", "exact")]
    oi_ja = next(j for j in q0["join_analysis"] if j["explore_name"] == "order_items")
    assert oi_ja["relationship"] == "many_to_one" and oi_ja["inferred_relationship"] == "many_to_one"
    assert "safety_warnings" not in oi_ja
    assert "explore_queries" not in q1

    from lkr.parse import parse_sql_to_lookml

    raw_jas = parse_sql_to_lookml(sql=sql.split(";")[0], lookml=lkml, offline=True).queries[0].join_analysis
    unjoined_ja = next(j for j in raw_jas if j.explore_name == "items_unjoined")
    assert unjoined_ja.status == "missing_join" and unjoined_ja.inferred_relationship == "many_to_one"


def test_cte_dead_projection_pruning_count_alias_and_unnest_virtual_view():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: events {\n"
        "  sql_table_name: `proj.ds.events` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: session_id { type: string sql: ${TABLE}.session_id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "  dimension: event_type { type: string sql: ${TABLE}.event_type ;; }\n"
        "  dimension: uri { type: string sql: ${TABLE}.uri ;; }\n"
        "  dimension: uri_dept { type: string sql: REGEXP_EXTRACT(${uri}, r'^/department/([^/?#]+)') ;; }\n"
        "  dimension: uri_segments { hidden: yes sql: SPLIT(TRIM(${uri}, '/'), '/') ;; }\n"
        "  measure: count { type: count }\n"
        '  measure: dept_events { type: count filters: [uri_dept: "-NULL"] }\n'
        "  measure: approx_sessions { type: number sql: APPROX_COUNT_DISTINCT(${session_id}) ;; }\n"
        "}\n"
        "view: events__uri_segments {\n"
        "  dimension: pk { primary_key: yes hidden: yes type: string sql: CONCAT(CAST(${events.id} AS STRING), '_', CAST(events__uri_segments_offset AS STRING)) ;; }\n"
        "  dimension: depth_level { type: number sql: events__uri_segments_offset ;; }\n"
        "  dimension: uri_segment { type: string sql: ${TABLE} ;; }\n"
        "}\n"
        "explore: events {\n"
        "  view_name: events\n"
        "  join: events__uri_segments {\n"
        "    sql: LEFT JOIN UNNEST(${events.uri_segments}) AS events__uri_segments WITH OFFSET AS events__uri_segments_offset ;;\n"
        "    relationship: one_to_many\n"
        "  }\n"
        "  query: by_event_type { dimensions: [events.event_type] measures: [events.count, events.dept_events] }\n"
        "  query: by_uri { dimensions: [events.uri] measures: [events.count, events.approx_sessions] }\n"
        "  query: top_uri_segments {\n"
        "    dimensions: [events__uri_segments.depth_level, events__uri_segments.uri_segment]\n"
        "    measures: [events.count, events.approx_sessions]\n"
        '    filters: [events__uri_segments.uri_segment: "-EMPTY"]\n'
        "  }\n"
        "}\n"
    )
    sql = (
        "WITH raw_e AS (SELECT id AS event_id, session_id, user_id, event_type, uri FROM `proj.ds.events`), "
        "parsed AS (SELECT event_id, session_id, user_id, event_type, "
        "REGEXP_EXTRACT(uri, r'^/department/([^/?#]+)') AS uri_dept FROM raw_e) "
        "SELECT event_type, COUNT(event_id) AS total_events, COUNTIF(uri_dept IS NOT NULL) AS dept_cnt "
        "FROM parsed GROUP BY 1; "
        "WITH parsed AS (SELECT uri, event_type, session_id FROM `proj.ds.events`) "
        "SELECT uri, COUNT(*) AS cnt, APPROX_COUNT_DISTINCT(session_id) AS sess FROM parsed GROUP BY 1; "
        "SELECT segment_offset, uri_segment, COUNT(e.id) AS hits, APPROX_COUNT_DISTINCT(e.session_id) AS sess "
        "FROM `proj.ds.events` e CROSS JOIN UNNEST(SPLIT(TRIM(e.uri, '/'), '/')) AS uri_segment WITH OFFSET AS segment_offset "
        "WHERE segment_offset <= 2 AND uri_segment != '' GROUP BY 1, 2"
    )
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    assert res.exit_code == 0, res.output
    q0, q1, q2 = json.loads(res.output)["queries"]

    q0_fnames = {f["field_name"] for v in q0["views"] for f in v["fields"]}
    assert "session_id" not in q0_fnames and "user_id" not in q0_fnames
    assert [(eq["query_name"], eq["coverage"]) for eq in q0["explore_queries"]] == [("by_event_type", "exact")]

    q1_vnames = {v["view_name"] for v in q1["views"]}
    assert "events__uri_segments" not in q1_vnames
    assert [(eq["query_name"], eq["coverage"]) for eq in q1["explore_queries"]] == [("by_uri", "exact")]

    q2_vnames = {v["view_name"] for v in q2["views"]}
    assert "events__uri_segments" in q2_vnames
    assert q2["join_analysis"][0]["status"] == "exact_match"
    assert q2["join_analysis"][0]["matched_explore_join"] == "events__uri_segments"
    assert [(eq["query_name"], eq["coverage"]) for eq in q2["explore_queries"]] == [("top_uri_segments", "exact")]


def test_star_schema_transitive_pk_fk_join_analysis_and_explore_queries():
    import json

    from typer.testing import CliRunner

    from lkr.main import app

    lkml = (
        'connection: "bq"\n'
        "view: users {\n"
        "  sql_table_name: `proj.ds.users` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: gender { type: string sql: ${TABLE}.gender ;; }\n"
        "}\n"
        "view: orders {\n"
        "  sql_table_name: `proj.ds.orders` ;;\n"
        "  dimension: order_id { primary_key: yes type: number sql: ${TABLE}.order_id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "}\n"
        "view: products {\n"
        "  sql_table_name: `proj.ds.products` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: department { type: string sql: ${TABLE}.department ;; }\n"
        "}\n"
        "view: order_items {\n"
        "  sql_table_name: `proj.ds.order_items` ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        "  dimension: order_id { type: number sql: ${TABLE}.order_id ;; }\n"
        "  dimension: user_id { type: number sql: ${TABLE}.user_id ;; }\n"
        "  dimension: product_id { type: number sql: ${TABLE}.product_id ;; }\n"
        "  measure: count { type: count }\n"
        "}\n"
        "explore: order_items {\n"
        "  view_name: order_items\n"
        "  join: orders { type: left_outer relationship: many_to_one sql_on: ${order_items.order_id} = ${orders.order_id} ;; }\n"
        "  join: users { type: left_outer relationship: many_to_one sql_on: ${order_items.user_id} = ${users.id} ;; }\n"
        "  join: products { type: left_outer relationship: many_to_one sql_on: ${order_items.product_id} = ${products.id} ;; }\n"
        "  query: by_gender_dept { dimensions: [users.gender, products.department] measures: [order_items.count] }\n"
        "}\n"
    )
    sql = (
        "SELECT u.gender, COUNT(oi.id) AS total_items "
        "FROM `proj.ds.users` u "
        "INNER JOIN `proj.ds.orders` o ON u.id = o.user_id "
        "INNER JOIN `proj.ds.order_items` oi ON o.order_id = oi.order_id "
        "INNER JOIN `proj.ds.products` p ON oi.product_id = p.id "
        "GROUP BY 1; "
        "SELECT u1.gender, COUNT(oi.id) AS total_items "
        "FROM `proj.ds.users` u1 "
        "INNER JOIN `proj.ds.users` u2 ON u1.id = u2.id "
        "INNER JOIN `proj.ds.order_items` oi ON u1.id = oi.user_id "
        "GROUP BY 1"
    )
    res = CliRunner().invoke(
        app,
        ["parse", "sql-lookml-compare", "--sql", sql, "--lookml", lkml, "--offline", "--compact"],
    )
    assert res.exit_code == 0, res.output
    q0, q1 = json.loads(res.output)["queries"]

    ja0 = {j["sql_join"]: j for j in q0["join_analysis"] if j["explore_name"] == "order_items"}
    uo = ja0["proj.ds.users INNER proj.ds.orders"]
    assert uo["status"] == "type_mismatch"
    assert uo["matched_explore_join"] == "users"
    assert uo["inferred_relationship"] == "many_to_one"
    assert [eq["query_name"] for eq in q0["explore_queries"]] == ["by_gender_dept"]

    ja1 = {j["sql_join"]: j for j in q1["join_analysis"] if j["explore_name"] == "order_items"}
    assert ja1["proj.ds.users INNER proj.ds.users"]["status"] == "missing_join"


