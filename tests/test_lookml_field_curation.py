"""Tests for LookML field curation CLI (`lkr parse curation-meta`), Monty curation scripts, and `lkr.utils.deep_get`."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from looker_sdk.rtl.auth_session import AuthSession
from looker_sdk.rtl.transport import Transport
from typer.testing import CliRunner

from lkr.codemode.main import run_python_code
from lkr.extended_sdk_methods import ExtendedLooker40SDK
from lkr.main import app
from lkr.observability.utils import format_attributes
from lkr.parse.curation import build_api_result_from_lookml, extract_curation_metadata
from lkr.utils import deep_get

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATION_SCRIPTS_DIR = REPO_ROOT / "skills" / "lookml-field-curation" / "scripts"
runner = CliRunner()


def _load_module(name: str, path: Path) -> Any:
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
            return json.dumps(
                [
                    {f: "Pending"},
                    {f: "Processing"},
                    {f: "Shipped"},
                    {f: "Cancelled"},
                    {f: None},
                ]
            )
        if f.endswith(".category"):
            return json.dumps([{f: f"Category_{i:02d}"} for i in range(1, 26)])
        if f.endswith((".product_name", ".brand")):
            return json.dumps(
                [{f: f"Classic Cotton Hoodie Style {i}"} for i in range(1, 150)]
            )
        if f.endswith(".sku"):
            return json.dumps([{f: f"SKU-{i:05d}"} for i in range(1, 150)])
        if f.endswith(".customer_notes"):
            return json.dumps(
                [{f: "Customer requested delivery to back porch " + ("x" * 100)}]
            )
        if f.endswith(".customer_email"):
            return json.dumps([{f: "alice@example.com"}, {f: "bob@example.com"}])
        if f.endswith(".customer_phone"):
            return json.dumps([{f: f"+1-555-010-{i:04d}"} for i in range(1, 150)])
        if f.endswith(".metadata_json"):
            return json.dumps(
                [
                    {f: '{"utm_source": "search", "medium": "cpc"}'},
                    {f: '{"utm_source": "direct", "medium": "none"}'},
                ]
            )
        if f.endswith(".user_uuid"):
            return json.dumps(
                [
                    {f: "550e8400-e29b-41d4-a716-446655440000"},
                    {f: "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
                ]
            )
        return json.dumps([{f: f"ID-{i:04d}"} for i in range(1, 150)])

    def create_sql_query(self, body: Any = None, *args: Any, **kwargs: Any) -> Any:
        b = body if isinstance(body, dict) else {}
        slug = f"slug_{len(self._sql_queries) + 1}"
        self._sql_queries[slug] = str(b.get("sql") or "")
        return {"slug": slug}

    def run_sql_query(
        self, slug: str, result_format: str = "json", *args: Any, **kwargs: Any
    ) -> str:
        sql = self._sql_queries.get(slug, "")
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return json.dumps(
                [
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
                ]
            )
        if "INFORMATION_SCHEMA.PARTITIONS" in sql:
            return json.dumps(
                [
                    {
                        "min_partition_id": "20230115",
                        "max_partition_id": "20261020",
                        "partition_count": 1375,
                    }
                ]
            )
        if "CAST(status AS" in sql:
            return json.dumps(
                [
                    {"val": "Pending", "cnt": 50, "total_groups": 4, "max_len": 9},
                    {"val": "Shipped", "cnt": 40, "total_groups": 4, "max_len": 9},
                    {"val": "Cancelled", "cnt": 10, "total_groups": 4, "max_len": 9},
                ]
            )
        return json.dumps(
            [{"val": "sample", "cnt": 1, "total_groups": 1, "max_len": 6}]
        )


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

  dimension: customer_email {
    type: string
    sql: ${TABLE}.customer_email ;;
  }

  dimension: customer_phone {
    type: string
    tags: ["contact"]
    sql: ${TABLE}.customer_phone ;;
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


def test_deep_get_dicts_sequences_and_objects() -> None:
    obj = SimpleNamespace(
        obj={"ctx_lkr": "ok"},
        rows=[SimpleNamespace(name="ecomm", tables=["orders", "users"]), {"columns": None}],
    )
    assert deep_get(obj, ["obj", "ctx_lkr"]) == "ok"
    assert deep_get(obj, "rows.0.name") == "ecomm"
    assert deep_get(obj, "rows.0.tables", []) == ["orders", "users"]
    assert deep_get(obj, "rows.1.columns", []) is None
    assert deep_get(obj, "rows.9.tables", []) == []
    assert deep_get(None, "a.b", "fallback") == "fallback"


def test_no_test_files_inside_skills_dir() -> None:
    skill_tests = list((REPO_ROOT / "skills").rglob("test_*.py")) + list(
        (REPO_ROOT / "skills").rglob("verify_*.py")
    )
    assert skill_tests == []


def test_monty_sandbox_script_hygiene() -> None:
    for script_name in ("profile_string_fields.py", "enrich_partition_clustering.py"):
        source = (CURATION_SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
        assert "globals(" not in source
        assert "print(" not in source
        assert "# ruff: noqa: F821" in source
        assert "ty: ignore[unresolved-reference]" in source


def test_curation_meta_cli_and_sandbox_pipeline() -> None:
    cli_res = runner.invoke(app, ["parse", "curation-meta", "--lookml", SAMPLE_LOOKML])
    assert cli_res.exit_code == 0, cli_res.stdout
    curation_meta = json.loads(cli_res.stdout)
    exp_meta = curation_meta["explores"]["inline::orders"]

    assert exp_meta["parsed_table"]["catalog"] == "analytics-prod"
    assert exp_meta["parsed_table"]["schema"] == "ecomm"
    assert exp_meta["parsed_table"]["table"] == "orders"

    orders_view = exp_meta["views"]["orders"]
    assert "orders.status" in orders_view["string_fields"]
    assert "orders.metadata_json" in orders_view["string_fields"]
    reasons = {
        c["field_name"]: c["reason"] for c in orders_view["static_curation_candidates"]
    }
    assert reasons["orders.order_id"] == "primary_key_visible"
    assert reasons["orders.user_id"] == "foreign_key_visible"
    assert reasons["orders._raw_amount"] == "intermediate_helper_dimension"
    assert reasons["orders.metadata_json"] == "raw_json_or_payload_column"
    assert reasons["orders._fivetran_synced"] == "system_or_etl_audit_column"
    assert reasons["orders.total_revenue"] == "measure_missing_description"
    assert orders_view["measures"][0]["synonyms"] == ["GMV", "gross sales"]

    # Also verify stdin piping (`--api-json -`)
    api_cli = runner.invoke(app, ["parse", "lookml-to-api", "--lookml", SAMPLE_LOOKML])
    piped_res = runner.invoke(
        app, ["parse", "curation-meta", "--api-json", "-"], input=api_cli.stdout
    )
    assert piped_res.exit_code == 0
    assert json.loads(piped_res.stdout)["explores"]["inline::orders"]["id"] == "inline::orders"

    profile_vars = exp_meta["sandbox_vars"]["profile_string_fields"]
    enrich_vars = exp_meta["sandbox_vars"]["enrich_partition_clustering"]
    profile_source = (CURATION_SCRIPTS_DIR / "profile_string_fields.py").read_text(
        encoding="utf-8"
    )
    enrich_source = (CURATION_SCRIPTS_DIR / "enrich_partition_clustering.py").read_text(
        encoding="utf-8"
    )

    with patch("lkr.codemode.main.get_mcp_sdk", return_value=_CurationMockSDK()):
        var_header_explore = "\n".join(
            f"{k} = {json.dumps(v)}"
            for k, v in {**profile_vars, "query_mode": "explore"}.items()
        )
        profile_res = json.loads(
            run_python_code(var_header_explore + "\n" + profile_source)
        )
        assert "stdout" not in profile_res
        recs_by_name = {r["short_name"]: r for r in profile_res["recommendations"]}

        assert recs_by_name["order_id"]["classification"] == "surrogate_or_system_key"
        assert recs_by_name["order_id"]["recommended_hidden"] is True
        assert recs_by_name["order_id"]["recommended_suggestable"] is False
        assert recs_by_name["order_id"]["recommended_tags"] == []

        assert recs_by_name["user_id"]["recommended_tags"] == ["foreign_key"]
        assert recs_by_name["status"]["classification"] == "low_cardinality_enum"
        assert recs_by_name["status"]["recommended_tags"] == ["low_cardinality_enum"]
        assert (
            recs_by_name["status"]["recommended_description"]
            == "Order fulfillment status. Values: 'Pending', 'Processing', 'Shipped', 'Cancelled'."
        )
        assert (
            recs_by_name["category"]["classification"]
            == "medium_cardinality_categorical"
        )
        assert recs_by_name["product_name"]["recommended_tags"] == [
            "searchable_entity_label"
        ]
        assert recs_by_name["sku"]["recommended_tags"] == ["opaque_code_or_free_text"]
        assert recs_by_name["customer_email"]["recommended_tags"] == [
            "opaque_code_or_free_text",
            "pii",
            "email",
        ]
        assert recs_by_name["customer_phone"]["recommended_tags"] == [
            "contact",
            "opaque_code_or_free_text",
            "pii",
            "phone",
        ]
        assert recs_by_name["metadata_json"]["classification"] == "json_payload"
        assert recs_by_name["user_uuid"]["classification"] == "uuid_or_hash"
        assert (
            recs_by_name["_fivetran_synced"]["classification"]
            == "surrogate_or_system_key"
        )

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
        sql_res = json.loads(run_python_code(var_header_sql + "\n" + profile_source))
        assert sql_res["recommendations"][0]["classification"] == "low_cardinality_enum"

        var_header_enrich = "\n".join(
            f"{k} = {json.dumps(v)}" for k, v in enrich_vars.items()
        )
        enrich_res = json.loads(
            run_python_code(var_header_enrich + "\n" + enrich_source)
        )
        assert enrich_res["is_partitioned"] is True
        assert enrich_res["is_clustered"] is True
        assert enrich_res["partition_column"]["recommended_tags"] == ["partition_key"]
        assert [c["lookml_field_name"] for c in enrich_res["clustering_columns"]] == [
            "user_id",
            "country",
        ]
        assert enrich_res["clustering_columns"][0]["recommended_tags"] == [
            "cluster_key"
        ]


def test_standalone_view_and_edge_cases() -> None:
    profile_mod = _load_module(
        "profile_string_fields", CURATION_SCRIPTS_DIR / "profile_string_fields.py"
    )
    enrich_mod = _load_module(
        "enrich_partition_clustering",
        CURATION_SCRIPTS_DIR / "enrich_partition_clustering.py",
    )

    view_only_lookml = """
    view: standalone_events {
      sql_table_name: `proj.ds.standalone_events` ;;
      dimension: id { primary_key: yes type: string }
      dimension: empty_col { type: string }
    }
    """
    meta = extract_curation_metadata(
        build_api_result_from_lookml(lookml=view_only_lookml)
    )
    assert "inline::standalone_events" in meta["explores"]
    assert (
        "standalone_events.empty_col"
        in meta["explores"]["inline::standalone_events"]["views"]["standalone_events"][
            "string_fields"
        ]
    )

    empty_rec = profile_mod.classify_string_field(
        field_meta={
            "field_name": "standalone_events.empty_col",
            "short_name": "empty_col",
        },
        sample_values=[],
        distinct_count=0,
        null_or_empty_count=100,
        total_rows=100,
        max_length=0,
        avg_length=0.0,
    )
    assert empty_rec["classification"] == "empty_or_null_only"
    assert empty_rec["recommended_hidden"] is True

    assert enrich_mod.format_partition_id_to_date("20250401") == "2025-04-01"
    assert enrich_mod.format_partition_id_to_date("202504") == "2025-04-01"
    assert enrich_mod.format_partition_id_to_date("2025") == "2025-01-01"
    assert enrich_mod.format_partition_id_to_date("__NULL__") is None

    const_lookml = """
    constant: bq_proj { value: "default-proj" export: override_optional }
    constant: bq_ds { value: "default_ds" export: override_optional }
    view: const_orders {
      sql_table_name: `@{bq_proj}.@{bq_ds}.orders` ;;
      dimension: status { type: string }
    }
    """
    const_meta = extract_curation_metadata(
        build_api_result_from_lookml(
            lookml=const_lookml, constants={"bq_proj": "override-proj"}
        )
    )
    const_exp = const_meta["explores"]["inline::const_orders"]
    assert const_exp["parsed_table"]["catalog"] == "override-proj"
    assert const_exp["parsed_table"]["schema"] == "default_ds"
    assert const_exp["parsed_table"]["table"] == "orders"


def test_project_helper_consolidated_monty_scripts() -> None:
    helper_dir = REPO_ROOT / "skills" / "lkr-project-helper" / "scripts"
    ensure_src = (helper_dir / "ensure_project_and_model.py").read_text(encoding="utf-8")
    deploy_src = (helper_dir / "deploy_and_reset_workspace.py").read_text(encoding="utf-8")

    class _ProjectMockSDK(_CurationMockSDK):
        def project(self, project_id: str, *args: Any, **kwargs: Any) -> Any:
            return {"id": project_id, "uses_git": True, "git_remote_url": None}

        def create_developer_copy(self, project_id: str, *args: Any, **kwargs: Any) -> Any:
            return {"status": "ok"}

        def all_lookml_models(self, *args: Any, **kwargs: Any) -> Any:
            return [{"name": "demo_model", "allowed_db_connection_names": ["conn_a"]}]

        def update_lookml_model(
            self, lookml_model_name: str, body: Any = None, *args: Any, **kwargs: Any
        ) -> Any:
            return body

        def validate_project(self, project_id: str, *args: Any, **kwargs: Any) -> Any:
            return {"errors": []}

        def commit(self, project_id: str, body: Any = None, *args: Any, **kwargs: Any) -> Any:
            return {"message": (body or {}).get("message")}

    with patch("lkr.codemode.main.get_mcp_sdk", return_value=_ProjectMockSDK()):
        ensure_out = json.loads(
            run_python_code(
                'project_name = "demo_proj"\nmodel_name = "demo_model"\nconnection_name = "conn_b"\n'
                + ensure_src
            )
        )
        assert ensure_out["model_action"] == "updated"
        assert ensure_out["allowed_connections"] == ["conn_a", "conn_b"]

        deploy_out = json.loads(
            run_python_code('project_name = "demo_proj"\ndeploy = "false"\n' + deploy_src)
        )
        assert deploy_out["committed"] is True
        assert deploy_out["deployed"] is False
        assert deploy_out["status"] == "committed_without_deploy"

    # Also verify direct Python execution when Looker SDK returns model objects (non-dicts)
    def _run_script_with_sdk_objects(path: Path, bindings: dict[str, Any]) -> Any:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        mod.__dict__.update(bindings)
        spec.loader.exec_module(mod)
        return mod.main()

    ensure_obj_res = _run_script_with_sdk_objects(
        helper_dir / "ensure_project_and_model.py",
        {
            "project_name": "demo_proj",
            "model_name": "demo_model",
            "connection_name": "",
            "project": lambda _p: SimpleNamespace(
                id="demo_proj", uses_git=True, git_remote_url=None
            ),
            "create_developer_copy": lambda _p: SimpleNamespace(status="ok"),
            "all_connections": lambda: [SimpleNamespace(name="conn_obj")],
            "all_lookml_models": lambda: [
                SimpleNamespace(
                    name="demo_model", allowed_db_connection_names=["conn_a"]
                )
            ],
            "update_lookml_model": lambda lookml_model_name, body: SimpleNamespace(
                **body
            ),
        },
    )
    assert ensure_obj_res["allowed_connections"] == ["conn_a", "conn_obj"]

    deploy_obj_res = _run_script_with_sdk_objects(
        helper_dir / "deploy_and_reset_workspace.py",
        {
            "project_name": "demo_proj",
            "strict": "true",
            "validate_project": lambda _p: SimpleNamespace(
                errors=[SimpleNamespace(severity="error")]
            ),
            "git_branch": lambda _p: SimpleNamespace(name="dev-bryan"),
        },
    )
    assert deploy_obj_res["status"] == "aborted_due_to_validation_errors"
    assert deploy_obj_res["blocking_error_count"] == 1


def test_format_attributes_and_invalid_api_json() -> None:
    assert format_attributes(["tenant:random.randint(7,7)", "bad_attr"]) == {"tenant": "7"}
    bad_json_res = runner.invoke(
        app, ["parse", "curation-meta", "--api-json", "-"], input="{not-valid-json"
    )
    assert bad_json_res.exit_code == 1


