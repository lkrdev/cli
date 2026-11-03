import copy
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from lkr.extended_sdk_methods.main import ExtendedLooker40SDK


def _make_sdk() -> ExtendedLooker40SDK:
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    return ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )


ORDER_ITEMS_EXPLORE: dict[str, Any] = {
    "name": "order_items",
    "view_name": "order_items",
    "joins": [
        {
            "name": "inventory_items",
            "type": "left_outer",
            "relationship": "one_to_one",
            "sql_on": "${order_items.inventory_item_id} = ${inventory_items.id}",
            "dependent_fields": [
                "order_items.inventory_item_id",
                "inventory_items.id",
            ],
        },
        {
            "name": "users",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${order_items.user_id} = ${users.id}",
            "dependent_fields": ["order_items.user_id", "users.id"],
        },
        {
            "name": "products",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${inventory_items.product_id} = ${products.id}",
            "dependent_fields": ["inventory_items.product_id", "products.id"],
        },
        {
            "name": "distribution_centers",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${distribution_centers.id} = ${inventory_items.product_distribution_center_id}",
            "dependent_fields": [
                "distribution_centers.id",
                "inventory_items.product_distribution_center_id",
            ],
        },
        {
            "name": "discounts",
            "type": "inner",
            "relationship": "many_to_one",
            "sql_on": "${products.id} = ${discounts.product_id}",
        },
        {
            "name": "promo_email",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${promo_email.id} = ${users.id}",
        },
    ],
    "sets": [
        {
            "name": "order_items.detail",
            "value": [
                "order_items.id",
                "order_items.status",
                "order_items.created_date",
                "order_items.sale_price",
                "products.brand",
                "products.item_name",
                "users.portrait",
                "users.name",
                "users.email",
            ],
        },
        {
            "name": "inventory_items.detail",
            "value": [
                "inventory_items.id",
                "inventory_items.cost",
                "products.category",
                "products.department",
                "distribution_centers.name",
            ],
        },
        {
            "name": "products.detail",
            "value": [
                "products.id",
                "products.brand",
                "products.category",
                "products.department",
                "products.retail_price",
                "products.sku",
            ],
        },
    ],
    "fields": {
        "dimensions": [
            {
                "name": "order_items.id",
                "view": "order_items",
                "type": "number",
                "primary_key": True,
                "is_numeric": True,
                "can_filter": True,
                "sql": "${TABLE}.id",
            },
            {
                "name": "order_items.created_date",
                "view": "order_items",
                "type": "date_date",
                "is_timeframe": True,
                "can_filter": True,
                "sql": "${TABLE}.created_at",
            },
            {
                "name": "order_items.created_month",
                "view": "order_items",
                "type": "date_month",
                "is_timeframe": True,
                "can_filter": True,
                "sql": "${TABLE}.created_at",
            },
            {
                "name": "order_items.created_year",
                "view": "order_items",
                "type": "date_year",
                "is_timeframe": True,
                "can_filter": True,
                "sql": "${TABLE}.created_at",
            },
            {
                "name": "order_items.status",
                "view": "order_items",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.status",
            },
            {
                "name": "order_items.is_returned",
                "view": "order_items",
                "type": "yesno",
                "can_filter": True,
                "sql": "${returned_raw} IS NOT NULL",
            },
            {
                "name": "order_items.reporting_period_ytd_vs_lytd",
                "view": "order_items",
                "type": "string",
                "can_filter": True,
                "sql": "CASE WHEN ... THEN 'This Year to Date' ELSE 'Last Year to Date' END",
            },
            {
                "name": "order_items.sale_price",
                "view": "order_items",
                "type": "number",
                "is_numeric": True,
                "can_filter": True,
                "sql": "${TABLE}.sale_price",
            },
            {
                "name": "inventory_items.cost",
                "view": "inventory_items",
                "type": "number",
                "is_numeric": True,
                "can_filter": True,
                "sql": "${TABLE}.cost",
            },
            {
                "name": "inventory_items.is_sold",
                "view": "inventory_items",
                "type": "yesno",
                "can_filter": True,
                "sql": "${sold_raw} is not null",
            },
            {
                "name": "order_items.gross_margin",
                "view": "order_items",
                "type": "number",
                "is_numeric": True,
                "can_filter": True,
                "sql": "${sale_price} - ${inventory_items.cost}",
            },
            {
                "name": "order_items.item_gross_margin_percentage",
                "view": "order_items",
                "type": "number",
                "is_numeric": True,
                "can_filter": True,
                "sql": "100.0 * ${gross_margin}/NULLIF(${sale_price}, 0)",
            },
            {
                "name": "order_items.item_gross_margin_percentage_tier",
                "view": "order_items",
                "type": "tier",
                "can_filter": True,
                "sql": "${item_gross_margin_percentage}",
            },
            {
                "name": "products.category",
                "view": "products",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.category",
                "drill_fields": ["products.department", "products.brand"],
            },
            {
                "name": "products.department",
                "view": "products",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.department",
            },
            {
                "name": "products.brand",
                "view": "products",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.brand",
            },
            {
                "name": "products.sku",
                "view": "products",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.sku",
            },
            {
                "name": "users.traffic_source",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.traffic_source",
            },
            {
                "name": "users.gender",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.gender",
            },
            {
                "name": "users.country",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.country",
            },
            {
                "name": "users.state",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.state",
            },
            {
                "name": "users.age_tier",
                "view": "users",
                "type": "tier",
                "can_filter": True,
                "sql": "${TABLE}.age",
            },
            {
                "name": "discounts.discount_reason",
                "view": "discounts",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.discount_reason",
            },
            {
                "name": "promo_email.gen_ai",
                "view": "promo_email",
                "type": "string",
                "can_filter": True,
                "sql": "{% parameter gen_ai_email %}",
            },
        ],
        "measures": [
            {
                "name": "order_items.count",
                "view": "order_items",
                "type": "count",
                "sql": None,
                "drill_fields": ["order_items.status", "products.brand"],
            },
            {
                "name": "order_items.total_sale_price",
                "view": "order_items",
                "type": "sum",
                "sql": "${sale_price}",
            },
            {
                "name": "inventory_items.total_cost",
                "view": "inventory_items",
                "type": "sum",
                "sql": "${cost}",
            },
            {
                "name": "order_items.total_gross_margin",
                "view": "order_items",
                "type": "sum",
                "sql": "${gross_margin}",
            },
            {
                "name": "order_items.average_gross_margin",
                "view": "order_items",
                "type": "average",
                "sql": "${gross_margin}",
            },
            {
                "name": "order_items.gross_margin_percentage",
                "view": "order_items",
                "type": "number",
                "sql": "1.0 * ${total_gross_margin}/NULLIF(${total_sale_price}, 0)",
            },
        ],
    },
}


