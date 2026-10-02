import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    LookmlExplore,
    LookmlExploreSource,
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
    cli_alias_res = runner.invoke(
        app,
        [
            "parse",
            "sql-to-lookml",
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
    assert cli_alias_res.exit_code == 0
    payload = json.loads(cli_res.stdout)
    assert len(payload["queries"]) == 3
    assert payload["queries"][2]["views"][0]["fields"][0]["line"] == 3

    # Also test sql-to-api alias command
    cli_alias_res = runner.invoke(
        app,
        [
            "parse",
            "sql-to-api",
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
    assert cli_alias_res.exit_code == 0
    payload_alias = json.loads(cli_alias_res.stdout)
    assert payload_alias == payload


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
    assert [t.test_name for t in oi_fields["total_sale_price"].tests] == ["test_revenue_pos"]
    assert oi_fields["sale_price"].tests == []

    # Field-level tests on inventory_items view
    ii_views = next(v for v in q1.views if v.view_name == "inventory_items")
    ii_fields = {f.field_name: f for f in ii_views.fields}
    assert [t.test_name for t in ii_fields["total_gross_margin"].tests] == ["test_margin_pos"]

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
    payload_normal = json.loads(res_normal.model_dump_json(by_alias=True, exclude_none=True))
    assert "_doc" not in payload_normal

    res_desc = parse_sql_to_lookml(
        sql="SELECT id FROM users",
        lookml=lkml,
        describe=True,
        sql_schema="public",
        lkml_schema="public",
    )
    assert res_desc.doc == SQL_TO_LOOKML_DOC
    payload_desc = json.loads(res_desc.model_dump_json(by_alias=True, exclude_none=True))
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
    assert {
        (a["name"], a["value"]) for a in actual_exp["aliases"]
    } == {(a["name"], a["value"]) for a in expected_exp["aliases"]}

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
                assert af[fk] == ef[fk], f"Field {fname}.{fk} mismatch: {af[fk]!r} != {ef[fk]!r}"


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
    exp = lookml_to_lookml_model_explore("inline", "order_items", lookml=lkml).model_dump(
        by_alias=True
    )

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
    assert dims["order_items.dynamic_metric_dim"]["label_from_parameter"] == "metric_selector"

    # Error 6: distance units value_format
    assert dims["order_items.warehouse_to_user_distance"]["value_format"] == '#,##0.00" km"'

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
    assert m_date["user_attribute_filter_types"] == ["datetime", "advanced_filter_datetime"]

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
    assert dims3["order_items.sales_region"]["map_layer"]["name"] == "custom_sales_regions"
    assert dims3["order_items.sales_region"]["map_layer"]["url"] == "/maps/regions.topojson"
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
    dur_names = [
        f
        for f in sets3["order_items"]
        if f.endswith("_default_dur")
    ]
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
    assert meas3["order_items.suggested_measure"]["suggest_dimension"] == "products.category"
    assert meas3["order_items.suggested_measure"]["suggest_explore"] == "custom_exp"
    assert meas3["order_items.suggested_measure"]["suggestions"] == ["A", "B"]
    assert filts3["order_items.status_filter"]["suggest_dimension"] == "order_items.status"
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
    with pytest.raises(ValueError, match="LookML view 'foo' table 'foo' cannot be qualified"):
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
        lambda conn_name: {"database": "db_live", "schema": "schema_live"}
        if conn_name == "thelook"
        else None,
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




