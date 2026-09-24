import json
import re
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.schema import build_explore_query_schema, validate_query
from lkr.schema.builder import build_query_body_schema
from lkr.schema.dynamic_fields import (
    build_custom_dimension_schema,
    build_custom_measure_schema,
    build_dynamic_fields_schema,
    build_table_calculation_schema,
)
from lkr.schema.fields import (
    build_fields_schema,
    build_fill_fields_schema,
    build_pivots_schema,
    build_sorts_schema,
    build_subtotals_schema,
    extract_visible_explore_fields,
    is_visible_field,
)
from lkr.schema.filter_expressions import (
    FILTER_EXPRESSION_DEFS,
    build_filter_property_schema,
    build_filters_schema,
    classify_filter_expression_ref,
    extract_enum_values,
)

runner = CliRunner()


def test_is_visible_field_and_extract_visible_explore_fields():
    assert is_visible_field({"name": "users.id", "hidden": False}) is True
    assert is_visible_field({"name": "users.id", "hidden": True}) is False
    assert is_visible_field({"name": "", "hidden": False}) is False
    assert is_visible_field({}) is False

    raw = {
        "fields": {
            "dimensions": [
                {"name": "d1", "hidden": False},
                {"name": "d_hidden", "hidden": True},
            ],
            "measures": [
                {"name": "m1", "hidden": False},
                {"name": "m_hidden", "hidden": True},
            ],
            "filters": [
                {"name": "f1", "hidden": False},
                {"name": "f_hidden", "hidden": True},
            ],
            "parameters": [
                {"name": "p1", "hidden": False},
                {"name": "p_hidden", "hidden": True},
            ],
        }
    }
    visible = extract_visible_explore_fields(raw)
    assert visible.dimension_names == ["d1"]
    assert visible.measure_names == ["m1"]
    assert visible.selectable_field_names == ["d1", "m1"]
    assert [f["name"] for f in visible.filters] == ["f1"]
    assert [p["name"] for p in visible.parameters] == ["p1"]


def test_build_fields_pivots_sorts_fill_and_subtotals_schema():
    fields_schema = build_fields_schema(["d1", "d2"], ["m1"])
    assert fields_schema["items"]["enum"] == ["d1", "d2", "m1"]

    pivots_schema = build_pivots_schema(["d1", "d2"])
    assert pivots_schema["items"]["enum"] == ["d1", "d2"]
    assert "m1" not in pivots_schema["items"]["enum"]

    fill_schema = build_fill_fields_schema(["d1", "d2"])
    assert fill_schema["items"]["enum"] == ["d1", "d2"]

    subtotals_schema = build_subtotals_schema(["d1", "d2"])
    assert subtotals_schema["items"]["enum"] == ["d1", "d2"]

    sorts_schema = build_sorts_schema(["d1", "m1"])
    sort_pat = re.compile(sorts_schema["items"]["pattern"])
    assert sort_pat.match("d1")
    assert sort_pat.match("d1 desc")
    assert sort_pat.match("m1 desc 0")
    assert sort_pat.match("__UNSORTED__")
    assert not sort_pat.match("unknown_field desc")


def test_extract_enum_values_and_classify_filter_expression_ref():
    assert extract_enum_values(
        {
            "enumerations": [
                {"label": "A", "value": "a"},
                {"label": "B", "value": "b"},
            ]
        }
    ) == ["a", "b"]
    assert extract_enum_values({"allowed_values": ["x", "y"]}) == ["x", "y"]
    assert extract_enum_values({}) is None

    assert (
        classify_filter_expression_ref({"type": "yesno"})
        == "#/$defs/BooleanFilterExpression"
    )
    assert (
        classify_filter_expression_ref({"type": "location"})
        == "#/$defs/LocationFilterExpression"
    )
    assert (
        classify_filter_expression_ref(
            {"type": "date_date", "is_timeframe": True}
        )
        == "#/$defs/DateTimeFilterExpression"
    )
    assert (
        classify_filter_expression_ref({"type": "number", "is_numeric": True})
        == "#/$defs/NumberFilterExpression"
    )
    assert (
        classify_filter_expression_ref({"type": "string"})
        == "#/$defs/StringFilterExpression"
    )


