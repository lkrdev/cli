import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lkr.main import app
from lkr.parse.user_attributes import (
    format_user_attributes,
    parse_user_attributes,
)

runner = CliRunner()


class MockUserAttribute:
    def __init__(self, name: str):
        self.name = name


class MockSDK:
    def __init__(self, attribute_names: list[str]):
        self._attrs = [MockUserAttribute(name) for name in attribute_names]

    def all_user_attributes(self):
        return self._attrs


def test_user_attributes_access_grant():
    lkml = """
    connection: "test_db"

    access_grant: financial_data {
      user_attribute: department
      allowed_values: ["finance", "executive"]
    }
    """
    res = parse_user_attributes(lookml=lkml)
    assert len(res.attributes) == 1
    ref = res.attributes[0]
    assert ref.attribute_name == "department"
    assert ref.source_type == "access_grant"
    assert ref.property == "user_attribute"
    assert ref.allowed_values == ["finance", "executive"]
    assert ref.line == 5
    assert ref.valid is None


def test_user_attributes_access_filter():
    lkml = """
    explore: orders {
      access_filter: {
        field: orders.region
        user_attribute: user_region
      }
      access_filter: {
        field: orders.brand
        user_attribute: user_brand
      }
    }
    """
    res = parse_user_attributes(lookml=lkml)
    assert len(res.attributes) == 2
    ref1, ref2 = res.attributes
    assert ref1.attribute_name == "user_region"
    assert ref1.source_type == "access_filter"
    assert ref1.explore == "orders"
    assert ref1.field == "orders.region"
    assert ref1.property == "user_attribute"
    assert ref1.line == 5

    assert ref2.attribute_name == "user_brand"
    assert ref2.source_type == "access_filter"
    assert ref2.explore == "orders"
    assert ref2.field == "orders.brand"
    assert ref2.property == "user_attribute"
    assert ref2.line == 9


def test_user_attributes_liquid_syntax_variants():
    lkml = """
    explore: orders {
      sql_always_where: ${region} = '{{ _user_attributes["quote_region"] }}' ;;
      join: users {
        sql_on: ${orders.user_id} = ${users.id} AND ${users.client} = '{{ _user_attributes[ 'spaced_client' ] }}' ;;
      }
    }

    view: orders {
      sql_table_name: public.orders_{{ _user_attributes['tenant_id'] }} ;;

      dimension: revenue {
        type: number
        sql: CASE WHEN {{ _user_attributes['is_admin'] }} = 1 THEN ${TABLE}.revenue ELSE NULL END ;;
      }

      dimension: raw_check {
        type: string
        sql: _user_attributes['raw_attr'] ;;
      }

      dimension: cost {
        type: number
        sql: ${TABLE}.cost ;;
        html: {% if _user_attributes['can_see_cost'] == 'yes' %} {{ rendered_value }} {% else %} [REDACTED] {% endif %} ;;
      }
    }
    """
    res = parse_user_attributes(lookml=lkml)
    attr_names = [r.attribute_name for r in res.attributes]
    assert "quote_region" in attr_names
    assert "spaced_client" in attr_names
    assert "tenant_id" in attr_names
    assert "is_admin" in attr_names
    assert "raw_attr" in attr_names
    assert "can_see_cost" in attr_names

    # Check join properties
    join_ref = next(r for r in res.attributes if r.attribute_name == "spaced_client")
    assert join_ref.source_type == "liquid"
    assert join_ref.explore == "orders"
    assert join_ref.view == "users"
    assert join_ref.property == "sql_on"

    # Check view sql_table_name
    tbl_ref = next(r for r in res.attributes if r.attribute_name == "tenant_id")
    assert tbl_ref.source_type == "liquid"
    assert tbl_ref.view == "orders"
    assert tbl_ref.property == "sql_table_name"

    # Check html property
    html_ref = next(r for r in res.attributes if r.attribute_name == "can_see_cost")
    assert html_ref.source_type == "liquid"
    assert html_ref.view == "orders"
    assert html_ref.field == "cost"
    assert html_ref.property == "html"


def test_user_attributes_multiline_positions():
    lkml = """
    view: accounts {
      dimension: status {
        sql:
          CASE
            WHEN {{ _user_attributes['vip_status'] }} = 'gold' THEN 'VIP'
            WHEN {{ _user_attributes['tier_status'] }} = 'tier1' THEN 'Tier 1'
            ELSE 'Standard'
          END ;;
      }
    }
    """
    res = parse_user_attributes(lookml=lkml)
    assert len(res.attributes) == 2
    vip_ref = next(r for r in res.attributes if r.attribute_name == "vip_status")
    tier_ref = next(r for r in res.attributes if r.attribute_name == "tier_status")

    assert vip_ref.line == 6
    assert tier_ref.line == 7


