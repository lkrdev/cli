import json
from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    CompiledTableInfo,
    LookmlDatabaseCompareResult,
    parse_lookml_database_compare,
)
from lkr.parse.lookml_database_compare import (
    format_compare_result,
    load_db_schema_file,
)

runner = CliRunner()

SAMPLE_LOOKML = """
connection: "bigquery_conn"

explore: orders {
  join: users {
    type: left_outer
    sql_on: ${orders.user_id} = ${users.id} ;;
    relationship: many_to_one
  }
}

explore: inventory {
  join: products {
    type: left_outer
    foreign_key: product_id
  }
}

view: orders {
  sql_table_name: `my_project.thelook.orders` ;;

  dimension: id {
    primary_key: yes
    type: number
    sql: ${TABLE}.id ;;
  }

  dimension: user_id {
    type: number
    sql: ${TABLE}.user_id ;;
  }

  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }

  dimension_group: created {
    type: time
    timeframes: [raw, time, date, week, month, year]
    sql: ${TABLE}.created_at ;;
  }

  measure: count {
    type: count
  }
}

view: users {
  sql_table_name: thelook.users ;;

  dimension: id {
    primary_key: yes
    type: number
  }

  dimension: name {
    type: string
    sql: ${TABLE}.name ;;
  }
}

view: inventory {
  sql_table_name: thelook.inventory_items ;;

  dimension: id {
    primary_key: yes
    sql: ${TABLE}.id ;;
  }

  dimension: product_id {
    sql: ${TABLE}.product_id ;;
  }
}

view: products {
  sql_table_name: thelook.products ;;

  dimension: id {
    primary_key: yes
    sql: ${TABLE}.id ;;
  }

  dimension: brand {
    sql: ${TABLE}.brand ;;
  }
}
"""


def test_basic_ast_compilation():
    result = parse_lookml_database_compare(lookml=SAMPLE_LOOKML, columns=True)
    assert isinstance(result, LookmlDatabaseCompareResult)
    assert len(result.warnings) > 0
    assert len(result.compile_errors) == 0

    tables_by_name = {t.name: t for t in result.tables}
    assert "orders" in tables_by_name
    assert "users" in tables_by_name
    assert "inventory_items" in tables_by_name
    assert "products" in tables_by_name

    orders_tbl = tables_by_name["orders"]
    assert orders_tbl.table == "my_project.thelook.orders"
    assert orders_tbl.catalog == "my_project"
    assert orders_tbl.schema == "thelook"
    assert orders_tbl.connection == "bigquery_conn"
    assert "inline.orders" in orders_tbl.explores
    assert set(orders_tbl.columns) == {"created_at", "id", "status", "user_id"}

    users_tbl = tables_by_name["users"]
    assert users_tbl.table == "thelook.users"
    assert users_tbl.schema == "thelook"
    assert set(users_tbl.columns) == {"id", "name"}


def test_columns_flag_toggle():
    res_no_cols = parse_lookml_database_compare(lookml=SAMPLE_LOOKML, columns=False)
    for t in res_no_cols.tables:
        assert t.columns == []

    res_with_cols = parse_lookml_database_compare(lookml=SAMPLE_LOOKML, columns=True)
    for t in res_with_cols.tables:
        assert len(t.columns) > 0


def test_filter_models_and_explores():
    result = parse_lookml_database_compare(
        lookml=SAMPLE_LOOKML,
        explore=["orders"],
        columns=True,
    )
    tables = [t.name for t in result.tables]
    assert "orders" in tables
    assert "users" in tables
    assert "inventory_items" not in tables
    assert "products" not in tables


def test_chained_sql_table_name_resolution():
    chained_lookml = """
    connection: "pg_conn"
    explore: sales {}

    view: raw_sales {
      sql_table_name: public.sales_v1 ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
    }

    view: sales {
      sql_table_name: ${raw_sales.SQL_TABLE_NAME} ;;
      dimension: id { primary_key: yes sql: ${TABLE}.id ;; }
      dimension: amount { sql: ${TABLE}.amount ;; }
    }
    """
    res = parse_lookml_database_compare(lookml=chained_lookml, columns=True)
    assert len(res.tables) == 1
    t = res.tables[0]
    assert t.table == "public.sales_v1"
    assert t.schema == "public"
    assert t.name == "sales_v1"
    assert set(t.columns) == {"amount", "id"}


