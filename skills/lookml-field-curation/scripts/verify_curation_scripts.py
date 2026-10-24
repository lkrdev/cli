"""Self-contained verification harness for lookml-field-curation scripts (local lookml-to-api + Monty code-mode sandbox)."""

import importlib.util
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from looker_sdk.rtl.auth_session import AuthSession
from looker_sdk.rtl.transport import Transport
from typer.testing import CliRunner

from lkr.codemode.main import run_python_code
from lkr.extended_sdk_methods import ExtendedLooker40SDK
from lkr.main import app

SCRIPTS_DIR = Path(__file__).resolve().parent
runner = CliRunner()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _DummyAuth:
    def __init__(self) -> None:
        self.settings = MagicMock()
        self.settings.base_url = "https://example.looker.com"
        self.settings.agent_tag = "test"

    def authenticate(self, request: Any) -> Any:
        return request


class _CurationMockSDK(ExtendedLooker40SDK):
    def __init__(self) -> None:
        super().__init__(
            auth=cast(AuthSession, _DummyAuth()),
            deserialize=cast(Any, MagicMock()),
            serialize=cast(Any, MagicMock()),
            transport=cast(Transport, MagicMock()),
            api_version="4.0",
        )
        self._sql_queries: dict[str, str] = {}

    def run_inline_query(
        self, result_format: str = "json", body: Any = None, *args: Any, **kwargs: Any
    ) -> str:
        b = body if isinstance(body, dict) else {}
        fields = b.get("fields") or [""]
        f = str(fields[0])
        if f.endswith(".status"):
            return json.dumps([
                {f: "Pending"},
                {f: "Processing"},
                {f: "Shipped"},
                {f: "Cancelled"},
                {f: None},
            ])
        if f.endswith(".category"):
            return json.dumps([{f: f"Category_{i:02d}"} for i in range(1, 26)])
        if f.endswith((".product_name", ".brand")):
            return json.dumps([{f: f"Classic Cotton Hoodie Style {i}"} for i in range(1, 150)])
        if f.endswith(".sku"):
            return json.dumps([{f: f"SKU-{i:05d}"} for i in range(1, 150)])
        if f.endswith(".customer_notes"):
            return json.dumps([{f: "Customer requested delivery to back porch " + ("x" * 100)}])
        if f.endswith(".metadata_json"):
            return json.dumps([
                {f: '{"utm_source": "search", "medium": "cpc"}'},
                {f: '{"utm_source": "direct", "medium": "none"}'},
            ])
        if f.endswith(".user_uuid"):
            return json.dumps([
                {f: "550e8400-e29b-41d4-a716-446655440000"},
                {f: "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
            ])
        return json.dumps([{f: f"ID-{i:04d}"} for i in range(1, 150)])

    def create_sql_query(self, body: Any = None, *args: Any, **kwargs: Any) -> Any:
        b = body if isinstance(body, dict) else {}
        sql = str(b.get("sql") or "")
        slug = f"slug_{len(self._sql_queries) + 1}"
        self._sql_queries[slug] = sql
        return {"slug": slug}

    def run_sql_query(
        self, slug: str, result_format: str = "json", *args: Any, **kwargs: Any
    ) -> str:
        sql = self._sql_queries.get(slug, "")
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return json.dumps([
                {
                    "column_name": "created_at",
                    "data_type": "TIMESTAMP",
                    "is_partitioning_column": "YES",
                    "clustering_ordinal_position": None,
                },
                {
                    "column_name": "user_id",
                    "data_type": "STRING",
                    "is_partitioning_column": "NO",
                    "clustering_ordinal_position": 1,
                },
                {
                    "column_name": "country",
                    "data_type": "STRING",
                    "is_partitioning_column": "NO",
                    "clustering_ordinal_position": 2,
                },
            ])
        if "INFORMATION_SCHEMA.PARTITIONS" in sql:
            return json.dumps([
                {
                    "min_partition_id": "20230115",
                    "max_partition_id": "20261020",
                    "partition_count": 1375,
                }
            ])
        if "CAST(status AS" in sql:
            return json.dumps([
                {"val": "Pending", "cnt": 50, "total_groups": 4, "max_len": 9},
                {"val": "Shipped", "cnt": 40, "total_groups": 4, "max_len": 9},
                {"val": "Cancelled", "cnt": 10, "total_groups": 4, "max_len": 9},
            ])
        return json.dumps([{"val": "sample", "cnt": 1, "total_groups": 1, "max_len": 6}])


SAMPLE_LOOKML = """
connection: "bigquery_prod"

view: orders {
  sql_table_name: `analytics-prod.ecomm.orders` ;;

  dimension: order_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.order_id ;;
  }

  dimension: user_id {
    type: string
    sql: ${TABLE}.user_id ;;
  }

  dimension: country {
    type: string
    sql: ${TABLE}.country ;;
  }

  dimension: status {
    type: string
    description: "Order fulfillment status"
    sql: ${TABLE}.status ;;
  }

  dimension: category {
    type: string
    sql: ${TABLE}.category ;;
  }

  dimension: product_name {
    type: string
    sql: ${TABLE}.product_name ;;
  }

  dimension: brand {
    type: string
    sql: ${TABLE}.brand ;;
  }

  dimension: sku {
    type: string
    sql: ${TABLE}.sku ;;
  }

  dimension: customer_notes {
    type: string
    sql: ${TABLE}.customer_notes ;;
  }

  dimension: metadata_json {
    type: string
    sql: ${TABLE}.metadata_json ;;
  }

  dimension: user_uuid {
    type: string
    sql: ${TABLE}.user_uuid ;;
  }

  dimension: _fivetran_synced {
    type: string
    sql: ${TABLE}._fivetran_synced ;;
  }

  dimension: _raw_amount {
    type: number
    sql: ${TABLE}.amount ;;
  }

  dimension: net_amount {
    type: number
    sql: ${_raw_amount} * 0.9 ;;
  }

  dimension_group: created {
    type: time
    timeframes: [raw, time, date, month, year]
    sql: ${TABLE}.created_at ;;
  }

  measure: total_revenue {
    type: sum
    synonyms: ["GMV", "gross sales"]
    sql: ${net_amount} ;;
  }
}

explore: orders {
  view_name: orders
}
"""


def test_monty_sandbox_script_hygiene() -> None:
    for script_name in ("profile_string_fields.py", "enrich_partition_clustering.py"):
        script_path = SCRIPTS_DIR / script_name
        source = script_path.read_text(encoding="utf-8")
        assert "globals(" not in source, f"{script_name} must not call globals() in Monty sandbox"
        assert "print(" not in source, f"{script_name} must not call print() in Monty sandbox"
        assert "# ruff: noqa: F821" in source
        assert "ty: ignore[unresolved-reference]" in source


def test_local_lookml_to_api_and_sandbox_pipeline() -> None:
    cli_res = runner.invoke(app, ["parse", "lookml-to-api", "--lookml", SAMPLE_LOOKML])
    assert cli_res.exit_code == 0, cli_res.stdout
    api_payload = json.loads(cli_res.stdout)
    assert "all_lookml_models" in api_payload
    assert "lookml_model_explores" in api_payload
    assert "inline::orders" in api_payload["lookml_model_explores"]

    inspect_mod = _load_module("inspect_local_lookml", SCRIPTS_DIR / "inspect_local_lookml.py")
    curation_meta = inspect_mod.extract_curation_metadata(api_payload)
    exp_meta = curation_meta["explores"]["inline::orders"]

    assert exp_meta["parsed_table"]["catalog"] == "analytics-prod"
    assert exp_meta["parsed_table"]["schema"] == "ecomm"
    assert exp_meta["parsed_table"]["table"] == "orders"

    orders_view = exp_meta["views"]["orders"]
    assert "orders.status" in orders_view["string_fields"]
    assert "orders.metadata_json" in orders_view["string_fields"]
    reasons = {c["field_name"]: c["reason"] for c in orders_view["static_curation_candidates"]}
    assert reasons["orders.order_id"] == "primary_key_visible"
    assert reasons["orders._raw_amount"] == "intermediate_helper_dimension"
    assert reasons["orders.metadata_json"] == "raw_json_or_payload_column"
    assert reasons["orders._fivetran_synced"] == "system_or_etl_audit_column"
    assert reasons["orders.total_revenue"] == "measure_missing_description"
    assert orders_view["measures"][0]["synonyms"] == ["GMV", "gross sales"]

    profile_vars = exp_meta["sandbox_vars"]["profile_string_fields"]
    enrich_vars = exp_meta["sandbox_vars"]["enrich_partition_clustering"]

    profile_source = (SCRIPTS_DIR / "profile_string_fields.py").read_text(encoding="utf-8")
    enrich_source = (SCRIPTS_DIR / "enrich_partition_clustering.py").read_text(encoding="utf-8")

    with patch("lkr.codemode.main.get_mcp_sdk", return_value=_CurationMockSDK()):
        # 1. Test profile_string_fields.py in Explore mode inside Monty sandbox
        var_header_explore = "\n".join(
            f"{k} = {json.dumps(v)}"
            for k, v in {**profile_vars, "query_mode": "explore"}.items()
        )
        raw_profile_out = run_python_code(var_header_explore + "\n" + profile_source)
        profile_res = json.loads(raw_profile_out)
        assert "stdout" not in profile_res
        recs_by_name = {r["short_name"]: r for r in profile_res["recommendations"]}

        assert recs_by_name["order_id"]["classification"] == "surrogate_or_system_key"
        assert recs_by_name["order_id"]["label_short"] == "Order ID"
        assert recs_by_name["order_id"]["recommended_hidden"] is True
        assert recs_by_name["order_id"]["recommended_suggestable"] is False
        assert (
            recs_by_name["order_id"]["recommended_description"]
            == "Internal key or system metadata column not intended for end-user grouping."
        )

        assert recs_by_name["status"]["classification"] == "low_cardinality_enum"
        assert recs_by_name["status"]["recommended_hidden"] is False
        assert recs_by_name["status"]["recommended_suggestable"] is True
        assert (
            "Order fulfillment status. Values: 'Pending', 'Processing', 'Shipped', 'Cancelled'."
            == recs_by_name["status"]["recommended_description"]
        )

        assert recs_by_name["category"]["classification"] == "medium_cardinality_categorical"
        assert recs_by_name["category"]["recommended_hidden"] is False
        assert recs_by_name["category"]["recommended_suggestable"] is True
        assert recs_by_name["category"]["recommended_description"].startswith("Top values include:")
        assert "(25 distinct values)" in recs_by_name["category"]["recommended_description"]

        for label_col in ("product_name", "brand"):
            assert recs_by_name[label_col]["classification"] == "searchable_entity_label"
            assert recs_by_name[label_col]["recommended_hidden"] is False
            assert recs_by_name[label_col]["recommended_suggestable"] is True
            assert recs_by_name[label_col]["recommended_description"].startswith(
                "Searchable entity label"
            )

        for opaque_col in ("sku", "customer_notes"):
            assert recs_by_name[opaque_col]["classification"] == "opaque_code_or_free_text"
            assert recs_by_name[opaque_col]["recommended_hidden"] is False
            assert recs_by_name[opaque_col]["recommended_suggestable"] is False
            assert recs_by_name[opaque_col]["recommended_description"].startswith(
                "Opaque identifier or free-text string"
            )

        assert recs_by_name["metadata_json"]["classification"] == "json_payload"
        assert recs_by_name["metadata_json"]["recommended_hidden"] is True
        assert recs_by_name["metadata_json"]["recommended_suggestable"] is False
        assert (
            recs_by_name["metadata_json"]["recommended_description"]
            == "Raw JSON payload; hidden and filter suggestions disabled to prevent full-column scans."
        )

        assert recs_by_name["user_uuid"]["classification"] == "uuid_or_hash"
        assert recs_by_name["user_uuid"]["recommended_hidden"] is True
        assert recs_by_name["user_uuid"]["recommended_suggestable"] is False

        assert recs_by_name["_fivetran_synced"]["classification"] == "surrogate_or_system_key"
        assert recs_by_name["_fivetran_synced"]["recommended_hidden"] is True

        assert 'include: "orders.view.lkml"' in profile_res["refinement_lookml"]
        assert "view: +orders {" in profile_res["refinement_lookml"]

        # 2. Test profile_string_fields.py in SQL Runner mode inside Monty sandbox
        var_header_sql = "\n".join(
            f"{k} = {json.dumps(v)}"
            for k, v in {
                "model_name": "inline",
                "view_name": "orders",
                "table_name": "`analytics-prod.ecomm.orders`",
                "query_mode": "sql",
                "field_names": "orders.status",
            }.items()
        )
        raw_sql_out = run_python_code(var_header_sql + "\n" + profile_source)
        sql_res = json.loads(raw_sql_out)
        assert sql_res["query_mode"] == "sql"
        assert sql_res["recommendations"][0]["classification"] == "low_cardinality_enum"

        # 3. Test enrich_partition_clustering.py inside Monty sandbox
        var_header_enrich = "\n".join(
            f"{k} = {json.dumps(v)}" for k, v in enrich_vars.items()
        )
        raw_enrich_out = run_python_code(var_header_enrich + "\n" + enrich_source)
        enrich_res = json.loads(raw_enrich_out)
        assert "stdout" not in enrich_res
        assert enrich_res["is_partitioned"] is True
        assert enrich_res["is_clustered"] is True
        assert (
            enrich_res["header_comment"]
            == "# PARTITION_COLUMN: created_at (TIMESTAMP) | MIN_DATE: 2023-01-15 | CLUSTERED_BY: user_id, country"
        )
        part_col = enrich_res["partition_column"]
        assert part_col["lookml_construct"] == "dimension_group"
        assert part_col["lookml_field_name"] == "created"
        assert part_col["min_partition_date"] == "2023-01-15"
        assert part_col["filter_timeframe_field"] == "orders.created_date"
        assert part_col["filter_timeframe_label"] == "Created Date"
        assert (
            part_col["recommended_description"]
            == "Physical partition column (required). Min date available: 2023-01-15. Do not use 'is any value'."
        )
        clust_cols = enrich_res["clustering_columns"]
        assert [c["lookml_field_name"] for c in clust_cols] == ["user_id", "country"]
        assert (
            "Filtering alongside Created Date enables block pruning."
            in clust_cols[0]["recommended_description"]
        )
        assert 'filters: [orders.created_date: "7 days"]' in enrich_res["base_explore_lookml"]


def test_standalone_view_and_edge_cases() -> None:
    inspect_mod = _load_module("inspect_local_lookml", SCRIPTS_DIR / "inspect_local_lookml.py")
    profile_mod = _load_module("profile_string_fields", SCRIPTS_DIR / "profile_string_fields.py")
    enrich_mod = _load_module(
        "enrich_partition_clustering", SCRIPTS_DIR / "enrich_partition_clustering.py"
    )

    # 1. Standalone view-only LookML (no explore: block) synthesizes an explore automatically
    view_only_lookml = """
    view: standalone_events {
      sql_table_name: `proj.ds.standalone_events` ;;
      dimension: id { primary_key: yes type: string }
      dimension: empty_col { type: string }
    }
    """
    api_res = inspect_mod.build_api_result_from_lookml(lookml=view_only_lookml)
    meta = inspect_mod.extract_curation_metadata(api_res)
    assert "inline::standalone_events" in meta["explores"]
    v_meta = meta["explores"]["inline::standalone_events"]["views"]["standalone_events"]
    assert "standalone_events.empty_col" in v_meta["string_fields"]

    # 2. Empty/null-only string field classification
    empty_rec = profile_mod.classify_string_field(
        field_meta={"field_name": "standalone_events.empty_col", "short_name": "empty_col"},
        sample_values=[],
        distinct_count=0,
        null_or_empty_count=100,
        total_rows=100,
        max_length=0,
        avg_length=0.0,
    )
    assert empty_rec["classification"] == "empty_or_null_only"
    assert empty_rec["recommended_hidden"] is True
    assert empty_rec["recommended_suggestable"] is False

    # 3. Partition ID normalization formats
    assert enrich_mod.format_partition_id_to_date("20250401") == "2025-04-01"
    assert enrich_mod.format_partition_id_to_date("202504") == "2025-04-01"
    assert enrich_mod.format_partition_id_to_date("2025") == "2025-01-01"
    assert enrich_mod.format_partition_id_to_date("__NULL__") is None
    assert enrich_mod.format_partition_id_to_date("__UNPARTITIONED__") is None

    # 4. Constant substitution and overrides in inspect_local_lookml
    const_lookml = """
    constant: bq_proj { value: "default-proj" export: override_optional }
    constant: bq_ds { value: "default_ds" export: override_optional }
    view: const_orders {
      sql_table_name: `@{bq_proj}.@{bq_ds}.orders` ;;
      dimension: status { type: string }
    }
    """
    const_api_res = inspect_mod.build_api_result_from_lookml(
        lookml=const_lookml, constants={"bq_proj": "override-proj"}
    )
    const_meta = inspect_mod.extract_curation_metadata(const_api_res)
    const_exp = const_meta["explores"]["inline::const_orders"]
    assert const_exp["parsed_table"]["catalog"] == "override-proj"
    assert const_exp["parsed_table"]["schema"] == "default_ds"
    assert const_exp["parsed_table"]["table"] == "orders"


if __name__ == "__main__":
    test_monty_sandbox_script_hygiene()
    test_local_lookml_to_api_and_sandbox_pipeline()
    test_standalone_view_and_edge_cases()