def test_filter_expression_patterns():
    dt_pattern = re.compile(
        FILTER_EXPRESSION_DEFS["DateTimeFilterExpression"]["pattern"]
    )
    for ex in FILTER_EXPRESSION_DEFS["DateTimeFilterExpression"]["examples"]:
        assert dt_pattern.match(ex), f"DateTime pattern failed on {ex}"

    num_pattern = re.compile(
        FILTER_EXPRESSION_DEFS["NumberFilterExpression"]["pattern"]
    )
    for ex in FILTER_EXPRESSION_DEFS["NumberFilterExpression"]["examples"]:
        assert num_pattern.match(ex), f"Number pattern failed on {ex}"

    loc_pattern = re.compile(
        FILTER_EXPRESSION_DEFS["LocationFilterExpression"]["pattern"]
    )
    for ex in FILTER_EXPRESSION_DEFS["LocationFilterExpression"]["examples"]:
        assert loc_pattern.match(ex), f"Location pattern failed on {ex}"


def test_build_filter_property_and_filters_schema():
    param_prop = build_filter_property_schema(
        {
            "name": "p1",
            "parameter": True,
            "has_allowed_values": True,
            "enumerations": [
                {"label": "Day", "value": "day"},
                {"label": "Week", "value": "week"},
            ],
            "default_filter_value": "day",
        },
        is_parameter=True,
    )
    assert param_prop == {
        "type": "string",
        "enum": ["day", "week"],
        "default": "day",
    }

    dim_enum_prop = build_filter_property_schema(
        {
            "name": "users.age_tier",
            "type": "tier",
            "enumerations": [{"label": "0 to 17", "value": "0 to 17"}],
        }
    )
    assert "anyOf" in dim_enum_prop

    filters_schema = build_filters_schema(
        dimensions=[{"name": "d1", "type": "string"}],
        measures=[{"name": "m1", "type": "sum", "is_numeric": True}],
        filters=[{"name": "f1", "type": "date_time", "can_time_filter": True}],
        parameters=[
            {
                "name": "p1",
                "parameter": True,
                "has_allowed_values": True,
                "enumerations": [{"label": "One", "value": "1"}],
            }
        ],
    )
    props = filters_schema["properties"]
    assert set(props.keys()) == {"d1", "m1", "f1", "p1"}
    assert props["d1"]["$ref"] == "#/$defs/StringFilterExpression"
    assert props["m1"]["$ref"] == "#/$defs/NumberFilterExpression"
    assert props["f1"]["$ref"] == "#/$defs/DateTimeFilterExpression"
    assert props["p1"]["enum"] == ["1"]


def test_build_dynamic_fields_schema():
    cd = build_custom_dimension_schema()
    assert "dimension" in cd["required"]

    cm = build_custom_measure_schema(["d1", "d2"])
    assert cm["properties"]["based_on"]["enum"] == ["d1", "d2"]
    assert "measure" in cm["required"]

    tc = build_table_calculation_schema()
    assert "table_calculation" in tc["required"]

    df = build_dynamic_fields_schema(["d1"])
    assert len(df["items"]["oneOf"]) == 3