def test_validation_against_mock_schema_file(tmp_path: Path):
    schema_data = {
        "tables": [
            {
                "table": "my_project.thelook.orders",
                "columns": ["id", "user_id", "status"],  # 'created_at' missing from DB!
            },
            {
                "table": "thelook.users",
                "columns": ["id", "name", "email"],  # 'email' unmodeled in LookML!
            },
            {
                "table": "thelook.inventory_items",
                "columns": ["id", "product_id"],
            },
            {
                "table": "thelook.unmodeled_refunds",  # Whole table unmodeled!
                "columns": ["id", "amount"],
            },
            # 'products' table missing from DB completely!
        ]
    }
    schema_file = tmp_path / "db_schema.json"
    schema_file.write_text(json.dumps(schema_data), encoding="utf-8")

    res = parse_lookml_database_compare(
        lookml=SAMPLE_LOOKML,
        validate_columns=True,
        db_schema_file=schema_file,
    )

    assert res.validation is not None
    missing = res.validation.missing_in_database
    unmodeled = res.validation.unmodeled_in_lookml

    # Missing table: thelook.products
    missing_tbl_names = [mt.table for mt in missing.tables]
    assert any("products" in name for name in missing_tbl_names)

    # Missing column: created_at on orders
    missing_col_pairs = [(mc.table, mc.column) for mc in missing.columns]
    assert ("my_project.thelook.orders", "created_at") in missing_col_pairs

    # Unmodeled table: thelook.unmodeled_refunds
    assert "thelook.unmodeled_refunds" in unmodeled.tables

    # Unmodeled column: email on thelook.users
    unmodeled_cols_by_table = {uc.table: uc.columns for uc in unmodeled.columns}
    assert "thelook.users" in unmodeled_cols_by_table
    assert "email" in unmodeled_cols_by_table["thelook.users"]


def test_database_catalog_formats(tmp_path: Path):
    # Flat dictionary format
    flat_data = {
        "thelook.orders": ["id", "status"],
        "thelook.users": ["id", "name"],
    }
    f1 = tmp_path / "flat.json"
    f1.write_text(json.dumps(flat_data), encoding="utf-8")
    cat1 = load_db_schema_file(f1)
    t1 = cat1.find_table("orders", "thelook")
    assert t1 is not None
    assert t1.has_column("id")

    # Nested hierarchy format
    nested_data = {
        "my_project": {
            "thelook": {
                "orders": ["id", "status"],
            }
        }
    }
    f2 = tmp_path / "nested.json"
    f2.write_text(json.dumps(nested_data), encoding="utf-8")
    cat2 = load_db_schema_file(f2)
    assert cat2.find_table("orders", "thelook", "my_project") is not None


def test_cli_command_json_and_output(tmp_path: Path):
    out_file = tmp_path / "result.json"
    cmd_args = [
        "parse",
        "lookml-database-compare",
        "--lookml",
        SAMPLE_LOOKML,
        "--explore",
        "orders",
        "--columns",
        "--format",
        "json",
        "--output",
        str(out_file),
    ]
    result = runner.invoke(app, cmd_args)
    assert result.exit_code == 0
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "tables" in data
    assert len(data["tables"]) == 2
    table_names = [t["name"] for t in data["tables"]]
    assert "orders" in table_names
    assert "users" in table_names


def test_cli_command_console_output():
    cmd_args = [
        "parse",
        "lookml-database-compare",
        "--lookml",
        SAMPLE_LOOKML,
        "--explore",
        "orders",
        "--columns",
        "--format",
        "console",
    ]
    result = runner.invoke(app, cmd_args)
    assert result.exit_code == 0
    assert "Compiled LookML Tables" in result.output
    assert "my_project.thelook.orders" in result.output
    assert "thelook.users" in result.output


def test_format_compare_result_clean_validation():
    res = LookmlDatabaseCompareResult(
        warnings=["Some warning"],
        tables=[
            CompiledTableInfo(
                table="thelook.orders",
                name="orders",
                schema="thelook",
                explores=["thelook.orders"],
                columns=["id", "status"],
            )
        ],
        validation=None,
    )
    txt = format_compare_result(res, fmt="console")
    assert "thelook.orders" in txt
    assert "Some warning" in txt


def test_mock_looker_sdk_inline_query():
    mock_sdk = MagicMock()
    mock_sql = """
    SELECT
        orders.id AS orders_id,
        orders.status AS orders_status,
        users.id AS users_id,
        users.name AS users_name
    FROM `my_project.thelook.orders` AS orders
    LEFT JOIN `my_project.thelook.users` AS users ON orders.user_id = users.id
    """
    mock_sdk.run_inline_query.return_value = mock_sql

    res = parse_lookml_database_compare(
        lookml=SAMPLE_LOOKML,
        explore="orders",
        columns=True,
        sdk=mock_sdk,
    )
    assert mock_sdk.run_inline_query.called
    table_names = [t.name for t in res.tables]
    assert "orders" in table_names
    assert "users" in table_names
