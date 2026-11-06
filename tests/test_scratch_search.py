from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from lkr.parse.lookml import LookmlFile, parse_lookml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "looker-field-profiler" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_SPEC = importlib.util.spec_from_file_location("scratch_search", SCRIPT_DIR / "scratch_search.py")
assert _SPEC is not None and _SPEC.loader is not None
scratch_search = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scratch_search)


class _FakeSDK:
    def run_inline_query(self, result_format: str, body: dict[str, object]) -> str:
        assert result_format == "sql"
        model = str(body["model"])
        explore = str(body["view"])
        filters = body.get("filters")
        assert isinstance(filters, dict)
        field_name = str(next(iter(filters.keys())))
        view_alias, col = field_name.split(".", 1)
        join_clause = (
            f"\nLEFT JOIN `proj.ds.{view_alias}` AS {view_alias} ON {explore}.{view_alias}_id = {view_alias}.id"
            if view_alias != explore
            else ""
        )
        return (
            f"SELECT\n"
            f"    '{model}' AS model_name,\n"
            f"    '{explore}' AS explore_name,\n"
            f"    '{field_name}' AS field_name,\n"
            f"    'entity_label' AS subtype,\n"
            f"    {view_alias}.{col} AS field_value\n"
            f"FROM `proj.ds.{explore}` AS {explore}{join_clause}\n"
            f"WHERE LENGTH({view_alias}.{col}) <> 0 AND ({view_alias}.{col}) IS NOT NULL\n"
            f"GROUP BY\n    1,\n    2,\n    3,\n    4,\n    5\n"
            f"ORDER BY\n    1\n"
            f"LIMIT 100000"
        )


def test_five_dialects_inline_sql_union_and_pdt() -> None:
    fake_sdk = _FakeSDK()
    b1 = scratch_search.generate_inline_branch_sql(
        sdk=fake_sdk,
        model_name="agentic_thelook",
        explore_name="order_items",
        field_name="products.brand",
        subtype="entity_label",
    )
    b2 = scratch_search.generate_inline_branch_sql(
        sdk=fake_sdk,
        model_name="agentic_thelook",
        explore_name="order_items",
        field_name="order_items.status",
        subtype="enum",
    )
    assert "FROM `proj.ds.order_items` AS order_items" in b1
    assert "LEFT JOIN `proj.ds.products` AS products" in b1
    assert "ORDER BY" not in b1
    assert "LIMIT 100000" not in b1
    assert "view_name" not in b1
    assert "LIMIT" not in scratch_search.strip_looker_order_and_limit("SELECT a FROM t GROUP BY 1 LIMIT 100000")
    assert "FETCH FIRST" not in scratch_search.strip_looker_order_and_limit(
        "SELECT a FROM t GROUP BY 1 FETCH FIRST 100000 ROWS ONLY"
    )

    union_sql = scratch_search.build_union_all_sql([b1, b2])
    expected_index_tokens = {
        "bigquery_standard_sql": "CREATE SEARCH INDEX",
        "snowflake": "ADD SEARCH OPTIMIZATION",
        "postgres": "USING GIN (to_tsvector",
        "databrickssql": "OPTIMIZE",
        "duckdb": "PRAGMA create_fts_index",
    }
    for dialect_name, idx_token in expected_index_tokens.items():
        mod = scratch_search.resolve_dialect_module(dialect_name)
        pdt_stmts = mod.build_persist_sql(union_sql)
        pdt_joined = "\n".join(pdt_stmts)
        assert "${SQL_TABLE_NAME}" in pdt_joined
        assert "FROM `proj.ds.order_items` AS order_items" in pdt_joined
        assert "UNION ALL" in pdt_joined
        assert idx_token in pdt_joined
        assert "{{" not in pdt_joined

        lkml_pdt = scratch_search.build_hidden_explore_lookml(
            pdt_steps=pdt_stmts,
            model_name="agentic_thelook",
        )
        assert "view: _field_value_search_agentic_thelook {" in lkml_pdt
        assert "explore: _field_value_search_agentic_thelook {" in lkml_pdt
        assert "sql_trigger_value: SELECT CURRENT_DATE ;;" in lkml_pdt
        assert "create_process: {" in lkml_pdt
        assert "${SQL_TABLE_NAME}" in lkml_pdt
        assert "dimension: view_name" not in lkml_pdt
        assert "{{" not in lkml_pdt
        assert "{%" not in lkml_pdt

        search_sql = mod.build_search_sql(
            "Calvin Klein",
            table_ref="${_field_value_search_agentic_thelook.SQL_TABLE_NAME}",
            limit=10,
        )
        assert "${_field_value_search_agentic_thelook.SQL_TABLE_NAME}" in search_sql
        assert "Calvin Klein" in search_sql
        assert "LIMIT 10" in search_sql


def test_two_models_offline_discovery_and_lookml_parse(tmp_path: Path) -> None:
    (tmp_path / "thelook.model.lkml").write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\nexplore: order_items {\n  join: users {\n    sql_on: ${order_items.user_id} = ${users.id} ;;\n    relationship: many_to_one\n  }\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "marketing.model.lkml").write_text(
        'connection: "bq"\ninclude: "*.view.lkml"\nexplore: users {}\n',
        encoding="utf-8",
    )
    (tmp_path / "order_items.view.lkml").write_text(
        "view: order_items {\n  sql_table_name: `proj.ds.order_items` ;;\n  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n  dimension: user_id { hidden: yes type: number sql: ${TABLE}.user_id ;; }\n  dimension: status { type: string sql: ${TABLE}.status ;; }\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "users.view.lkml").write_text(
        'view: users {\n  sql_table_name: `proj.ds.users` ;;\n  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n  dimension: city { type: string sql: ${TABLE}.city ;; }\n  dimension: email { type: string tags: ["pii", "email"] sql: ${TABLE}.email ;; }\n}\n',
        encoding="utf-8",
    )
    fake_sdk = _FakeSDK()
    for m_name in ("thelook", "marketing"):
        cands = scratch_search.discover_model_string_candidates(
            sdk=None,
            model_name=m_name,
            lookml_path=tmp_path,
        )
        branches = [
            scratch_search.generate_inline_branch_sql(
                sdk=fake_sdk,
                model_name=m_name,
                explore_name=c["explore_name"],
                field_name=c["field_name"],
                subtype="categorical",
            )
            for c in cands
        ]
        pdt_steps = scratch_search.bigquery.build_persist_sql(
            scratch_search.build_union_all_sql(branches)
        )
        v_name = scratch_search.view_name_for_model(m_name)
        pdt_lkml = scratch_search.build_hidden_explore_lookml(pdt_steps=pdt_steps, model_name=m_name)
        (tmp_path / f"{v_name}.explore.lkml").write_text(pdt_lkml, encoding="utf-8")

    parsed = parse_lookml(tmp_path)
    assert isinstance(parsed.file, LookmlFile) and parsed.file.explore is not None
    for m_name in ("thelook", "marketing"):
        v_name = f"_field_value_search_{m_name}"
        exp_entry = parsed.file.explore[v_name]
        assert v_name in (exp_entry.view or {})
        assert v_name in (exp_entry.explore or {})