def test_schema_generate_and_validate_pipeline(tmp_path: Path):
    order_items_path = Path("tmp/order_items.json")
    if not order_items_path.exists():
        order_items_path = tmp_path / "order_items.json"
        order_items_path.write_text(
            json.dumps(
                {
                    "fields": {
                        "dimensions": [
                            {"name": "order_items.created_year", "type": "date_year", "is_timeframe": True, "hidden": False},
                            {"name": "order_items.created_date", "type": "date_date", "is_timeframe": True, "hidden": False},
                            {"name": "order_items.status", "type": "string", "hidden": False},
                            {"name": "order_items.sale_price", "type": "number", "is_numeric": True, "hidden": False},
                            {"name": "users.over_21", "type": "yesno", "hidden": False},
                        ],
                        "measures": [
                            {"name": "users.count", "type": "count", "is_numeric": True, "hidden": False},
                        ],
                        "filters": [],
                        "parameters": [],
                    }
                }
            ),
            encoding="utf-8",
        )

    data = json.loads(order_items_path.read_text(encoding="utf-8"))
    body_schema = build_query_body_schema("thelook", "order_items", data)
    assert body_schema["properties"]["model"]["const"] == "thelook"
    assert body_schema["properties"]["view"]["const"] == "order_items"
    assert body_schema["properties"]["limit"]["default"] == "500"

    schema = build_explore_query_schema("thelook", "order_items", data)
    assert schema["properties"]["limit"]["default"] == 500

    # Valid query with dynamic_fields (both CustomDimension in pivots/fields and TableCalculation in fields)
    valid_payload = {
        "model": "thelook",
        "view": "order_items",
        "fields": [
            "order_items.created_year",
            "users.count",
            "custom_dim_bucket",
            "calc_pct",
        ],
        "pivots": ["order_items.status", "custom_dim_bucket"],
        "filters": {
            "order_items.status": "Returned",
            "order_items.created_date": "7 days",
            "order_items.sale_price": ">=10 AND <=50",
            "users.over_21": "Yes",
        },
        "sorts": ["order_items.created_year desc", "calc_pct asc"],
        "dynamic_fields": [
            {
                "dimension": "custom_dim_bucket",
                "label": "Custom Bucket",
                "expression": "${order_items.sale_price} > 20",
            },
            {
                "table_calculation": "calc_pct",
                "label": "Calc Pct",
                "expression": "${users.count} / 100",
            },
        ],
    }
    valid_res = validate_query(valid_payload, schema)
    assert valid_res.valid is True, f"Unexpected errors: {valid_res.errors}"
    assert valid_res.normalized_query is not None
    assert isinstance(
        valid_res.normalized_query["body"]["dynamic_fields"], str
    )

    # Multi-error payload: pipeline must collect EVERY error without stopping early
    invalid_payload = {
        "model": "wrong_model",
        "view": "wrong_view",
        "fields": ["order_items.nonexistent_field"],
        "pivots": ["users.count", "calc_pct"],
        "filters": {
            "order_items.sale_price": "not_a_number_expression",
            "hidden_or_fake.field": "abc",
        },
        "sorts": ["bad_sort_field desc"],
        "subtotals": ["users.count"],
        "dynamic_fields": [
            {
                "table_calculation": "calc_pct",
                "label": "Calc Pct",
                "expression": "${users.count} / 100",
            }
        ],
    }
    invalid_res = validate_query(invalid_payload, schema)
    assert invalid_res.valid is False
    # Verify errors from all pipeline stages were collected simultaneously
    joined_errors = "\n".join(invalid_res.errors)
    assert "$.body.model" in joined_errors
    assert "$.body.view" in joined_errors
    assert "$.body.fields[0]" in joined_errors
    assert "$.body.pivots[0]" in joined_errors
    assert "$.body.pivots[1]" in joined_errors
    assert "$.body.filters.order_items.sale_price" in joined_errors
    assert "$.body.filters.hidden_or_fake.field" in joined_errors
    assert "$.body.sorts[0]" in joined_errors
    assert "$.body.subtotals[0]" in joined_errors

    # Verify CLI `lkr schema generate`
    gen_res = runner.invoke(
        app,
        [
            "schema",
            "generate",
            "--model=thelook",
            "--explore=order_items",
            f"--explore-file={order_items_path}",
        ],
    )
    assert gen_res.exit_code == 0
    cli_schema = json.loads(gen_res.stdout)
    assert cli_schema["title"] == "run_inline_query_thelook_order_items"

    # Verify CLI `lkr schema validate` (auto-generating schema via --model and --explore)
    val_res = runner.invoke(
        app,
        [
            "schema",
            "validate",
            "--model=thelook",
            "--explore=order_items",
            f"--explore-file={order_items_path}",
            f"--query={json.dumps(valid_payload)}",
        ],
    )
    assert val_res.exit_code == 0
    assert json.loads(val_res.stdout)["valid"] is True

    # Verify CLI `lkr schema validate` returns exit code 1 and all errors when invalid
    val_fail_res = runner.invoke(
        app,
        [
            "schema",
            "validate",
            "--model=thelook",
            "--explore=order_items",
            f"--explore-file={order_items_path}",
            f"--query={json.dumps(invalid_payload)}",
        ],
    )
    assert val_fail_res.exit_code == 1
    fail_out = json.loads(val_fail_res.stdout)
    assert fail_out["valid"] is False
    assert len(fail_out["errors"]) >= 9