EVENTS_EXPLORE: dict[str, Any] = {
    "name": "events",
    "view_name": "events",
    "joins": [
        {
            "name": "users",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${events.user_id} = ${users.id}",
            "dependent_fields": ["events.user_id", "users.id"],
        },
        {
            "name": "product_viewed",
            "from": "products",
            "type": "left_outer",
            "relationship": "many_to_one",
            "sql_on": "${events.viewed_product_id} = ${product_viewed.id}",
            "dependent_fields": [
                "events.viewed_product_id",
                "product_viewed.id",
            ],
        },
    ],
    "sets": [],
    "fields": {
        "dimensions": [
            {
                "name": "events.created_date",
                "view": "events",
                "type": "date_date",
                "is_timeframe": True,
                "can_filter": True,
                "sql": "${TABLE}.created_at",
            },
            {
                "name": "events.created_year",
                "view": "events",
                "type": "date_year",
                "is_timeframe": True,
                "can_filter": True,
                "sql": "${TABLE}.created_at",
            },
            {
                "name": "events.event_type",
                "view": "events",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.event_type",
            },
            {
                "name": "events.traffic_source",
                "view": "events",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.traffic_source",
            },
            {
                "name": "events.browser",
                "view": "events",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.browser",
            },
            {
                "name": "events.viewed_product_id",
                "view": "events",
                "type": "number",
                "is_numeric": True,
                "can_filter": True,
                "sql": "CASE WHEN ${event_type} = 'Product' THEN ${TABLE}.uri_product_id END",
            },
            {
                "name": "users.traffic_source",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.traffic_source",
            },
            {
                "name": "users.country",
                "view": "users",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.country",
            },
            {
                "name": "product_viewed.brand",
                "view": "product_viewed",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.brand",
            },
            {
                "name": "product_viewed.category",
                "view": "product_viewed",
                "type": "string",
                "can_filter": True,
                "sql": "${TABLE}.category",
            },
        ],
        "measures": [
            {
                "name": "events.count",
                "view": "events",
                "type": "count",
                "sql": None,
            },
            {
                "name": "events.unique_visitors",
                "view": "events",
                "type": "count_distinct",
                "sql": "${TABLE}.ip_address",
            },
        ],
    },
}