def test_user_attributes_validation():
    lkml = """
    access_grant: sales_only {
      user_attribute: user_team
      allowed_values: ["sales"]
    }
    view: accounts {
      dimension: secret {
        sql: {{ _user_attributes['secret_key'] }} ;;
      }
    }
    """
    mock_sdk = MockSDK(["user_team"])
    res = parse_user_attributes(lookml=lkml, validate=True, sdk=mock_sdk)

    assert len(res.attributes) == 2
    team_ref = next(r for r in res.attributes if r.attribute_name == "user_team")
    secret_ref = next(r for r in res.attributes if r.attribute_name == "secret_key")

    assert team_ref.valid is True
    assert secret_ref.valid is False
    assert res.missing_attributes == ["secret_key"]

    text_output = format_user_attributes(res, format="text")
    assert "VALID" in text_output
    assert "INVALID" in text_output
    assert "Missing attributes on instance: secret_key" in text_output


def test_user_attributes_empty():
    lkml = """
    view: plain {
      dimension: id {
        type: number
        sql: ${TABLE}.id ;;
      }
    }
    """
    res = parse_user_attributes(lookml=lkml)
    assert len(res.attributes) == 0
    assert (
        format_user_attributes(res, format="text")
        == "No user attributes found in LookML project."
    )


def test_user_attributes_cli_text_and_json(tmp_path: Path):
    model_file = tmp_path / "app.model.lkml"
    model_file.write_text(
        """
        connection: "warehouse"
        access_grant: finance_grant {
          user_attribute: finance_role
          allowed_values: ["analyst"]
        }
        explore: transactions {
          access_filter: {
            field: transactions.id
            user_attribute: tx_filter
          }
        }
        """,
        encoding="utf-8",
    )

    # 1. Text format to stdout
    res_text = runner.invoke(
        app,
        ["parse", "lookml", "user-attributes", "--path", str(tmp_path)],
    )
    assert res_text.exit_code == 0
    assert "ATTRIBUTE" in res_text.output
    assert "finance_role" in res_text.output
    assert "tx_filter" in res_text.output

    # 2. JSON format to output file
    json_out = tmp_path / "attrs.json"
    res_json = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "user-attributes",
            "--path",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(json_out),
        ],
    )
    assert res_json.exit_code == 0
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert "attributes" in data
    assert len(data["attributes"]) == 2
    names = [a["attribute_name"] for a in data["attributes"]]
    assert "finance_role" in names
    assert "tx_filter" in names


def test_user_attributes_cli_errors(tmp_path: Path):
    # Non-existent path
    res_bad_path = runner.invoke(
        app,
        ["parse", "lookml", "user-attributes", "--path", str(tmp_path / "missing")],
    )
    assert res_bad_path.exit_code == 1

    # Invalid format
    res_bad_fmt = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "user-attributes",
            "--path",
            str(tmp_path),
            "--format",
            "xml",
        ],
    )
    assert res_bad_fmt.exit_code == 1


def test_lookml_command_backward_compatibility(tmp_path: Path):
    view_file = tmp_path / "users.view.lkml"
    view_file.write_text(
        "view: users { dimension: id { type: number } }", encoding="utf-8"
    )

    res = runner.invoke(
        app,
        ["parse", "lookml", "--file", str(view_file)],
    )
    assert res.exit_code == 0
    parsed = json.loads(res.output)
    assert "file" in parsed or "model" in parsed


def test_user_attributes_validation_missing_context():
    with pytest.raises(ValueError, match="No Looker context provided for --validate"):
        parse_user_attributes(
            lookml="access_grant: g { user_attribute: a }", validate=True
        )


def test_user_attributes_lookml_filters():
    lkml = """
    explore: orders {
      always_filter: {
        filters: [orders.region: "{{ _user_attributes['always_region'] }}"]
      }
      conditionally_filter: {
        filters: [orders.brand: "{{ _user_attributes['cond_brand'] }}"]
        unless: [orders.id]
      }
    }

    view: orders {
      measure: filtered_revenue {
        type: sum
        sql: ${TABLE}.revenue ;;
        filters: [orders.department: "{{ _user_attributes['dept_filter'] }}"]
      }
    }
    """
    res = parse_user_attributes(lookml=lkml)
    by_name = {r.attribute_name: r for r in res.attributes}
    assert "always_region" in by_name
    assert by_name["always_region"].explore == "orders"
    assert by_name["always_region"].field == "orders.region"
    assert by_name["always_region"].property == "always_filter.filters"

    assert "cond_brand" in by_name
    assert by_name["cond_brand"].explore == "orders"
    assert by_name["cond_brand"].field == "orders.brand"
    assert by_name["cond_brand"].property == "conditionally_filter.filters"

    assert "dept_filter" in by_name
    assert by_name["dept_filter"].view == "orders"
    assert by_name["dept_filter"].field == "filtered_revenue"
    assert by_name["dept_filter"].property == "filters[orders.department]"