MOCK_EXPLORE = {
    "fields": {
        "dimensions": [
            {"name": "order_items.status", "type": "string", "hidden": False},
            {"name": "order_items.sale_price", "type": "number", "hidden": False},
            {"name": "order_items.secret_id", "type": "number", "hidden": True},
        ],
        "measures": [
            {
                "name": "order_items.total_sale_price",
                "type": "sum",
                "hidden": False,
            },
        ],
        "filters": [],
        "parameters": [],
    }
}


def test_real_world_dynamic_fields_and_history_shapes() -> None:
    schema = build_explore_query_schema("thelook", "order_items", MOCK_EXPLORE)

    # 1. Valid real-world shapes from system__activity::history:
    #    - TableCalculation with calculation_type + args (no expression)
    #    - CustomMeasure with based_on + filters + filter_expression (no type)
    #    - CustomDimension with ${view.field} expression reference
    #    - Tier sort companion (<dimension>__sort_) + pivoted sort (<field> 0)
    #    - Dashboard empty string "" filter value
    payload = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": [
                "order_items.status",
                "order_items.total_sale_price",
                "custom_bin_dim",
                "filtered_revenue",
                "rank_calc",
            ],
            "pivots": ["order_items.status"],
            "filters": {
                "order_items.status": "",
                "order_items.sale_price": "[10, 100]",
            },
            "sorts": [
                "order_items.status__sort_ asc",
                "order_items.total_sale_price 0",
            ],
            "dynamic_fields": [
                {
                    "category": "dimension",
                    "dimension": "custom_bin_dim",
                    "label": "High Value Item",
                    "expression": "${order_items.sale_price} > 50",
                    "_kind_hint": "dimension",
                    "_type_hint": "yesno",
                },
                {
                    "category": "measure",
                    "measure": "filtered_revenue",
                    "label": "Filtered Revenue",
                    "based_on": "order_items.total_sale_price",
                    "filters": {"order_items.status": "Complete"},
                    "filter_expression": "${order_items.sale_price} > 20",
                    "_kind_hint": "measure",
                    "_type_hint": "number",
                },
                {
                    "category": "table_calculation",
                    "table_calculation": "rank_calc",
                    "label": "Rank of Sale Price",
                    "based_on": "order_items.total_sale_price",
                    "calculation_type": "rank_of_column",
                    "args": ["order_items.total_sale_price"],
                    "is_disabled": False,
                },
            ],
        }
    }
    res = validate_query(payload, schema)
    assert res.valid is True, f"Unexpected errors: {res.errors}"

    # 2. Invalid ${unknown.field} reference inside expression and invalid custom measure filters
    bad_dyn_payload = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": ["bad_dim", "bad_meas"],
            "dynamic_fields": [
                {
                    "dimension": "bad_dim",
                    "expression": "${order_items.secret_id} + ${nonexistent.col}",
                },
                {
                    "measure": "bad_meas",
                    "based_on": "order_items.total_sale_price",
                    "filters": {"order_items.secret_id": "123"},
                },
            ],
        }
    }
    bad_res = validate_query(bad_dyn_payload, schema)
    assert bad_res.valid is False
    assert any("order_items.secret_id" in e for e in bad_res.errors)
    assert any("nonexistent.col" in e for e in bad_res.errors)


