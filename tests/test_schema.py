import copy
import json
import re
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

import lkr.schema as _schema
import lkr.schema.builder as _builder
import lkr.schema.dynamic_fields as _dyn_fields
import lkr.schema.fields as _fields
import lkr.schema.filter_expressions as _filter_exprs
from lkr.main import app

build_explore_query_schema = _schema.build_explore_query_schema
build_schema_context = _schema.build_schema_context
execute_looker_query = _schema.execute_looker_query
validate_merge_query = _schema.validate_merge_query
validate_query = _schema.validate_query
build_query_body_schema = _builder.build_query_body_schema
build_custom_dimension_schema = _dyn_fields.build_custom_dimension_schema
build_custom_measure_schema = _dyn_fields.build_custom_measure_schema
build_dynamic_fields_schema = _dyn_fields.build_dynamic_fields_schema
build_table_calculation_schema = _dyn_fields.build_table_calculation_schema
build_fields_schema = _fields.build_fields_schema
build_fill_fields_schema = _fields.build_fill_fields_schema
build_pivots_schema = _fields.build_pivots_schema
build_sorts_schema = _fields.build_sorts_schema
build_subtotals_schema = _fields.build_subtotals_schema
extract_visible_explore_fields = _fields.extract_visible_explore_fields
is_visible_field = _fields.is_visible_field
FILTER_EXPRESSION_DEFS = _filter_exprs.FILTER_EXPRESSION_DEFS
build_filter_property_schema = _filter_exprs.build_filter_property_schema
build_filters_schema = _filter_exprs.build_filters_schema
classify_filter_expression_ref = _filter_exprs.classify_filter_expression_ref
extract_enum_values = _filter_exprs.extract_enum_values

runner = CliRunner()


def _dig(obj: object, *keys: str | int) -> object:
    cur = obj
    for k in keys:
        if isinstance(k, int):
            assert isinstance(cur, list)
            cur = cur[k]
        else:
            assert isinstance(cur, dict)
            cur = cur[k]
    return cur