def test_user_attributes_lookml_dashboard(tmp_path: Path):
    dash_file = tmp_path / "overview.dashboard.lookml"
    dash_file.write_text(
        """- dashboard: executive_overview
  title: Executive Overview
  filters:
  - name: Brand Filter
    title: Brand Filter
    type: field_filter
    model: ecommerce
    explore: orders
    field: orders.brand
    default_value: "{{ _user_attributes['Looker_Brand'] }}"
  elements:
  - name: Regional Sales
    title: Regional Sales
    model: ecommerce
    explore: orders
    type: looker_grid
    filters:
      orders.region: "{{ _user_attributes['Looker_Region'] }}"
      orders.tier: "{{ _user_attributes['Looker_Tier'] }}"
""",
        encoding="utf-8",
    )

    res = parse_user_attributes(path=tmp_path)
    by_name = {r.attribute_name: r for r in res.attributes}
    assert set(by_name.keys()) == {"Looker_Brand", "Looker_Region", "Looker_Tier"}

    brand_ref = by_name["Looker_Brand"]
    assert brand_ref.source_type == "dashboard_filter"
    assert brand_ref.model == "ecommerce"
    assert brand_ref.explore == "orders"
    assert brand_ref.field == "orders.brand"
    assert brand_ref.line == 10

    region_ref = by_name["Looker_Region"]
    assert region_ref.source_type == "dashboard_filter"
    assert region_ref.model == "ecommerce"
    assert region_ref.explore == "orders"
    assert region_ref.field == "orders.region"
    assert region_ref.line == 18


def test_user_attributes_dashboard_json_shapes(tmp_path: Path):
    # Shape 1: Single DashboardFilter object
    single_filter = {
        "name": "Region",
        "model": "sales_model",
        "explore": "orders",
        "dimension": "orders.region",
        "default_value": "{{ _user_attributes['single_region_attr'] }}",
    }
    res_single = parse_user_attributes(dashboard_json=json.dumps(single_filter))
    assert len(res_single.attributes) == 1
    assert res_single.attributes[0].attribute_name == "single_region_attr"
    assert res_single.attributes[0].source_type == "dashboard_filter"
    assert res_single.attributes[0].model == "sales_model"
    assert res_single.attributes[0].explore == "orders"
    assert res_single.attributes[0].field == "orders.region"

    # Shape 2: Dashboard object (e.g. looker-cli export / SDK Dashboard)
    dashboard_export = {
        "id": "123",
        "title": "Sales Dashboard",
        "dashboard_filters": [
            {
                "name": "Tenant",
                "model": "sales_model",
                "explore": "orders",
                "dimension": "orders.tenant_id",
                "default_value": "{{ _user_attributes['export_tenant_attr'] }}",
            }
        ],
        "dashboard_elements": [
            {
                "title": "Revenue Tile",
                "query": {
                    "model": "sales_model",
                    "view": "orders",
                    "filters": {
                        "orders.country": "{{ _user_attributes['export_country_attr'] }}"
                    },
                },
            }
        ],
    }
    dash_json_path = tmp_path / "exported_dashboard.json"
    dash_json_path.write_text(json.dumps(dashboard_export), encoding="utf-8")

    res_cli = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "user-attributes",
            "--dashboard-file",
            str(dash_json_path),
            "--format",
            "json",
        ],
    )
    assert res_cli.exit_code == 0
    cli_data = json.loads(res_cli.output)
    cli_names = {a["attribute_name"] for a in cli_data["attributes"]}
    assert cli_names == {"export_tenant_attr", "export_country_attr"}

    # Shape 3: Array of DashboardFilter objects
    filter_array = [
        {
            "name": "Filter A",
            "dimension": "users.team",
            "default_value": "{{ _user_attributes['array_team_attr'] }}",
        },
        {
            "name": "Filter B",
            "dimension": "users.org",
            "default_value": "{{ _user_attributes['array_org_attr'] }}",
        },
    ]
    res_arr = parse_user_attributes(dashboard_json=json.dumps(filter_array))
    assert {r.attribute_name for r in res_arr.attributes} == {
        "array_team_attr",
        "array_org_attr",
    }