def test_history_pipeline_and_real_queries() -> None:
    from scripts.schema.history import (
        build_history_lookup_query,
        resolve_history_queries,
        validate_history_queries,
    )

    # 1. Verify build_history_lookup_query starts from base_query and sets model/explore/query_ids
    lookup = build_history_lookup_query(
        base_query={
            "model": "system__activity",
            "view": "history",
            "fields": ["query.id", "history.completed_Count"],
            "filters": {
                "history.status": "complete",
                "query.dynamic_fields": "-NULL",
            },
        },
        model="thelook",
        explore="order_items",
        query_ids=[314, 142769],
        limit=10,
    )
    assert lookup["model"] == "system__activity"
    assert lookup["view"] == "history"
    assert "query.slug" in lookup["fields"]
    assert lookup["filters"]["query.model"] == "thelook"
    assert lookup["filters"]["query.view"] == "order_items"
    assert lookup["filters"]["query.id"] == "314,142769"
    assert "query.dynamic_fields" not in lookup["filters"]

    # 2. Verify resolve_history_queries with a mock SDK
    class FakeSDK:
        def query_for_slug(self, slug: str) -> dict:
            return {
                "model": "system__activity",
                "view": "history",
                "fields": ["query.id"],
                "filters": {"history.status": "complete"},
            }

        def run_inline_query(self, result_format: str, body: object) -> str:
            return json.dumps(
                [
                    {
                        "query.id": 142769,
                        "query.slug": "slug_142769",
                        "query.model": "thelook",
                        "query.view": "order_items",
                        "history.completed_Count": 5,
                    }
                ]
            )

        def query(self, slug: str) -> dict:
            assert slug == "slug_142769"
            return {
                "id": 142769,
                "slug": "slug_142769",
                "model": "thelook",
                "view": "order_items",
                "fields": ["order_items.status", "order_items.total_sale_price"],
                "can": {"run": True},
                "share_url": "https://example.looker.com/x/slug_142769",
            }

    schema = build_explore_query_schema("thelook", "order_items", MOCK_EXPLORE)
    resolved = resolve_history_queries(
        FakeSDK(), model="thelook", explore="order_items", query_ids=[142769]
    )
    assert len(resolved) == 1
    assert resolved[0]["query_id"] == 142769
    summary = validate_history_queries(resolved, schema)
    assert summary["valid_queries"] == 1
    assert summary["invalid_queries"] == 0

    # 3. Verify against cached real files if present
    sys_hist_path = Path("tmp/system_activity_history.json")
    if sys_hist_path.exists():
        sys_schema = json.loads(sys_hist_path.read_text(encoding="utf-8"))
        assert sys_schema["title"] == "run_inline_query_system__activity_history"
        assert (
            sys_schema["properties"]["body"]["properties"]["model"]["const"]
            == "system__activity"
        )

    slug_test_path = Path("tmp/slug_query_test.json")
    order_items_path = Path("tmp/order_items.json")
    if slug_test_path.exists() and order_items_path.exists():
        explore_data = json.loads(order_items_path.read_text(encoding="utf-8"))
        real_schema = build_explore_query_schema("thelook", "order_items", explore_data)
        real_queries = json.loads(slug_test_path.read_text(encoding="utf-8"))
        batch = validate_history_queries(real_queries, real_schema)
        assert batch["total_queries"] == 5
        assert batch["valid_queries"] == 5
        assert batch["invalid_queries"] == 0


def test_rust_validator_and_batch() -> None:
    from lkr.schema.validator import get_rust_validator, validate_batch_queries

    schema = build_explore_query_schema("thelook", "order_items", MOCK_EXPLORE)
    rust_val = get_rust_validator(schema)
    assert rust_val is not None

    valid_q = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": ["order_items.status", "order_items.total_sale_price"],
            "subtotals": ["order_items.status"],
        }
    }
    invalid_q = {
        "body": {
            "model": "wrong",
            "view": "order_items",
            "fields": ["order_items.secret_id"],
            "pivots": ["order_items.total_sale_price"],
        }
    }

    res_ok = validate_query(valid_q, schema)
    assert res_ok.valid is True
    assert res_ok.normalized_query is not None
    assert res_ok.normalized_query["body"]["subtotals"] == ["order_items.status"]

    res_bad = validate_query(invalid_q, schema)
    assert res_bad.valid is False
    assert len(res_bad.errors) == 3

    batch_out = validate_batch_queries([valid_q, invalid_q], schema)
    assert len(batch_out) == 2
    assert batch_out[0].valid is True
    assert batch_out[1].valid is False