def test_decompile_direct_explore_and_measure_tree():
    sdk = _make_sdk()
    sdk.lookml_model_explore = MagicMock(return_value=ORDER_ITEMS_EXPLORE)

    res = sdk.decompile_kda_target(
        model_name="thelook",
        explore_name="order_items",
        fields=[
            "order_items.created_date",
            "order_items.total_gross_margin",
            "order_items.gross_margin_percentage",
            "order_items.average_gross_margin",
        ],
        filters={
            "order_items.created_date": "yesterday",
            "users.country": "USA",
        },
    )

    assert res["target_type"] == "explore"
    assert res["cross_explore_overlaps"] == []
    tgt = res["targets"][0]
    assert tgt["data_source"] == {
        "model_name": "thelook",
        "explore_name": "order_items",
    }
    assert "query_id" not in tgt["data_source"]
    assert tgt["base_filters"] == {"users.country": "USA"}
    assert tgt["colliding_time_filters"] == {"order_items.created_date": "yesterday"}
    assert tgt["excluded_views"] == ["discounts", "promo_email"]

    # Measure tree: total_gross_margin -> gross_margin -> sale_price & inventory_items.cost
    tgm = tgt["measures"]["order_items.total_gross_margin"]
    assert tgm["derived_dimensions"][0]["dimension"] == "order_items.gross_margin"
    assert [ld["dimension"] for ld in tgm["leaf_dimensions"]] == [
        "order_items.sale_price",
        "inventory_items.cost",
    ]
    assert tgm["recommended_kda_measures"] == [
        "order_items.total_gross_margin",
        "order_items.total_sale_price",
        "inventory_items.total_cost",
    ]
    assert tgm["unmodeled_components"] == []

    # Ratio measure: gross_margin_percentage
    gmp = tgt["measures"]["order_items.gross_margin_percentage"]
    assert gmp["referenced_measures"] == [
        "order_items.total_gross_margin",
        "order_items.total_sale_price",
    ]
    assert gmp["recommended_kda_measures"] == [
        "order_items.total_gross_margin",
        "order_items.total_sale_price",
        "inventory_items.total_cost",
    ]

    # Average measure: average_gross_margin -> includes order_items.count + additive sums
    agm = tgt["measures"]["order_items.average_gross_margin"]
    assert "order_items.count" in agm["recommended_kda_measures"]
    assert "order_items.total_gross_margin" in agm["recommended_kda_measures"]

    # Fix #4: Tautological _tier and relative-date dimensions excluded; drill & entity ranked ahead of yesno/tier
    cands = tgt["candidate_dimensions"]
    all_ranked = (
        cands["query_dimensions"]
        + cands["drill_dimensions"]
        + cands["entity_dimensions"]
        + cands["secondary_flag_and_tier_dimensions"]
    )
    assert "order_items.item_gross_margin_percentage_tier" not in all_ranked
    assert "order_items.reporting_period_ytd_vs_lytd" not in all_ranked
    assert "discounts.discount_reason" not in all_ranked
    assert "promo_email.gen_ai" not in all_ranked
    assert "users.country" not in all_ranked  # Already pinned in base_filters

    assert "order_items.status" in cands["drill_dimensions"]
    assert "products.department" in cands["drill_dimensions"]
    assert "users.traffic_source" in cands["entity_dimensions"]
    assert "order_items.is_returned" in cands["secondary_flag_and_tier_dimensions"]
    assert "inventory_items.is_sold" in cands["secondary_flag_and_tier_dimensions"]
    assert "users.age_tier" in cands["secondary_flag_and_tier_dimensions"]

    # Pass 1 top-6 must not include yesno/tier when >6 drill + entity dimensions exist
    for d in tgt["recommended_pass1_dimensions"]:
        assert d not in cands["secondary_flag_and_tier_dimensions"]