def test_is_visible_field_and_extract_visible_explore_fields() -> None:
    assert is_visible_field({"name": "users.id", "hidden": False}) is True
    assert is_visible_field({"name": "users.id", "hidden": True}) is False
    assert is_visible_field({"name": "", "hidden": False}) is False
    assert is_visible_field({}) is False

    raw: dict[str, object] = {
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


def test_build_fields_pivots_sorts_fill_and_subtotals_schema() -> None:
    fields_schema = build_fields_schema(["d1", "d2"], ["m1"])
    assert _dig(fields_schema, "items", "enum") == ["d1", "d2", "m1"]

    pivots_schema = build_pivots_schema(["d1", "d2"])
    pivots_enum = _dig(pivots_schema, "items", "enum")
    assert pivots_enum == ["d1", "d2"]
    assert isinstance(pivots_enum, list) and "m1" not in pivots_enum

    fill_schema = build_fill_fields_schema(["d1", "d2"])
    assert _dig(fill_schema, "items", "enum") == ["d1", "d2"]

    subtotals_schema = build_subtotals_schema(["d1", "d2"])
    assert _dig(subtotals_schema, "items", "enum") == ["d1", "d2"]

    sorts_schema = build_sorts_schema(["d1", "m1"])
    sort_pat_raw = _dig(sorts_schema, "items", "pattern")
    assert isinstance(sort_pat_raw, str)
    sort_pat = re.compile(sort_pat_raw)
    assert sort_pat.match("d1")
    assert sort_pat.match("d1 desc")
    assert sort_pat.match("m1 desc 0")
    assert sort_pat.match("__UNSORTED__")
    assert not sort_pat.match("unknown_field desc")


def test_extract_enum_values_and_classify_filter_expression_ref() -> None:
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
    for ref, types in (
        ("NumberFilterExpression", ("duration_day", "date_month_num", "date_hour_of_day")),
        ("DateTimeFilterExpression", ("date", "date_year", "date_minute15")),
        ("StringFilterExpression", ("string", "date_day_of_week", "date_month_name")),
    ):
        for t in types:
            assert classify_filter_expression_ref({"type": t}) == f"#/$defs/{ref}"


def test_filter_expression_patterns() -> None:
    for name in (
        "DateTimeFilterExpression",
        "NumberFilterExpression",
        "LocationFilterExpression",
    ):
        pat_raw = _dig(FILTER_EXPRESSION_DEFS, name, "pattern")
        examples = _dig(FILTER_EXPRESSION_DEFS, name, "examples")
        assert isinstance(pat_raw, str) and isinstance(examples, list)
        pat = re.compile(pat_raw)
        for ex in examples:
            assert isinstance(ex, str) and pat.match(ex), (
                f"{name} pattern failed on {ex}"
            )


def test_build_filter_property_and_filters_schema() -> None:
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
    assert isinstance(props, dict)
    assert set(props.keys()) == {"d1", "m1", "f1", "p1"}
    assert _dig(props, "d1", "$ref") == "#/$defs/StringFilterExpression"
    assert _dig(props, "m1", "$ref") == "#/$defs/NumberFilterExpression"
    assert _dig(props, "f1", "$ref") == "#/$defs/DateTimeFilterExpression"
    assert _dig(props, "p1", "enum") == ["1"]


def test_build_dynamic_fields_schema() -> None:
    cd = build_custom_dimension_schema()
    assert isinstance(cd["required"], list) and "dimension" in cd["required"]

    cm = build_custom_measure_schema(["d1", "d2"])
    assert _dig(cm, "properties", "based_on", "enum") == ["d1", "d2"]
    assert isinstance(cm["required"], list) and "measure" in cm["required"]

    tc = build_table_calculation_schema()
    assert (
        isinstance(tc["required"], list)
        and "table_calculation" in tc["required"]
    )

    df = build_dynamic_fields_schema(["d1"])
    one_of = _dig(df, "items", "oneOf")
    assert isinstance(one_of, list) and len(one_of) == 3


def test_schema_generate_and_validate_pipeline(tmp_path: Path) -> None:
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
    assert _dig(body_schema, "properties", "model", "const") == "thelook"
    assert _dig(body_schema, "properties", "view", "const") == "order_items"
    assert _dig(body_schema, "properties", "limit", "default") == "500"

    schema = build_explore_query_schema("thelook", "order_items", data)
    assert _dig(schema, "properties", "limit", "default") == 500

    # Valid query with dynamic_fields (both CustomDimension in pivots/fields and TableCalculation in fields)
    valid_payload: dict[str, object] = {
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
        _dig(valid_res.normalized_query, "body", "dynamic_fields"), str
    )

    # Multi-error payload: pipeline must collect EVERY error without stopping early
    invalid_payload: dict[str, object] = {
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


MOCK_EXPLORE: dict[str, object] = {
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
    payload: dict[str, object] = {
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
    bad_dyn_payload: dict[str, object] = {
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
        def query_for_slug(self, slug: str) -> dict[str, object]:
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

        def query(self, slug: str) -> dict[str, object]:
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
    import lkr.schema.validator as _val

    get_rust_validator = _val.get_rust_validator
    validate_batch_queries = _val.validate_batch_queries

    schema = build_explore_query_schema("thelook", "order_items", MOCK_EXPLORE)
    rust_val = get_rust_validator(schema)
    assert rust_val is not None

    valid_q: dict[str, object] = {
        "body": {
            "model": "thelook",
            "view": "order_items",
            "fields": ["order_items.status", "order_items.total_sale_price"],
            "subtotals": ["order_items.status"],
        }
    }
    invalid_q: dict[str, object] = {
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
    assert _dig(res_ok.normalized_query, "body", "subtotals") == ["order_items.status"]

    res_bad = validate_query(invalid_q, schema)
    assert res_bad.valid is False
    assert len(res_bad.errors) == 3

    batch_out = validate_batch_queries([valid_q, invalid_q], schema)
    assert len(batch_out) == 2
    assert batch_out[0].valid is True
    assert batch_out[1].valid is False


def test_expression_and_custom_filter_field_validator_on_small_schema() -> None:
    # 1. Small JSON Schema for system__activity::history (testing eiMJQXpAgoXow2JId7whVy)
    small_history_explore: dict[str, object] = {
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
    valid_history_query: dict[str, object] = {
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
    invalid_history_query: dict[str, object] = {
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
    chained_valid_query: dict[str, object] = {
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
    bad_refs_query: dict[str, object] = {
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

    # 4. Unwrap lookml-to-api wrapper payload {"lookml_model_explores": {"model::explore": {...}}}
    wrapped_schema = build_explore_query_schema(
        "thelook",
        "order_items",
        {"all_lookml_models": [], "lookml_model_explores": {"thelook::order_items": MOCK_EXPLORE}},
    )
    fields_enum = _dig(
        wrapped_schema,
        "properties",
        "body",
        "properties",
        "fields",
        "items",
        "enum",
    )
    assert isinstance(fields_enum, list)
    assert "order_items.total_sale_price" in fields_enum
    assert any(
        "$.body.dynamic_fields[0].filters: expected object" in e
        for e in non_obj_filters_res.errors
    )

    # 4. DateTimeFilterExpression multi-comma input completes without backtracking
    dt_pat_raw = _dig(FILTER_EXPRESSION_DEFS, "DateTimeFilterExpression", "pattern")
    assert isinstance(dt_pat_raw, str)
    dt_pat = re.compile(dt_pat_raw)
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

    # 6. CLI lkr schema validate accepts multi-explore api_all.json + query map dict (--query-file)
    api_all_path = tmp_path / "api_all.json"
    api_all_path.write_text(
        json.dumps({"all_lookml_models": [], "lookml_model_explores": {"thelook::order_items": MOCK_EXPLORE}}),
        encoding="utf-8",
    )
    qmap_ok = tmp_path / "inline_queries.json"
    qmap_ok.write_text(
        json.dumps({"0": {"model": "thelook", "view": "order_items", "fields": ["order_items.status"]}}),
        encoding="utf-8",
    )
    map_ok_res = runner.invoke(
        app,
        ["schema", "validate", "-m", "thelook", f"--explore-file={api_all_path}", f"--query-file={qmap_ok}"],
    )
    assert map_ok_res.exit_code == 0, map_ok_res.output
    map_ok_data = json.loads(map_ok_res.stdout)
    assert map_ok_data["0"]["valid"] is True and map_ok_data["0"]["errors"] == []

    qmap_missing = tmp_path / "inline_missing.json"
    qmap_missing.write_text(
        json.dumps({"0": {"model": "thelook", "view": "no_such_explore", "fields": ["x.y"]}}),
        encoding="utf-8",
    )
    map_miss_res = runner.invoke(
        app,
        ["schema", "validate", "-m", "thelook", f"--explore-file={api_all_path}", f"--query-file={qmap_missing}"],
    )
    assert map_miss_res.exit_code == 1
    assert "no_such_explore" in json.loads(map_miss_res.stdout)["0"]["errors"][0]


def test_py_explore_validator_windows_fallback_and_parity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import lkr.mcp.utils as mcp_utils
    import lkr.schema.validator as val_mod
    from lkr.schema.validator import _PyExploreValidator

    explore: dict[str, object] = {
        "fields": {
            **cast("dict[str, object]", MOCK_EXPLORE["fields"]),
            "parameters": [
                {
                    "name": "order_items.metric_param",
                    "parameter": True,
                    "has_allowed_values": True,
                    "enumerations": [{"label": "Rev", "value": "rev"}, {"label": "Cnt", "value": "cnt"}],
                }
            ],
        }
    }
    schema = build_explore_query_schema("thelook", "order_items", explore)
    schema_json = json.dumps(schema, sort_keys=True)
    py_val = _PyExploreValidator(schema_json)

    cases = [
        # Valid full query with int limit coercion, read-only keys stripped, dynamic_fields, sorts, subtotals
        {
            "id": 99,
            "slug": "ro",
            "model": "thelook",
            "view": "order_items",
            "limit": 100,
            "fields": ["order_items.status", "order_items.total_sale_price", "cd1", "cm1", "tc1", "tc2"],
            "pivots": ["order_items.status", "cd1"],
            "fill_fields": ["order_items.status"],
            "subtotals": ["order_items.status"],
            "filters": {
                "order_items.status": "Complete",
                "order_items.sale_price": ">=10",
                "order_items.metric_param": "rev",
            },
            "sorts": ["__UNSORTED__", "order_items.status__sort_ asc", "tc1 desc"],
            "filter_expression": "${order_items.sale_price} > 5 AND ${cd1}",
            "dynamic_fields": [
                {"dimension": "cd1", "expression": "${order_items.sale_price} > 20"},
                {
                    "measure": "cm1",
                    "type": "sum",
                    "based_on": "order_items.sale_price",
                    "filters": {"order_items.metric_param": "rev"},
                },
                {
                    "table_calculation": "tc1",
                    "calculation_type": "rank_of_column",
                    "args": ["order_items.total_sale_price"],
                    "based_on": "order_items.total_sale_price",
                },
                {
                    "table_calculation": "tc2",
                    "expression": "${tc1} / ${order_items.total_sale_price:row_total} + ${cm1:total}",
                },
            ],
        },
        # Warning: column_limit without pivots + JSON-encoded dynamic_fields string
        {
            "body": {
                "model": "thelook",
                "view": "order_items",
                "fields": ["order_items.status"],
                "column_limit": 25,
                "dynamic_fields": json.dumps([{"dimension": "d_str", "based_on": "order_items.status"}]),
            }
        },
        # Exhaustive invalid branches for coverage and Rust parity
        "not_an_object",
        {"body": "not_an_object"},
        {
            "unknown_top": 1,
            "result_format": "bogus_fmt",
            "body": {
                "model": "wrong",
                "view": "wrong",
                "unknown_body": 1,
                "fields": [123, "order_items.secret_id"],
                "pivots": [123, "order_items.total_sale_price", "cm_bad", "unknown.dim"],
                "filters": {
                    "unknown.f": "x",
                    "order_items.sale_price": "not_a_num",
                    "order_items.metric_param": "bad_enum",
                    "order_items.status": 123,
                },
                "sorts": [123, "bad sort !!", "unknown.sort desc"],
                "fill_fields": [123, "order_items.total_sale_price"],
                "subtotals": [123, "order_items.total_sale_price"],
                "filter_expression": "${} + ${tc_bad} + ${unknown.ref}",
                "dynamic_fields": [
                    "not_obj",
                    {"label": "no_kind"},
                    {"dimension": "cd_empty", "based_on": "unknown.bo"},
                    {
                        "measure": "cm_bad",
                        "type": "invalid_mtype",
                        "based_on": "unknown.bo",
                        "filters": "not_obj",
                    },
                    {
                        "table_calculation": "tc_bad",
                        "source_field": "unknown.sf",
                        "args": ["unknown.arg"],
                        "expression": "${tc_bad}",
                    },
                    {"dimension": "cd_tc_ref", "expression": "${tc_bad}"},
                ],
            },
        },
        {"body": {"fields": "bad", "pivots": "bad", "filters": "bad", "sorts": "bad", "fill_fields": "bad", "subtotals": "bad", "filter_expression": 123, "dynamic_fields": 123}},
        {"body": {"dynamic_fields": "{bad json"}},
        {"body": {"dynamic_fields": '{"not": "array"}'}},
    ]

    serialized = [json.dumps(c) for c in cases] + ["{corrupt_query_json"]
    py_out = py_val.validate_batch_json(serialized)
    assert py_out[0][0] is True and py_out[0][3] is not None
    assert py_out[1][0] is True and len(py_out[1][2]) == 1
    assert all(not r[0] for r in py_out[2:])

    if val_mod._schema_rs is not None:
        rs_val = val_mod._schema_rs.RustExploreValidator(schema_json)
        rs_out = rs_val.validate_batch_json(serialized)
        for (p_ok, p_err, p_warn, p_norm), (r_ok, r_err, r_warn, r_norm) in zip(py_out, rs_out, strict=True):
            assert p_ok == r_ok
            assert sorted(p_warn) == sorted(r_warn)
            assert len(p_err) == len(r_err)
            assert (json.loads(p_norm) if p_norm else None) == (json.loads(r_norm) if r_norm else None)

    # Simulate Windows / non-ELF platform where _schema_rs is unavailable
    val_mod._compile_validator.cache_clear()
    monkeypatch.setattr(val_mod, "_schema_rs", None)
    try:
        res = validate_query({"fields": ["order_items.status"]}, schema)
        assert res.valid is True
        assert res.normalized_query is not None
        assert _dig(res.normalized_query, "body", "model") == "thelook"
    finally:
        val_mod._compile_validator.cache_clear()

    # Verify Windows-safe MCP filename sanitization for Looker base URLs containing ':' and '/'
    monkeypatch.setattr(mcp_utils, "db_loc", tmp_path)
    p_search = mcp_utils.get_database_search_file("https://acme.cloud.looker.com:19999")
    p_reg = mcp_utils.get_connection_registry_file("table", "https://acme.cloud.looker.com:19999")
    assert ":" not in p_search.name and "/" not in p_search.name and p_search.exists()
    assert ":" not in p_reg.name and "/" not in p_reg.name


def test_dynamic_fields_sync_and_filter_coercion_parity() -> None:
    import lkr.schema.validator as val_mod

    explore_data: dict[str, object] = {
        "fields": {
            "dimensions": [
                {"name": "order_items.status", "type": "string", "hidden": False},
                {"name": "order_items.created_date", "type": "date_date", "hidden": False},
                {"name": "order_items.created_year", "type": "date_year", "hidden": False},
                {"name": "order_items.sale_price", "type": "number", "hidden": False},
            ],
            "measures": [
                {"name": "order_items.total_sale_price", "type": "sum", "hidden": False},
            ],
            "filters": [],
            "parameters": [],
        }
    }
    schema = build_explore_query_schema("thelook", "order_items", explore_data)
    schema_json = json.dumps(schema, sort_keys=True)
    py_val = val_mod._PyExploreValidator(schema_json)

    query_payload: dict[str, object] = {
        "fields": ["pct_of_rev"],
        "filters": {
            "order_items.created_year": ">=2024",
            "order_items.sale_price": "10 to 50",
            "order_items.status": "NOT NULL",
        },
        "dynamic_fields": [
            {
                "dimension": "price_bucket",
                "expression": 'if(${order_items.sale_price} >= 100, "High", "Low")',
            },
            {
                "measure": "returned_rev",
                "based_on": "order_items.sale_price",
                "type": "sum",
                "filter_expression": "",
                "filters": {
                    "order_items.status": "IS NULL",
                    "order_items.created_year": "<=2024",
                },
            },
            {
                "table_calculation": "pct_of_rev",
                "expression": "${returned_rev} / ${order_items.total_sale_price}",
            },
        ],
    }

    res = validate_query(query_payload, schema)
    assert res.valid is True, res.errors
    assert res.normalized_query is not None
    body = res.normalized_query["body"]
    assert isinstance(body, dict)
    # TableCalculation removed from fields; CustomDimension, CustomMeasure, and referenced static measure auto-injected
    assert body["fields"] == ["price_bucket", "returned_rev", "order_items.total_sale_price"]
    assert body["filters"] == {
        "order_items.created_date": "after 2024-01-01",
        "order_items.sale_price": "[10, 50]",
        "order_items.status": "-NULL",
    }
    assert isinstance(body["dynamic_fields"], str)
    dyn = json.loads(body["dynamic_fields"])
    assert dyn[0]["label"] == "price_bucket"
    assert dyn[1]["label"] == "returned_rev"
    assert "filter_expression" not in dyn[1]
    assert dyn[1]["filters"] == {
        "order_items.status": "NULL",
        "order_items.created_date": "before 2024-12-31",
    }
    assert dyn[2]["label"] == "pct_of_rev"

    # Additional filter coercion patterns (BETWEEN, >YYYY-MM-DD, <=YYYY-MM-DD)
    res2 = validate_query(
        {
            "fields": ["order_items.status"],
            "filters": {
                "order_items.created_date": "BETWEEN '2024-01-01' AND '2024-06-30'",
                "order_items.sale_price": "BETWEEN 5 AND 25.5",
                "order_items.status": "!= NULL",
            },
        },
        schema,
    )
    assert res2.valid is True, res2.errors
    assert res2.normalized_query is not None
    assert _dig(res2.normalized_query, "body", "filters") == {
        "order_items.created_date": "2024-01-01 to 2024-06-30",
        "order_items.sale_price": "[5, 25.5]",
        "order_items.status": "-NULL",
    }

    # Verify byte-for-byte parity between Python and Rust validators on normalization
    serialized = [json.dumps(query_payload), json.dumps({"fields": ["order_items.status"], "filters": {"order_items.created_date": ">2024-03-01"}})]
    py_out = py_val.validate_batch_json(serialized)
    if val_mod._schema_rs is not None:
        rs_val = val_mod._schema_rs.RustExploreValidator(schema_json)
        rs_out = rs_val.validate_batch_json(serialized)
        for (p_ok, p_err, p_warn, p_norm), (r_ok, r_err, r_warn, r_norm) in zip(py_out, rs_out, strict=True):
            assert p_ok == r_ok
            assert p_err == r_err
            assert p_warn == r_warn
            assert p_norm is not None and r_norm is not None
            assert json.loads(p_norm) == json.loads(r_norm)


def test_validate_merge_query_and_execute_looker_query() -> None:
    explores_map: dict[str, object] = {
        "order_items": {
            "name": "order_items",
            "view_name": "order_items",
            "joins": [{"name": "products", "relationship": "many_to_one", "sql_on": "${order_items.product_id} = ${products.id}"}],
            "fields": {
                "dimensions": [
                    {"name": "products.category", "type": "string", "hidden": False},
                    {"name": "order_items.status", "type": "string", "hidden": False},
                ],
                "measures": [
                    {"name": "order_items.total_sale_price", "type": "sum", "hidden": False},
                ],
            },
        },
        "inventory_items": {
            "name": "inventory_items",
            "view_name": "inventory_items",
            "joins": [{"name": "products", "relationship": "many_to_one", "sql_on": "${inventory_items.product_id} = ${products.id}"}],
            "fields": {
                "dimensions": [
                    {"name": "products.category", "type": "string", "hidden": False},
                ],
                "measures": [
                    {"name": "inventory_items.count", "type": "count", "hidden": False},
                ],
            },
        },
    }

    # 1. Single-query fallback across candidate_explores when Explore 'view' is initially wrong
    single_res = validate_merge_query(
        {"view": "wrong_explore", "fields": ["inventory_items.count"]},
        "thelook",
        explores_map,
        candidate_explores=["order_items", "inventory_items"],
    )
    assert single_res.valid is True
    assert single_res.normalized_query is not None
    assert _dig(single_res.normalized_query, "body", "view") == "inventory_items"

    # 2. Multi-Explore source_queries validation with shared-key inference & auto-injection
    merge_payload: dict[str, object] = {
        "source_queries": [
            {
                "name": "sales",
                "view": "order_items",
                "fields": ["products.category", "order_items.total_sale_price"],
            },
            {
                "name": "stock",
                "view": "inventory_items",
                "fields": ["products.category", "inventory_items.count"],
            },
        ],
        "join_type": "left",
        "sorts": ["order_items.total_sale_price desc"],
        "limit": 5,
        "column_limit": 50,
        "total": True,
        "vis_config": {"type": "looker_column", "advanced_vis_config": "{chart: {}}"},
    }
    merge_res = validate_merge_query(merge_payload, "thelook", explores_map)
    assert merge_res.valid is True, merge_res.errors
    norm = merge_res.normalized_query
    assert norm is not None
    assert norm["limit"] == "5" and norm["column_limit"] == "50"
    assert norm["total"] is True
    assert isinstance(norm["source_queries"], list)
    assert all(
        _dig(sq, "query", "total") is True for sq in norm["source_queries"]
    )
    assert _dig(norm, "source_queries", 1, "merge_fields") == [
        {"source_field_name": "products.category", "field_name": "products.category"}
    ]

    # 3. Mode 1: Zero queries raises ValueError; single query calls run_inline_query("json", ...)
    empty_specs: tuple[dict[str, object], ...] = ({}, {"body": {}}, {"source_queries": []})
    for empty_spec in empty_specs:
        with pytest.raises(ValueError, match="At least one query"):
            execute_looker_query(object(), empty_spec)

    # Validation inside execute_looker_query when explores_data is provided
    with pytest.raises(ValueError, match="unknown"):
        execute_looker_query(
            object(),
            {"model": "thelook", "view": "order_items", "fields": ["order_items.unknown_field"]},
            explores_data=explores_map,
        )

    # 4. Mode 2, 3, & 4: SQL Runner CTE merge (no final TCs vs. with final TCs via sql__{slug})
    class SqlRunnerSDK:
        def __init__(self) -> None:
            self.created_sql: list[dict[str, object]] = []
            self.inline_calls: list[tuple[str, dict[str, object]]] = []
            self.fail_model_create = False

        def lookml_model_explore(
            self, model_name: str, explore_name: str, fields: str | None = None
        ) -> dict[str, str]:
            return {"connection_name": "bq_conn"}

        def create_sql_query(self, body: dict[str, object]) -> dict[str, str]:
            if self.fail_model_create and "model_name" in body:
                raise RuntimeError("Model has errors")
            self.created_sql.append(body)
            return {"slug": "slug123"}

        def run_sql_query(self, slug: str, result_format: str) -> str:
            assert slug == "slug123" and result_format == "json"
            return json.dumps([
                {
                    "products_category": "Accessories",
                    "order_items_total_sale_price": 300.0,
                    "inventory_items_count": 50,
                },
                {
                    "products_category": "Jeans",
                    "order_items_total_sale_price": 120.0,
                    "inventory_items_count": None,
                },
            ])

        def run_inline_query(
            self,
            result_format: str,
            body: dict[str, object],
            limit: int | None = None,
        ) -> str:
            self.inline_calls.append((result_format, body))
            if result_format == "sql":
                if body["view"] == "order_items":
                    return "SELECT products.category AS products_category, SUM(sale_price) AS order_items_total_sale_price FROM orders GROUP BY 1 LIMIT 100000;"
                return "SELECT products.category AS products_category, COUNT(*) AS inventory_items_count FROM inv GROUP BY 1 LIMIT 500;"
            if body.get("model") == "sql__slug123":
                assert body["view"] == "sql_runner_query"
                return json.dumps([
                    {
                        "sql_runner_query.products_category": "Accessories",
                        "sql_runner_query.order_items_total_sale_price": 300.0,
                        "sql_runner_query.inventory_items_count": 50,
                        "rev_per_unit": 6.0,
                    }
                ])
            if body["view"] == "order_items":
                return json.dumps([
                    {"products.category": "Jeans", "order_items.total_sale_price": 120.0},
                    {"products.category": "Accessories", "order_items.total_sale_price": 300.0},
                ])
            return json.dumps([
                {"products.category": "Accessories", "inventory_items.count": 50},
            ])

    sql_sdk = SqlRunnerSDK()

    # Single query (direct & 1-element source_queries)
    assert len(execute_looker_query(sql_sdk, single_res.normalized_query, explores_data=explores_map)) == 1
    assert len(execute_looker_query(sql_sdk, {"source_queries": [single_res.normalized_query]})) == 1

    # Mode 2 + 3: Multi-query CTE generation, -1 LIMIT 100000 stripping, source-query TC warning, SQL Runner execution
    spec_with_src_tc = copy.deepcopy(norm)
    src_q0 = _dig(spec_with_src_tc, "source_queries", 0, "query")
    assert isinstance(src_q0, dict)
    src_q0["limit"] = "-1"
    src_q0["dynamic_fields"] = json.dumps([
        {"dimension": "custom_cat", "expression": "${products.category}"},
        {"table_calculation": "ignored_src_tc", "expression": "${order_items.total_sale_price} * 2"},
    ])
    assert isinstance(src_q0["fields"], list)
    src_q0["fields"].append("ignored_src_tc")
    src_q0["sorts"] = ["ignored_src_tc desc"]

    with pytest.warns(UserWarning, match="Table calculations on source queries are ignored"):
        cte_rows = execute_looker_query(sql_sdk, spec_with_src_tc)

    assert len(cte_rows) == 2
    assert cte_rows[0] == {
        "products.category": "Accessories",
        "order_items.total_sale_price": 300.0,
        "inventory_items.count": 50,
    }
    gen_sql = sql_sdk.created_sql[-1]["sql"]
    assert isinstance(gen_sql, str)
    assert "WITH cte_0 AS (" in gen_sql
    assert "LIMIT 100000" not in gen_sql  # Stripped on limit="-1"
    assert "LIMIT 500" in gen_sql  # Preserved oncte_1 without -1 limit
    assert "LEFT JOIN cte_1 ON cte_0.products_category = cte_1.products_category" in gen_sql
    assert "ORDER BY order_items_total_sale_price DESC" in gen_sql
    assert "LIMIT 5" in gen_sql

    # Mode 4: Top-level table calculations on final select -> sql__{slug} / sql_runner_query Explore query
    sql_sdk.fail_model_create = True  # Also exercises lookml_model_explore connection_name fallback
    spec_final_tc = {
        **norm,
        "fields": ["products.category", "order_items.total_sale_price"],
        "table_calculations": [
            {
                "name": "rev_per_unit",
                "expression": "${order_items.total_sale_price} / ${inventory_items.count:total}",
                "based_on": "order_items.total_sale_price",
                "args": ["inventory_items.count"],
            }
        ],
        "sorts": ["order_items.total_sale_price desc", "rev_per_unit desc"],
    }
    tc_rows = execute_looker_query(sql_sdk, spec_final_tc, explores_data=explores_map)
    assert tc_rows == [
        {
            "products.category": "Accessories",
            "order_items.total_sale_price": 300.0,
            "inventory_items.count": 50,
            "rev_per_unit": 6.0,
        }
    ]
    _, sql_explore_body = sql_sdk.inline_calls[-1]
    assert sql_explore_body["model"] == "sql__slug123"
    assert sql_explore_body["view"] == "sql_runner_query"
    assert sql_explore_body["total"] is True
    assert isinstance(sql_explore_body["dynamic_fields"], str)
    assert "${sql_runner_query.order_items_total_sale_price} / ${sql_runner_query.inventory_items_count:total}" in (
        sql_explore_body["dynamic_fields"]
    )
    assert sql_explore_body["sorts"] == ["sql_runner_query.order_items_total_sale_price desc", "rev_per_unit desc"]

    # 5. Fallback when user lacks SQL Runner permissions: warns about row limits & unprocessed table calculations
    class NoSqlRunnerPermissionsSDK:
        def run_inline_query(
            self,
            result_format: str,
            body: dict[str, object],
            limit: int | None = None,
        ) -> str:
            view = body["view"]
            if view == "order_items":
                return json.dumps([
                    {"products.category": "Jeans", "order_items.total_sale_price": 120.0},
                    {"products.category": "Accessories", "order_items.total_sale_price": 300.0},
                ])
            return json.dumps([
                {"products.category": "Accessories", "inventory_items.count": 50},
            ])

    sdk = NoSqlRunnerPermissionsSDK()
    with pytest.warns(UserWarning, match="falling back to Python merge with source query row limits applied"):
        rows = execute_looker_query(sdk, norm, explores_data=explores_map)
    assert len(rows) == 2
    assert rows[0]["products.category"] == "Accessories"
    assert rows[0]["inventory_items.count"] == 50
    assert rows[1]["products.category"] == "Jeans"
    assert rows[1]["inventory_items.count"] is None

    with pytest.warns(UserWarning) as rec_warns:
        rows_inner = execute_looker_query(
            sdk,
            {
                **norm,
                "join_type": "inner",
                "limit": "1",
                "dynamic_fields": [{"table_calculation": "tc_ignored", "expression": "${order_items.total_sale_price} * 2"}],
            },
            explores_data=explores_map,
        )
    warn_msgs = [str(w.message) for w in rec_warns]
    assert any("row limits applied" in m for m in warn_msgs)
    assert any("cannot process table calculations" in m for m in warn_msgs)
    assert len(rows_inner) == 1
    assert rows_inner[0]["products.category"] == "Accessories"
    with pytest.warns(UserWarning, match="row limits applied"):
        assert len(execute_looker_query(sdk, {**norm, "limit": "-1"})) == 2

    # Invalid merge query cases
    bad_merge = validate_merge_query(
        {"source_queries": [{"view": "order_items", "fields": ["products.category"]}], "join_type": "outer"},
        "thelook",
        explores_map,
    )
    assert bad_merge.valid is False
    assert any("at least 2" in e for e in bad_merge.errors)
    assert any("join_type" in e for e in bad_merge.errors)


def test_build_schema_context_and_cli_commands(tmp_path: Path) -> None:
    explores_list: list[dict[str, object]] = [
        {
            "name": "order_items",
            "label": "Order Items",
            "description": "Order line items and revenue",
            "view_name": "order_items",
            "joins": [
                {"name": "products", "relationship": "many_to_one", "sql_on": "${order_items.product_id} = ${products.id}"},
                {"name": "users", "relationship": "many_to_one", "sql_on": "${order_items.user_id} = ${users.id}"},
            ],
            "fields": {
                "dimensions": [
                    {"name": "products.category", "type": "string", "label": "Category", "hidden": False},
                    {"name": "users.id", "type": "number", "label": "User ID", "hidden": False},
                ],
                "measures": [
                    {"name": "order_items.total_sale_price", "type": "sum", "label": "Total Revenue", "hidden": False},
                ],
            },
        },
        {
            "name": "inventory_items",
            "label": "Inventory Items",
            "description": "Warehouse stock and inventory counts",
            "view_name": "inventory_items",
            "joins": [
                {"name": "products", "relationship": "many_to_one", "sql_on": "${inventory_items.product_id} = ${products.id}"},
            ],
            "fields": {
                "dimensions": [
                    {"name": "products.category", "type": "string", "label": "Category", "hidden": False},
                ],
                "measures": [
                    {"name": "inventory_items.count", "type": "count", "label": "Inventory Count", "hidden": False},
                ],
            },
        },
    ]

    ctx = build_schema_context("thelook", explores_list, prompt="revenue and warehouse inventory count by category")
    assert ctx["model"] == "thelook"
    assert isinstance(ctx["explores"], dict) and len(ctx["explores"]) == 2
    assert isinstance(ctx["candidate_merge_keys"], list)
    assert {"field_name": "products.category", "source_field_name": "products.category"} in (
        ctx["candidate_merge_keys"]
    )
    assert _dig(ctx, "explores", "order_items", "base_view") == "order_items"

    explores_file = tmp_path / "explores.json"
    explores_file.write_text(json.dumps(explores_list))

    # CLI: lkr schema context
    ctx_res = runner.invoke(
        app,
        [
            "schema",
            "context",
            "--model",
            "thelook",
            "--explore-file",
            str(explores_file),
            "--prompt",
            "inventory count by category",
        ],
    )
    assert ctx_res.exit_code == 0, ctx_res.output
    parsed_ctx = json.loads(ctx_res.stdout)
    assert parsed_ctx["model"] == "thelook"
    assert next(iter(parsed_ctx["explores"])) == "inventory_items"

    # CLI: lkr schema validate with source_queries
    merge_query_json = json.dumps(
        {
            "source_queries": [
                {"view": "order_items", "fields": ["products.category", "order_items.total_sale_price"]},
                {"view": "inventory_items", "fields": ["products.category", "inventory_items.count"]},
            ],
            "sorts": ["order_items.total_sale_price desc"],
        }
    )
    val_res = runner.invoke(
        app,
        [
            "schema",
            "validate",
            "--model",
            "thelook",
            "--explore-file",
            str(explores_file),
            "--query",
            merge_query_json,
        ],
    )
    assert val_res.exit_code == 0, val_res.output
    parsed_val = json.loads(val_res.stdout)
    assert parsed_val["valid"] is True
    sq0_norm = parsed_val["normalized_query"]["source_queries"][0]["query"]
    assert sq0_norm["limit"] == "5000" and sq0_norm["sorts"] == ["order_items.total_sale_price desc"]