def test_expression_and_custom_filter_field_validator_on_small_schema() -> None:
    # 1. Small JSON Schema for system__activity::history (testing eiMJQXpAgoXow2JId7whVy)
    small_history_explore = {
        "fields": {
            "dimensions": [
                {"name": "query.id", "type": "number", "hidden": False},
                {"name": "query.slug", "type": "string", "hidden": False},
                {"name": "query.model", "type": "string", "hidden": False},
                {"name": "query.view", "type": "string", "hidden": False},
                {"name": "query.dynamic_fields", "type": "string", "hidden": False},
                {"name": "history.status", "type": "string", "hidden": False},
                {"name": "history.workspace_id", "type": "string", "hidden": False},
            ],
            "measures": [
                {"name": "history.completed_Count", "type": "count", "hidden": False},
            ],
            "filters": [],
            "parameters": [],
        }
    }
    small_history_schema = build_explore_query_schema(
        "system__activity", "history", small_history_explore
    )

    # Valid query matching eiMJQXpAgoXow2JId7whVy + filter_expression: length(${query.dynamic_fields}) > 2
    valid_history_query = {
        "body": {
            "model": "system__activity",
            "view": "history",
            "fields": ["query.id"],
            "filters": {
                "history.status": "complete",
                "history.workspace_id": "production",
            },
            "filter_expression": "length(${query.dynamic_fields}) > 2",
            "sorts": ["query.id desc"],
            "limit": "500",
        }
    }
    res_hist_ok = validate_query(valid_history_query, small_history_schema)
    assert res_hist_ok.valid is True, f"Unexpected errors: {res_hist_ok.errors}"

    # Invalid filter_expression referencing unknown field ${query.filter_expression}
    invalid_history_query = {
        "body": {
            "model": "system__activity",
            "view": "history",
            "fields": ["query.id"],
            "filter_expression": "length(${query.dynamic_fields}) > 2 OR length(${query.filter_expression}) > 0",
        }
    }
    res_hist_bad = validate_query(invalid_history_query, small_history_schema)
    assert res_hist_bad.valid is False
    assert any(
        "$.body.filter_expression" in e and "${query.filter_expression}" in e
        for e in res_hist_bad.errors
    )

    # 2. Small JSON Schema testing chained dynamic_fields ${...}, :total suffix, self-references, and table_calc in SQL filter_expression
    small_order_schema = build_explore_query_schema(
        "thelook", "order_items", MOCK_EXPLORE
    )
    chained_valid_query = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": ["order_items.status", "current_aov", "pct_of_total"],
            "filter_expression": "${order_items.sale_price} > 10 AND ${is_high_value}",
            "dynamic_fields": [
                {
                    "dimension": "is_high_value",
                    "label": "Is High Value",
                    "expression": "${order_items.sale_price} >= 25",
                },
                {
                    "measure": "current_revenue",
                    "label": "Current Revenue",
                    "based_on": "order_items.total_sale_price",
                    "filter_expression": "${order_items.sale_price} > 0 AND ${is_high_value}",
                },
                {
                    "table_calculation": "current_aov",
                    "label": "Current AOV",
                    "expression": "${current_revenue} / 10",
                },
                {
                    "table_calculation": "pct_of_total",
                    "label": "Pct of Total",
                    "expression": "${current_aov} / ${order_items.total_sale_price:total}",
                },
            ],
        }
    }
    res_chain_ok = validate_query(chained_valid_query, small_order_schema)
    assert res_chain_ok.valid is True, f"Unexpected errors: {res_chain_ok.errors}"

    # Invalid ${...} cases: empty ${}, self-reference, unknown field, and table_calculation inside body.filter_expression
    bad_refs_query = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": ["order_items.status"],
            "filter_expression": "${tc_after_sql} > 0 AND ${} > 1 AND ${unknown.dim} = 1",
            "dynamic_fields": [
                {
                    "table_calculation": "tc_after_sql",
                    "label": "Self Ref TC",
                    "expression": "${tc_after_sql} + ${order_items.secret_id}",
                }
            ],
        }
    }
    res_bad_refs = validate_query(bad_refs_query, small_order_schema)
    assert res_bad_refs.valid is False
    err_text = "\n".join(res_bad_refs.errors)
    assert "empty field reference '${}'" in err_text
    assert "cannot reference itself in '${tc_after_sql}'" in err_text
    assert "post-query table_calculation '${tc_after_sql}'" in err_text
    assert "${order_items.secret_id}" in err_text
    assert "${unknown.dim}" in err_text

    # 3. column_limit without pivots emits a warning (does not fail valid)
    col_limit_warn_res = validate_query(
        {
            "body": {
                "model": "thelook",
                "view": "order_items",
                "fields": ["order_items.status", "order_items.total_sale_price"],
                "column_limit": "50",
            }
        },
        small_order_schema,
    )
    assert col_limit_warn_res.valid is True
    assert len(col_limit_warn_res.warnings) == 1
    assert "$.body.column_limit" in col_limit_warn_res.warnings[0]