def test_unmodeled_component_warning_when_sum_cost_missing():
    sdk = _make_sdk()
    exp_no_cost = copy.deepcopy(ORDER_ITEMS_EXPLORE)
    exp_no_cost["fields"]["measures"] = [
        m
        for m in exp_no_cost["fields"]["measures"]
        if m["name"] != "inventory_items.total_cost"
    ]
    sdk.lookml_model_explore = MagicMock(return_value=exp_no_cost)

    res = sdk.decompile_kda_target(
        model_name="thelook",
        explore_name="order_items",
        fields=["order_items.total_gross_margin"],
    )
    tgm = res["targets"][0]["measures"]["order_items.total_gross_margin"]
    assert tgm["recommended_kda_measures"] == [
        "order_items.total_gross_margin",
        "order_items.total_sale_price",
    ]
    assert len(tgm["unmodeled_components"]) == 1
    warn = tgm["unmodeled_components"][0]
    assert warn["dimension"] == "inventory_items.cost"
    assert warn["expected_measure_type"] == "sum"
    assert warn["dynamic_field_hint"]["based_on"] == "inventory_items.cost"


def test_conditional_join_isolation_on_events():
    sdk = _make_sdk()
    sdk.lookml_model_explore = MagicMock(return_value=EVENTS_EXPLORE)

    res = sdk.decompile_kda_target(
        model_name="thelook",
        explore_name="events",
        fields=["events.count"],
    )
    cands = res["targets"][0]["candidate_dimensions"]
    cond_dims = [c["dimension"] for c in cands["conditional_join_dimensions"]]
    assert "product_viewed.brand" in cond_dims
    assert "product_viewed.category" in cond_dims
    assert "product_viewed.brand" not in cands["entity_dimensions"]
    assert "product_viewed.brand" not in res["targets"][0]["recommended_pass1_dimensions"]


def test_all_target_url_and_id_variants():
    sdk = _make_sdk()

    def _mock_explore(model: str, explore: str):
        return EVENTS_EXPLORE if explore == "events" else ORDER_ITEMS_EXPLORE

    sdk.lookml_model_explore = MagicMock(side_effect=_mock_explore)
    sdk.query_for_slug = MagicMock(
        side_effect=lambda slug, **_: {
            "id": slug,  # Fix #1: API 4.0 returns string slug in query["id"]
            "slug": slug,
            "model": "thelook",
            "view": "events" if slug == "slug_ev" else "order_items",
            "fields": ["order_items.created_date", "order_items.total_gross_margin"],
            "filters": {"order_items.created_year": "2025"},
        }
    )
    sdk.look = MagicMock(
        return_value={
            "id": "247",
            "title": "Margin Look",
            "query_id": "8CDyM4D",
        }
    )
    sdk.merge_query = MagicMock(
        return_value={
            "id": "m123",
            "source_queries": [
                {
                    "name": "Orders",
                    "query_id": "8CDyM4D",
                    "merge_fields": [
                        {
                            "source_field_name": "order_items.created_date",
                            "field_name": "order_items.created_date",
                        }
                    ],
                },
                {
                    "name": "Events",
                    "query_id": "slug_ev",
                    "merge_fields": [
                        {
                            "source_field_name": "events.created_date",
                            "field_name": "order_items.created_date",
                        }
                    ],
                },
            ],
        }
    )
    sdk.dashboard = MagicMock(
        return_value={
            "id": "thelook::business_pulse",
            "dashboard_filters": [
                {"name": "Date", "default_value": "2025"},
                {"name": "Country", "default_value": "USA"},
            ],
            "dashboard_elements": [
                {
                    "id": "1",
                    "title": "Total Gross Margin",
                    "query": {
                        "id": "q1",
                        "model": "thelook",
                        "view": "order_items",
                        "fields": ["order_items.total_gross_margin"],
                        "filters": {},
                    },
                    "result_maker": {
                        "filterables": [
                            {
                                "model": "thelook",
                                "view": "order_items",
                                "listen": [
                                    {
                                        "dashboard_filter_name": "Date",
                                        "field": "order_items.created_year",
                                    },
                                    {
                                        "dashboard_filter_name": "Country",
                                        "field": "users.country",
                                    },
                                ],
                            }
                        ]
                    },
                },
                {
                    "id": "2",
                    "title": "Orders vs Events Merge",
                    "merge_result_id": "m123",
                    "result_maker": {
                        "merge_result_id": "m123",
                        "filterables": [
                            {
                                "model": "thelook",
                                "view": "order_items",
                                "listen": [
                                    {
                                        "dashboard_filter_name": "Country",
                                        "field": "users.country",
                                    }
                                ],
                            },
                            {
                                "model": "thelook",
                                "view": "events",
                                "listen": [
                                    {
                                        "dashboard_filter_name": "Country",
                                        "field": "users.country",
                                    }
                                ],
                            },
                        ],
                    },
                },
            ],
        }
    )
    sdk.get_conversation = MagicMock(
        return_value={"id": "b891cf86aa2c4258b3f173cd17c8d8c1", "name": "CA Session"}
    )
    sdk.all_conversation_messages = MagicMock(
        return_value=[
            {
                "type": "user",
                "message": {"userMessage": {"text": "Why did gross margin drop?"}},
            },
            {
                "type": "system",
                "message": {
                    "systemMessage": {
                        "data": {
                            "generatedLookerQuery": {
                                "model": "thelook",
                                "explore": "order_items",
                                "fields": ["order_items.total_gross_margin"],
                                "filters": [
                                    {
                                        "field": "order_items.created_year",
                                        "value": "2025",
                                    },
                                    {"field": "users.country", "value": "USA"},
                                ],
                            }
                        }
                    }
                },
            },
        ]
    )

    # 1. Raw query slug
    r_slug = sdk.decompile_kda_target(target="8CDyM4D")
    assert r_slug["target_type"] == "query"
    assert r_slug["targets"][0]["data_source"] == {
        "model_name": "thelook",
        "explore_name": "order_items",
    }

    # 2. Explore URL with qid & filter override + Explore URL with fields
    r_exp_qid = sdk.decompile_kda_target(
        target="https://looker.example.com/explore/thelook/order_items?qid=8CDyM4D&f%5Busers.country%5D=UK"
    )
    assert r_exp_qid["targets"][0]["base_filters"] == {"users.country": "UK"}

    r_exp_flds = sdk.decompile_kda_target(
        target="https://looker.example.com/explore/thelook/order_items?fields=order_items.total_gross_margin&f[users.country]=France"
    )
    assert r_exp_flds["targets"][0]["base_filters"] == {"users.country": "France"}
    assert "order_items.total_gross_margin" in r_exp_flds["targets"][0]["measures"]

    # 3. Look URL
    r_look = sdk.decompile_kda_target(
        target="https://looker.example.com/looks/247?f[users.country]=Germany"
    )
    assert r_look["target_type"] == "look"
    assert r_look["targets"][0]["title"] == "Margin Look"
    assert r_look["targets"][0]["base_filters"] == {"users.country": "Germany"}

    # 4. Dashboard with standard + Merge Result tiles and cross-explore overlaps
    r_dash = sdk.decompile_kda_target(target="thelook::business_pulse")
    assert r_dash["target_type"] == "dashboard"
    assert len(r_dash["targets"]) == 3
    assert len(r_dash["cross_explore_overlaps"]) == 1
    ov = r_dash["cross_explore_overlaps"][0]
    assert ov["explores"] == ["thelook::events", "thelook::order_items"]
    assert "users" in ov["shared_views"]
    assert "users.traffic_source" in ov["shared_dimensions"]
    assert ov["shared_filter_mappings"]["Country"] == {
        "thelook::order_items": "users.country",
        "thelook::events": "users.country",
    }

    # Dashboard with tile_filter
    r_dash_filtered = sdk.decompile_kda_target(
        target="thelook::business_pulse", tile_filter="Total Gross Margin"
    )
    assert len(r_dash_filtered["targets"]) == 1

    # 5. Standalone Merge Result URL
    r_merge = sdk.decompile_kda_target(target="/merge?mid=m123")
    assert r_merge["target_type"] == "merge_result"
    assert len(r_merge["targets"]) == 2

    # 6. Conversational Analytics 32-char UUID (Fix #3)
    r_ca = sdk.decompile_kda_target(target="b891cf86aa2c4258b3f173cd17c8d8c1")
    assert r_ca["target_type"] == "conversation"
    assert r_ca["targets"][0]["title"] == "Why did gross margin drop?"
    assert r_ca["targets"][0]["base_filters"] == {"users.country": "USA"}
    assert r_ca["targets"][0]["colliding_time_filters"] == {
        "order_items.created_year": "2025"
    }