def test_vgr_edge_cases(tmp_path: Path) -> None:
    # 1. Missing --explore-file exits with code 1 cleanly
    missing_res = runner.invoke(
        app,
        [
            "schema",
            "generate",
            "--model=thelook",
            "--explore=order_items",
            f"--explore-file={tmp_path / 'does_not_exist.json'}",
        ],
    )
    assert missing_res.exit_code == 1

    # 2. Invalid JSON in --explore-file exits with code 1 cleanly
    bad_file = tmp_path / "corrupt.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    bad_json_res = runner.invoke(
        app,
        [
            "schema",
            "generate",
            "--model=thelook",
            "--explore=order_items",
            f"--explore-file={bad_file}",
        ],
    )
    assert bad_json_res.exit_code == 1

    # 3. Non-object CustomMeasure.filters rejected with explicit error
    schema = build_explore_query_schema("thelook", "order_items", MOCK_EXPLORE)
    non_obj_filters_res = validate_query(
        {
            "body": {
                "model": "thelook",
                "view": "order_items",
                "fields": ["cm_bad_filters"],
                "dynamic_fields": [
                    {
                        "measure": "cm_bad_filters",
                        "based_on": "order_items.total_sale_price",
                        "filters": "not_an_object",
                    }
                ],
            }
        },
        schema,
    )
    assert non_obj_filters_res.valid is False
    assert any(
        "$.body.dynamic_fields[0].filters: expected object" in e
        for e in non_obj_filters_res.errors
    )

    # 4. DateTimeFilterExpression multi-comma input completes without backtracking
    dt_pat = re.compile(
        FILTER_EXPRESSION_DEFS["DateTimeFilterExpression"]["pattern"]
    )
    assert dt_pat.match("today, yesterday, 7 days, this month")
    assert not dt_pat.match("invalid_prefix," + "a," * 40 + "!")

    # 5. CLI lkr schema validate accepts a JSON array of queries (batch validation)
    explore_path = tmp_path / "mock_explore.json"
    explore_path.write_text(json.dumps(MOCK_EXPLORE), encoding="utf-8")
    valid_arr = [
        {"model": "thelook", "view": "order_items", "fields": ["order_items.status"]},
        {"model": "thelook", "view": "order_items", "fields": ["order_items.total_sale_price"]},
    ]
    arr_ok_res = runner.invoke(
        app,
        [
            "schema",
            "validate",
            f"--explore-file={explore_path}",
            f"--query={json.dumps(valid_arr)}",
        ],
    )
    assert arr_ok_res.exit_code == 0
    arr_ok_data = json.loads(arr_ok_res.stdout)
    assert isinstance(arr_ok_data, list)
    assert len(arr_ok_data) == 2
    assert all(item["valid"] is True for item in arr_ok_data)

    mixed_arr = [
        {"model": "thelook", "view": "order_items", "fields": ["order_items.status"]},
        {"model": "thelook", "view": "order_items", "fields": ["order_items.secret_id"]},
    ]
    arr_fail_res = runner.invoke(
        app,
        [
            "schema",
            "validate",
            f"--explore-file={explore_path}",
            f"--query={json.dumps(mixed_arr)}",
        ],
    )
    assert arr_fail_res.exit_code == 1
    arr_fail_data = json.loads(arr_fail_res.stdout)
    assert arr_fail_data[0]["valid"] is True
    assert arr_fail_data[1]["valid"] is False