def test_run_key_driver_analysis_slug_rewrite_and_422_fallback():
    sdk = _make_sdk()
    sdk.query_for_slug = MagicMock(
        return_value={
            "id": "8CDyM4D",
            "model": "thelook",
            "view": "order_items",
            "filters": {
                "order_items.created_date": "last 30 days",
                "users.country": "USA",
            },
        }
    )

    # Case 1: Native /internal/kda/analyze succeeds
    sdk.post = MagicMock(
        return_value={
            "status": "SUCCESS",
            "drivers": [{"drivers": ["order_items.status=Complete"], "difference": 80.0}],
        }
    )
    res_ok = sdk.run_key_driver_analysis(
        body={
            "data_source": {"query_id": "8CDyM4D"},
            "contribution_metric": "order_items.total_gross_margin",
            "dimensions": ["order_items.status"],
            "baseline_filters": {"order_items.created_year": "2024"},
            "breach_filters": {"order_items.created_year": "2025"},
        }
    )
    assert res_ok["status"] == "SUCCESS"
    sent_body = sdk.post.call_args.kwargs["body"]
    assert sent_body["data_source"] == {
        "model_name": "thelook",
        "explore_name": "order_items",
    }
    assert sent_body["base_filters"] == {"users.country": "USA"}

    # Case 2: Looker 26.20-26.22 throws HTTP 422 KdaResponse::Success.status -> fallback runs 1 folded query
    sdk.post = MagicMock(
        side_effect=RuntimeError(
            "422: undefined method 'status' for #<Java::ComLookerInsightsKda::KdaResponse::Success>"
        )
    )
    folded_rows = [
        {
            "order_items.created_year": "2024",
            "order_items.status": "Complete",
            "sparse.dim": None,
            "order_items.total_gross_margin": 100.0,
        },
        {
            "order_items.created_year": "2024",
            "order_items.status": "Returned",
            "sparse.dim": None,
            "order_items.total_gross_margin": 50.0,
        },
        {
            "order_items.created_year": "2025",
            "order_items.status": "Complete",
            "sparse.dim": None,
            "order_items.total_gross_margin": 200.0,
        },
        {
            "order_items.created_year": "2025",
            "order_items.status": "Returned",
            "sparse.dim": None,
            "order_items.total_gross_margin": 40.0,
        },
    ]
    sdk.run_inline_query = MagicMock(return_value=json.dumps(folded_rows))

    res_fb = sdk.run_key_driver_analysis(
        body={
            "data_source": {
                "model_name": "thelook",
                "explore_name": "order_items",
                "query_id": "8CDyM4D",
            },
            "contribution_metric": "order_items.total_gross_margin",
            "dimensions": ["order_items.status", "sparse.dim"],
            "base_filters": {"order_items.created_date": "yesterday"},
            "baseline_filters": {"order_items.created_year": "2024"},
            "breach_filters": {"order_items.created_year": "2025"},
        }
    )
    assert res_fb["status"] == "SUCCESS"
    # sparse.dim (100% null) was automatically dropped by the >25% null guard
    assert res_fb["dimensions"] == ["order_items.status"]
    sdk.run_inline_query.assert_called_once()
    inline_body = sdk.run_inline_query.call_args.args[1]
    assert inline_body["filters"]["order_items.created_year"] == "2024,2025"

    # Case 3: Non-422 errors are re-raised
    sdk.post = MagicMock(side_effect=RuntimeError("403 Forbidden"))
    with pytest.raises(RuntimeError, match="403 Forbidden"):
        sdk.run_key_driver_analysis(
            body={
                "data_source": {
                    "model_name": "thelook",
                    "explore_name": "order_items",
                },
                "contribution_metric": "order_items.total_gross_margin",
                "dimensions": ["order_items.status"],
                "baseline_filters": {"order_items.created_year": "2024"},
                "breach_filters": {"order_items.created_year": "2025"},
            }
        )
