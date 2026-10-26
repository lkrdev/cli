import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pydantic_monty
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "agentic-lookml-workflow" / "scripts"


def _run_monty(path: Path, vars_: dict[str, str], externals: dict[str, Any]) -> Any:
    header = "\n".join(f"{k} = {json.dumps(v)}" for k, v in vars_.items())
    code = f"{header}\n{path.read_text()}" if header else path.read_text()
    with pydantic_monty.Monty() as m, m.checkout() as session:
        return session.feed_run(code, external_lookup=externals)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pre_gate_mod = _load_module("pre_gate", SCRIPTS_DIR / "pre_gate.py")

split_sql_statements = pre_gate_mod.split_sql_statements
compare_row_sets = pre_gate_mod.compare_row_sets
normalize_val = pre_gate_mod.normalize_val


def test_split_sql_statements_single():
    sql = "SELECT id, count FROM orders WHERE status = 'Complete'"
    stmts = split_sql_statements(sql)
    assert len(stmts) == 1
    assert stmts[0] == sql


def test_split_sql_statements_multiple_with_semicolons_and_comments():
    sql = """
    -- First query
    SELECT id, total_amount FROM orders WHERE status = 'done;not_split';

    /* Block comment with ; */
    SELECT user_id, count(*) AS order_cnt
    FROM users
    GROUP BY 1;
    """
    stmts = split_sql_statements(sql)
    assert len(stmts) == 2
    assert "status = 'done;not_split'" in stmts[0]
    assert "FROM users" in stmts[1]


def test_compare_row_sets_identical():
    sql_rows = [{"order_id": 1, "revenue": 100.50}]
    looker_rows = [{"orders.order_id": 1, "orders.revenue": 100.50}]
    matched, mismatches = compare_row_sets(sql_rows, looker_rows)
    assert matched is True
    assert len(mismatches) == 0


def test_compare_row_sets_numeric_tolerance():
    sql_rows = [{"id": 10, "val": 12.34567}]
    looker_rows = [{"orders.id": "10", "orders.val": 12.3457}]
    matched, _mismatches = compare_row_sets(sql_rows, looker_rows)
    assert matched is True


def test_compare_row_sets_mismatch():
    sql_rows = [{"id": 1, "val": 50}]
    looker_rows = [{"orders.id": 1, "orders.val": 99}]
    matched, mismatches = compare_row_sets(sql_rows, looker_rows)
    assert matched is False
    assert len(mismatches) > 0
    assert "SQL=50" in mismatches[0]
    assert "Looker=99" in mismatches[0]


def test_compare_row_sets_row_count_mismatch():
    sql_rows = [{"id": 1}, {"id": 2}]
    looker_rows = [{"id": 1}]
    matched, mismatches = compare_row_sets(sql_rows, looker_rows)
    assert matched is False
    assert "Row count mismatch" in mismatches[0]


def test_generate_bronze_view_monty_compatible():
    script_path = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "generate-view-from-table"
        / "scripts"
        / "generate_bronze_view.py"
    )
    source = script_path.read_text()
    assert "globals(" not in source

    called_kwargs = {}

    def fake_generate(**kwargs):
        called_kwargs.update(kwargs)
        return {"new_files": [{"path": "bronze/order_items.view.lkml"}]}

    ns = {
        "project_id": "proj",
        "model_name": "mod",
        "connection_name": "conn",
        "schema_name": "bigquery-public-data.thelook_ecommerce",
        "table_name": "order_items",
        "generate_lookml_with_new_files": fake_generate,
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    assert called_kwargs["folder_name"] == "bronze"
    assert called_kwargs["body"] == {
        "tables": [
            {"schema": "bigquery-public-data.thelook_ecommerce", "table_name": "order_items", "base_view": True}
        ]
    }


def test_configure_model_defaults_to_project_id_and_creates_model():
    script_path = SCRIPTS_DIR / "configure_model.py"
    source = script_path.read_text()
    assert "globals(" not in source

    created_bodies = []

    def fake_create_lookml_model(body):
        created_bodies.append(body)
        return body

    ns = {
        "project_id": "agentic-thelook",
        "connection_name": "bigquery_public",
        "all_lookml_models": list,
        "create_lookml_model": fake_create_lookml_model,
        "update_lookml_model": lambda **_kw: None,
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    assert created_bodies == [
        {
            "name": "agentic_thelook",
            "project_name": "agentic-thelook",
            "allowed_db_connection_names": ["bigquery_public"],
        }
    ]


def test_init_branch_prefers_remote_ref_over_ref():
    script_path = SCRIPTS_DIR / "init_branch.py"
    created_branches = []
    looked_up_branches = []

    def fake_find_git_branch(project_id, branch_name):
        looked_up_branches.append((project_id, branch_name))
        return {"name": branch_name, "is_production": True, "ref": "local_stale_sha", "remote_ref": "origin_latest_sha"}

    def fake_create_git_branch(project_id, body):
        created_branches.append((project_id, body))
        return body

    result = _run_monty(
        script_path,
        {"project_id": "agentic-thelook", "ts_utc": "20261021_070000_000"},
        {
            "me": lambda: {"id": "42"},
            "project": lambda **_kw: {
                "git_production_branch_name": "main",
                "git_remote_url": "git@github.com:org/repo.git",
            },
            "reset_project_to_production": lambda **_kw: None,
            "create_developer_copy": lambda **_kw: None,
            "find_git_branch": fake_find_git_branch,
            "git_branch": lambda **_kw: {"name": "main", "ref": "local_stale_sha"},
            "create_git_branch": fake_create_git_branch,
        },
    )
    assert result["production_ref"] == "origin_latest_sha"
    assert looked_up_branches == [("agentic-thelook", "main")]
    assert created_branches == [
        ("agentic-thelook", {"name": "20261021_070000_000_42", "ref": "origin_latest_sha"}),
    ]


def test_validate_and_commit_pushes_branch_to_remote_and_pairs_tests():
    script_path = SCRIPTS_DIR / "validate_and_commit_branch.py"
    pushed_paths = []
    test_calls = []

    def fake_post(path, **_kw):
        pushed_paths.append(path)
        return ""

    def fake_run_lookml_test(**kw):
        test_calls.append((kw.get("file_id"), kw.get("test")))
        return [{"test_name": kw.get("test"), "success": True}]

    res = _run_monty(
        script_path,
        {
            "project_id": "agentic-thelook",
            "file_ids": "tests/bronze/a.test.lkml,tests/silver/b.test.lkml",
            "test_names": "test_a,test_b",
            "commit_message": "feat(lookml): refactor SQL queries",
        },
        {
            "validate_project": lambda **_kw: {"errors": []},
            "run_lookml_test": fake_run_lookml_test,
            "commit": lambda **_kw: {},
            "post": fake_post,
            "encode_path_param": lambda s: s,
            "git_branch": lambda **_kw: {"name": "20261020_093734_975_1", "ref": "abc1234"},
        },
    )
    assert res["passed"] is True
    assert res["committed"] is True
    assert test_calls == [
        ("tests/bronze/a.test.lkml", "test_a"),
        ("tests/silver/b.test.lkml", "test_b"),
    ]
    assert pushed_paths == ["/projects/agentic-thelook/push_branch"]


def test_no_monty_globals_in_skill_scripts():
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    for py_file in skills_dir.rglob("*.py"):
        text = py_file.read_text()
        assert "globals().get(" not in text, f"{py_file} uses globals().get()"
        assert "locals().get(" not in text, f"{py_file} uses locals().get()"


def test_pre_gate_compare_row_sets_matches_aliased_count():
    ok, diffs = compare_row_sets(
        [{"total_line_items_sold": 181978}],
        [{"order_items.count": 181978}],
    )
    assert ok is True
    assert diffs == []

    ok2, diffs2 = compare_row_sets(
        [{"status": "Complete", "total_line_items_sold": 500}],
        [{"order_items.status": "Complete", "order_items.count": 500}],
    )
    assert ok2 is True
    assert diffs2 == []


def test_pre_gate_initializes_sql_and_validates_and_checks_parity():
    script_path = SCRIPTS_DIR / "pre_gate.py"
    source = script_path.read_text()
    assert "globals(" not in source
    assert "locals(" not in source

    created_sql = []
    created_looker_queries = []

    def fake_create_sql_query(body):
        created_sql.append(body)
        return {"slug": "sql_slug_1"}

    def fake_create_query(body):
        created_looker_queries.append(body)
        return {"id": "101", "slug": "slug_101", "share_url": "https://example.looker.com/x/slug_101"}

    res: dict[str, Any] = _run_monty(
        script_path,
        {
            "raw_sql": "SELECT id, count AS total_cnt FROM orders WHERE status = 'Complete';",
            "connection_name": "thelook_conn",
            "data_json": '{"project_id": "thelook"}',
            "base_url": "https://example.looker.com",
            "validate": "true",
            "inline_queries_json": '{"0": {"model": "thelook", "view": "orders", "fields": ["orders.id", "orders.count"]}}',
        },
        {
            "validate_project": lambda **_kw: {"errors": []},
            "create_sql_query": fake_create_sql_query,
            "create_query": fake_create_query,
            "run_sql_query": lambda **_kw: '[{"id": 1, "total_cnt": 10}]',
            "run_inline_query": lambda **_kw: '[{"orders.id": 1, "orders.count": 10}]',
        },
    )

    assert res["passed"] is True
    assert res["all_queries_matched"] is True
    assert len(res["queries"]) == 1
    q0 = res["queries"][0]
    assert q0["query_index"] == 0
    assert q0["sql_query_id"] == "sql_slug_1"
    assert q0["sql_runner_url"] == "https://example.looker.com/sql/sql_slug_1"
    assert q0["query_id"] == "101"
    assert q0["explore_url"] == "https://example.looker.com/x/slug_101"
    assert q0["parity_status"] == "matched"
    assert q0["sql"] == "SELECT id, count AS total_cnt FROM orders WHERE status = 'Complete'"
    assert created_sql == [{"connection_name": "thelook_conn", "sql": "SELECT id, count AS total_cnt FROM orders WHERE status = 'Complete'"}]
    assert len(created_looker_queries) == 1

    # Verify that modified SQL regenerates SQL Runner queries and invalid JSON does not crash
    res2: dict[str, Any] = _run_monty(
        script_path,
        {
            "raw_sql": "SELECT id, count FROM orders WHERE status = 'Cancelled';",
            "connection_name": "thelook_conn",
            "data_json": json.dumps(res),
            "base_url": "https://example.looker.com",
            "validate": "false",
            "inline_queries_json": "{invalid_json",
        },
        {
            "create_sql_query": lambda body: {"slug": "sql_slug_2"},
            "create_query": lambda body: {"id": "102", "slug": "slug_102"},
            "run_sql_query": lambda **_kw: "[]",
            "run_inline_query": lambda **_kw: "[]",
        },
    )
    assert res2["queries"][0]["sql_query_id"] == "sql_slug_2"
    assert res2["queries"][0]["sql"] == "SELECT id, count FROM orders WHERE status = 'Cancelled'"


def test_pre_gate_aligns_outer_sql_round_scale_without_loosening_unrounded_columns():
    script_path = SCRIPTS_DIR / "pre_gate.py"
    sql = (
        "SELECT COUNT(id) AS unsold_units_on_shelf, "
        "ROUND(SUM(cost), 2) AS sunk_dusty_shelf_cost, "
        "ROUND(SUM(product_retail_price), 2) AS hypothetical_retail_value "
        "FROM `bigquery-public-data.thelook_ecommerce.inventory_items` WHERE sold_at IS NULL;"
    )
    res: dict[str, Any] = _run_monty(
        script_path,
        {
            "raw_sql": sql,
            "connection_name": "bq_conn",
            "data_json": '{"project_id": "agentic-thelook"}',
            "base_url": "https://example.looker.com",
            "validate": "false",
            "inline_queries_json": json.dumps({
                "0": {
                    "model": "agentic_thelook",
                    "view": "inventory_items",
                    "fields": [
                        "inventory_items.count",
                        "inventory_items.sunk_dusty_shelf_cost",
                        "inventory_items.unsold_retail_value",
                    ],
                }
            }),
        },
        {
            "create_sql_query": lambda body: {"slug": "sql_round"},
            "create_query": lambda body: {"id": "201", "slug": "slug_201"},
            "run_sql_query": lambda **_kw: json.dumps([
                {
                    "unsold_units_on_shelf": 308865,
                    "sunk_dusty_shelf_cost": 8892021.4,
                    "hypothetical_retail_value": 18500974.0,
                }
            ]),
            "run_inline_query": lambda **_kw: json.dumps([
                {
                    "inventory_items.count": 308865,
                    "inventory_items.sunk_dusty_shelf_cost": 8892021.4041,
                    "inventory_items.unsold_retail_value": 18500973.9977,
                }
            ]),
        },
    )
    assert res["passed"] is True
    assert res["queries"][0]["parity_status"] == "matched"

    # Without outer ROUND, with inner SUM(ROUND(...)), or with ROUND only in a SQL comment, 4-decimal precision stays enforced
    for non_cosmetic_sql in (
        "SELECT SUM(cost) AS sunk_dusty_shelf_cost FROM inventory_items;",
        "SELECT SUM(ROUND(cost, 2)) AS sunk_dusty_shelf_cost FROM inventory_items;",
        "-- SELECT ROUND(SUM(cost), 2) AS sunk_dusty_shelf_cost\nSELECT SUM(cost) AS sunk_dusty_shelf_cost FROM inventory_items;",
    ):
        res_strict: dict[str, Any] = _run_monty(
            script_path,
            {
                "raw_sql": non_cosmetic_sql,
                "connection_name": "bq_conn",
                "data_json": '{"project_id": "agentic-thelook"}',
                "base_url": "https://example.looker.com",
                "validate": "false",
                "inline_queries_json": '{"0": {"model": "m", "view": "v", "fields": ["v.sunk_dusty_shelf_cost"]}}',
            },
            {
                "create_sql_query": lambda body: {"slug": "sql_strict"},
                "create_query": lambda body: {"id": "202", "slug": "slug_202"},
                "run_sql_query": lambda **_kw: '[{"sunk_dusty_shelf_cost": 8892021.4}]',
                "run_inline_query": lambda **_kw: '[{"v.sunk_dusty_shelf_cost": 8892021.4041}]',
            },
        )
        assert res_strict["passed"] is False
        assert res_strict["queries"][0]["parity_status"] == "mismatched"


def test_pre_gate_executes_optional_test_queries_json_in_same_sandbox_call():
    script_path = SCRIPTS_DIR / "pre_gate.py"
    inline_calls = []

    def fake_run_inline_query(result_format, body, **kw):
        assert "apply_formatting" not in kw
        assert result_format == "json"
        inline_calls.append(body)
        if body.get("view") == "orders_base":
            return '[{"orders.total_revenue": 4520.2519, "orders.count": 84}]'
        return '[{"orders.id": 1, "orders.count": 10}]'

    res: dict[str, Any] = _run_monty(
        script_path,
        {
            "raw_sql": "SELECT id, count FROM orders;",
            "connection_name": "bq_conn",
            "data_json": '{"project_id": "thelook"}',
            "base_url": "https://example.looker.com",
            "validate": "true",
            "inline_queries_json": '{"0": {"model": "thelook", "view": "orders", "fields": ["orders.id", "orders.count"]}}',
            "test_queries_json": json.dumps({
                "orders_base": {
                    "model": "thelook",
                    "view": "orders_base",
                    "fields": ["orders.total_revenue", "orders.count"],
                    "filters": {"orders.created_date": "2024-01-01"},
                }
            }),
        },
        {
            "validate_project": lambda **_kw: {"errors": []},
            "create_sql_query": lambda body: {"slug": "sql_1"},
            "create_query": lambda body: {"id": "101", "slug": "slug_101"},
            "run_sql_query": lambda **_kw: '[{"id": 1, "count": 10}]',
            "run_inline_query": fake_run_inline_query,
        },
    )
    assert res["passed"] is True
    assert res["test_query_results"] == {
        "orders_base": [{"orders.total_revenue": 4520.2519, "orders.count": 84}]
    }
    assert len(inline_calls) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX bash script test")
def test_setup_repo_skip_preflight_and_opt_in_secrets_and_preflight_fast_path(tmp_path: Path):
    import os
    import subprocess

    create_pr_src = (SCRIPTS_DIR / "create_github_pr.sh").read_text(encoding="utf-8")
    assert "gh secret" not in create_pr_src

    # Fake bin directory with spy uv, lkr, gh, jq
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spy_log = tmp_path / "spy.log"
    for cmd in ("uv", "lkr", "gh", "jq"):
        p = bin_dir / cmd
        p.write_text(
            f'#!/usr/bin/env bash\necho "{cmd} $*" >> "{spy_log}"\nexit 0\n',
            encoding="utf-8",
        )
        p.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "LOOKERSDK_BASE_URL": "https://example.looker.com",
        "LOOKERSDK_CLIENT_ID": "cid",
        "LOOKERSDK_CLIENT_SECRET": "csecret",
        "PROJECT_ID": "agentic-thelook",
    }

    # 1. Warm preflight.sh fast-paths without calling uv tool install or lkr --help
    subprocess.run(["bash", str(SCRIPTS_DIR / "preflight.sh")], env=env, check=True)
    log1 = spy_log.read_text(encoding="utf-8")
    assert "uv tool install" not in log1
    assert "lkr parse" not in log1
    assert "gh auth token" in log1

    # 2. setup_repo.sh with LOOKML_DIR / --skip-preflight only updates model includes (no gh secret, no .github)
    spy_log.write_text("", encoding="utf-8")
    work_dir = tmp_path / "repo"
    lookml_dir = work_dir / "data" / "run1" / "lookml"
    (lookml_dir / "bronze" / "explores").mkdir(parents=True)
    (lookml_dir / "bronze" / "explores" / "orders_base.explore.lkml").write_text("", encoding="utf-8")
    model_file = lookml_dir / "agentic_thelook.model.lkml"
    model_file.write_text(
        'connection: "bq"\ninclude: "/bronze/explores/*.explore.lkml"\ninclude: "/bronze/explores/**/*.explore.lkml"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["bash", str(SCRIPTS_DIR / "setup_repo.sh"), "--skip-preflight"],
        cwd=work_dir,
        env={**env, "LOOKML_DIR": str(lookml_dir), "MODEL_NAME": "agentic_thelook", "CONNECTION_NAME": "bq"},
        check=True,
    )
    assert spy_log.read_text(encoding="utf-8") == ""
    assert not (work_dir / ".github").exists()
    model_text = model_file.read_text(encoding="utf-8")
    assert model_text.count(".explore.lkml") == 1
    assert 'include: "/bronze/explores/**/*.explore.lkml"' in model_text

    # 3. Full setup_repo.sh without --sync-secrets does NOT call gh secret, with --sync-secrets DOES
    (work_dir / ".agents" / "skills").mkdir(parents=True)
    for s in (
        "agentic-lookml",
        "agentic-lookml-workflow",
        "generate-view-from-table",
        "lkr-code-mode",
        "lkr-project-helper",
        "looker-expressions",
        "looker-filters",
        "lookml",
        "lookml-field-curation",
    ):
        (work_dir / ".agents" / "skills" / s).mkdir(parents=True, exist_ok=True)
        (work_dir / ".agents" / "skills" / s / "SKILL.md").write_text("", encoding="utf-8")

    subprocess.run(["bash", str(SCRIPTS_DIR / "setup_repo.sh")], cwd=work_dir, env=env, check=True)
    assert "gh secret" not in spy_log.read_text(encoding="utf-8")
    installed_wf = (work_dir / ".github" / "workflows" / "lookml-pr-checks.yml").read_text(encoding="utf-8")
    assert installed_wf == (SCRIPTS_DIR.parent / "examples" / "lookml-pr-checks.yml").read_text(encoding="utf-8")

    spy_log.write_text("", encoding="utf-8")
    subprocess.run(
        ["bash", str(SCRIPTS_DIR / "setup_repo.sh"), "--sync-secrets"],
        cwd=work_dir,
        env=env,
        check=True,
    )
    assert "gh secret set LOOKERSDK_BASE_URL" in spy_log.read_text(encoding="utf-8")


def test_pre_gate_orders_unmatched_columns_by_inline_query_fields_not_json_dict_order():
    res: dict[str, Any] = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "raw_sql": (
                "SELECT COUNT(*) AS COUNT, "
                "COUNT(DISTINCT session_id) AS unique_chaotic_sessions, "
                "COUNT(DISTINCT user_id) AS distinct_clicking_humans FROM events;"
            ),
            "connection_name": "bq_conn",
            "data_json": '{"project_id": "agentic-thelook"}',
            "base_url": "https://example.looker.com",
            "validate": "false",
            "inline_queries_json": json.dumps({
                "0": {
                    "model": "agentic_thelook",
                    "view": "events",
                    "fields": ["events.count", "events.unique_sessions", "events.distinct_users"],
                }
            }),
        },
        {
            "create_sql_query": lambda body: {"slug": "sql_ev"},
            "create_query": lambda body: {"id": "301", "slug": "slug_301"},
            "run_sql_query": lambda **_kw: json.dumps([
                {
                    "COUNT": 2426072,
                    "unique_chaotic_sessions": 681596,
                    "distinct_clicking_humans": 80168,
                }
            ]),
            # Looker JSON keys returned in scrambled alphabetical order vs fields list
            "run_inline_query": lambda **_kw: json.dumps([
                {
                    "events.distinct_users": 80168,
                    "events.count": 2426072,
                    "events.unique_sessions": 681596,
                }
            ]),
        },
    )
    assert res["passed"] is True
    assert res["queries"][0]["parity_status"] == "matched"


def test_init_branch_pre_generates_only_missing_bronze_views_before_pull():
    generated_calls = []

    def fake_generate(**kw):
        generated_calls.append(kw)
        return {"new_files": [{"path": "bronze/events.view.lkml"}]}

    res: dict[str, Any] = _run_monty(
        SCRIPTS_DIR / "init_branch.py",
        {
            "project_id": "agentic-thelook",
            "ts_utc": "20261022_220000_000",
            "parsed_sql_json": json.dumps({
                "queries": [
                    {
                        "ctes": [{"name": "recent_events", "sql": "SELECT * FROM events"}],
                        "tables": [
                            {"name": "ORDERS", "db": "thelook_ecommerce", "catalog": "bigquery-public-data"},
                            {"name": "events", "db": "thelook_ecommerce", "catalog": "bigquery-public-data"},
                            {"name": "recent_events", "db": None, "catalog": None},
                        ],
                    }
                ]
            }),
        },
        {
            "me": lambda: {"id": "1"},
            "project": lambda **_kw: {"git_production_branch_name": "main", "git_remote_url": "git@github.com:o/r.git"},
            "reset_project_to_production": lambda **_kw: None,
            "create_developer_copy": lambda **_kw: None,
            "find_git_branch": lambda **_kw: {"remote_ref": "sha1"},
            "git_branch": lambda **_kw: {"ref": "sha1"},
            "create_git_branch": lambda **_kw: {},
            "all_project_files": lambda **_kw: [
                {"path": "agentic_thelook.model.lkml"},
                {"path": "bronze/orders.view.lkml"},
            ],
            "get_file_content": lambda **_kw: 'connection: "bigquery_public"\n',
            "create_project_directory": lambda **_kw: None,
            "generate_lookml_with_new_files": fake_generate,
        },
    )
    assert res["generated_bronze_files"] == ["bronze/events.view.lkml"]
    assert len(generated_calls) == 1
    assert generated_calls[0]["connection"] == "bigquery_public"
    assert generated_calls[0]["model_name"] == "agentic_thelook"
    assert generated_calls[0]["body"] == {
        "tables": [{"schema": "bigquery-public-data.thelook_ecommerce", "table_name": "events", "base_view": True}]
    }


def test_validate_and_commit_branch_checks_out_pr_branch_and_workflow_serializes():
    from looker_sdk.error import SDKError

    calls: list[tuple[str, Any]] = []

    def rec(name: str, ret: Any = None, fail_first: bool = False):
        seen = 0

        def _fn(**kw):
            nonlocal seen
            seen += 1
            calls.append((name, kw))
            if fail_first and seen == 1:
                raise SDKError("dirty workspace")
            return ret

        return _fn

    res = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {"project_id": "agentic-thelook", "branch_name": "20261023_070000_000_1"},
        {
            "reset_project_to_remote": rec("reset_remote", fail_first=True),
            "reset_project_to_production": rec("reset_prod"),
            "create_developer_copy": rec("create_dev"),
            "project": rec("project", {"git_production_branch_name": "main"}),
            "update_git_branch": rec("update_branch"),
            "validate_project": rec("validate", {"errors": []}),
            "run_lookml_test": rec("test", [{"test_name": "t1", "success": True}]),
        },
    )
    assert res["passed"] is True
    assert res["committed"] is False
    assert [c[0] for c in calls] == [
        "reset_remote",
        "reset_prod",
        "project",
        "update_branch",
        "reset_remote",
        "validate",
        "test",
    ]
    assert calls[3][1]["body"] == {"name": "20261023_070000_000_1"}

    wf_yml = (SCRIPTS_DIR.parent / "examples" / "lookml-pr-checks.yml").read_text()
    assert "group: looker-dev-${{ vars.LOOKER_PROJECT_NAME || github.repository }}" in wf_yml
    assert "cancel-in-progress: false" in wf_yml
    assert '--var branch_name="$BRANCH_NAME"' in wf_yml

    yaml_mod = importlib.import_module("yaml")
    wf = yaml_mod.safe_load(wf_yml)
    jobs = wf["jobs"]
    assert list(jobs) == ["snapshots", "validator", "data-tests", "query-parity"]
    assert "LOOKERSDK_" not in json.dumps(jobs["snapshots"])
    assert "needs" not in jobs["snapshots"]
    assert "needs" not in jobs["validator"]
    assert jobs["data-tests"]["needs"] == ["validator"]
    assert jobs["query-parity"]["needs"] == ["validator", "data-tests"]
    assert jobs["query-parity"]["permissions"]["pull-requests"] == "read"

    # validator mode: skip_tests="true" runs validate_project only
    calls.clear()
    res_val = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {"project_id": "agentic-thelook", "branch_name": "b1", "skip_tests": "true"},
        {
            "reset_project_to_remote": rec("reset_remote"),
            "project": rec("project", {"git_production_branch_name": "main"}),
            "update_git_branch": rec("update_branch"),
            "validate_project": rec("validate", {"errors": []}),
            "run_lookml_test": rec("test", []),
        },
    )
    assert res_val["passed"] is True
    assert [c[0] for c in calls] == ["reset_remote", "project", "update_branch", "reset_remote", "validate"]

    # data-tests mode right after validator: head_sha matches -> fast-paths git sync & skips validate_project
    calls.clear()
    res_dt_fast = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {"project_id": "agentic-thelook", "branch_name": "b1", "head_sha": "sha_b1", "skip_validate": "true"},
        {
            "git_branch": rec("git_branch", {"name": "b1", "ref": "sha_b1"}),
            "reset_project_to_remote": rec("reset_remote"),
            "validate_project": rec("validate", {"errors": []}),
            "run_lookml_test": rec("test", [{"test_name": "t1", "success": True}]),
        },
    )
    assert res_dt_fast["passed"] is True
    assert [c[0] for c in calls] == ["git_branch", "test"]

    # data-tests standalone "Re-run failed jobs" after dev workspace moved: re-syncs branch
    calls.clear()
    res_dt_rerun = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {"project_id": "agentic-thelook", "branch_name": "b1", "head_sha": "sha_b1", "skip_validate": "true"},
        {
            "git_branch": rec("git_branch", {"name": "other_branch", "ref": "sha_other"}),
            "reset_project_to_remote": rec("reset_remote"),
            "project": rec("project", {"git_production_branch_name": "main"}),
            "update_git_branch": rec("update_branch"),
            "validate_project": rec("validate", {"errors": []}),
            "run_lookml_test": rec("test", [{"test_name": "t1", "success": True}]),
        },
    )
    assert res_dt_rerun["passed"] is True
    assert [c[0] for c in calls] == ["git_branch", "reset_remote", "project", "update_branch", "reset_remote", "test"]

    # query-parity branch-sync only mode (skip_validate="true" + skip_tests="true"): re-syncs branch without running checks
    calls.clear()
    res_sync_only = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {
            "project_id": "agentic-thelook",
            "branch_name": "b1",
            "head_sha": "sha_b1",
            "skip_validate": "true",
            "skip_tests": "true",
        },
        {
            "git_branch": rec("git_branch", {"name": "other_branch", "ref": "sha_other"}),
            "reset_project_to_remote": rec("reset_remote"),
            "project": rec("project", {"git_production_branch_name": "main"}),
            "update_git_branch": rec("update_branch"),
            "validate_project": rec("validate", {"errors": []}),
            "run_lookml_test": rec("test", []),
        },
    )
    assert res_sync_only["passed"] is True
    assert [c[0] for c in calls] == ["git_branch", "reset_remote", "project", "update_branch", "reset_remote"]


def test_pre_gate_percent_scaling_unordered_group_by_and_share_url_fallback():
    raw_sql = (
        "SELECT department, COUNT(id) AS sku_count, "
        "ROUND(AVG(retail_price - cost), 2) AS avg_dollar_markup, "
        "ROUND(AVG((retail_price - cost) / NULLIF(cost, 0)) * 100, 2) AS avg_markup_greed_pct "
        "FROM `bigquery-public-data.thelook_ecommerce.products` GROUP BY department;\n"
        "SELECT category, department, COUNT(id) AS skus, "
        "ROUND(AVG((retail_price - cost) / NULLIF(cost, 0)) * 100, 2) AS markup_pct "
        "FROM `bigquery-public-data.thelook_ecommerce.products` "
        "GROUP BY category, department ORDER BY markup_pct DESC LIMIT 2;"
    )
    sql_results = {
        "sql_0": [
            {"department": "Men", "sku_count": 13131, "avg_dollar_markup": 28.12, "avg_markup_greed_pct": 81.16},
            {"department": "Women", "sku_count": 15989, "avg_dollar_markup": 29.54, "avg_markup_greed_pct": 110.01},
        ],
        "sql_1": [
            {"category": "Socks", "department": "Women", "skus": 400, "markup_pct": 140.25},
            {"category": "Jeans", "department": "Men", "skus": 900, "markup_pct": 95.50},
        ],
    }
    looker_results = [
        # Unordered GROUP BY: Looker returns Women before Men, and unscaled percent_2 decimals (1.10012, 0.81164)
        [
            {
                "products.department": "Women",
                "products.count": 15989,
                "products.avg_dollar_markup": 29.5419,
                "products.avg_markup_ratio": 1.10012,
            },
            {
                "products.department": "Men",
                "products.count": 13131,
                "products.avg_dollar_markup": 28.1204,
                "products.avg_markup_ratio": 0.81164,
            },
        ],
        # Ordered query: reversed order in Looker MUST fail parity when top-level ORDER BY is present
        [
            {
                "products.category": "Jeans",
                "products.department": "Men",
                "products.count": 900,
                "products.avg_markup_ratio": 0.955,
            },
            {
                "products.category": "Socks",
                "products.department": "Women",
                "products.count": 400,
                "products.avg_markup_ratio": 1.4025,
            },
        ],
    ]
    created_slugs = iter(["sql_0", "sql_1"])
    inline_iter = iter(looker_results)

    res: dict[str, Any] = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "raw_sql": raw_sql,
            "connection_name": "bq_conn",
            "data_json": '{"project_id": "agentic-thelook"}',
            "base_url": "",
            "validate": "false",
            "inline_queries_json": json.dumps({
                "0": {
                    "model": "agentic_thelook",
                    "view": "products",
                    "fields": [
                        "products.department",
                        "products.count",
                        "products.avg_dollar_markup",
                        "products.avg_markup_ratio",
                    ],
                },
                "1": {
                    "model": "agentic_thelook",
                    "view": "products",
                    "fields": [
                        "products.category",
                        "products.department",
                        "products.count",
                        "products.avg_markup_ratio",
                    ],
                    "sorts": ["products.avg_markup_ratio desc"],
                },
            }),
        },
        {
            "create_sql_query": lambda body: {"slug": next(created_slugs)},
            "create_query": lambda body: {
                "id": "501",
                "slug": "qslug",
                "share_url": "https://demo.cloud.looker.com/x/qslug",
            },
            "run_sql_query": lambda slug, **_kw: json.dumps(sql_results[slug]),
            "run_inline_query": lambda **_kw: json.dumps(next(inline_iter)),
        },
    )
    assert res["queries"][0]["parity_status"] == "matched"
    assert res["queries"][0]["sql_runner_url"] == "https://demo.cloud.looker.com/sql/sql_0"
    assert res["queries"][0]["explore_url"] == "https://demo.cloud.looker.com/x/qslug"
    assert res["queries"][1]["sql_runner_url"] == "https://demo.cloud.looker.com/sql/sql_1"
    assert res["queries"][1]["parity_status"] == "mismatched"
    assert res["passed"] is False

    # Window OVER (ORDER BY ...) has no top-level ORDER BY -> still sorts rows deterministically
    pre_mod = _load_module("pre_gate_mod", SCRIPTS_DIR / "pre_gate.py")
    ok_win, diffs_win = pre_mod.compare_row_sets(
        [{"dept": None, "pct": 25.0}, {"dept": "Accessories", "pct": 75.0}],
        [{"p.dept": "Accessories", "p.pct": 0.75}, {"p.dept": None, "p.pct": 0.25}],
        sql="WITH w AS (SELECT *, ROW_NUMBER() OVER (ORDER BY id) FROM p) SELECT dept, 100.0 * COUNT(*) / 4 AS pct FROM w GROUP BY dept",
        looker_fields=["p.dept", "p.pct"],
    )
    assert ok_win is True and diffs_win == []

    # Non-percentage SQL column (no * 100) must NOT accept a 100x-off Looker value
    ok_non_pct, _ = pre_mod.compare_row_sets(
        [{"val": 81.16}],
        [{"p.val": 0.8116}],
        sql="SELECT ROUND(AVG(val), 2) AS val FROM p",
        looker_fields=["p.val"],
    )
    assert ok_non_pct is False

    # Joined queries selecting multiple .count measures must not collide on leaf name "count"
    ok_2cnt, diffs_2cnt = pre_mod.compare_row_sets(
        [{"country": "US", "registered_users": 100, "items_purchased": 250}],
        [{"order_items.count": 250, "users.count": 100, "users.country": "US"}],
        sql="SELECT u.country, COUNT(DISTINCT u.id) AS registered_users, COUNT(oi.id) AS items_purchased FROM users u LEFT JOIN order_items oi ON u.id = oi.user_id GROUP BY 1",
        looker_fields=["users.country", "users.count", "order_items.count"],
    )
    assert ok_2cnt is True and diffs_2cnt == []
    ok_2cnt_swap, _ = pre_mod.compare_row_sets(
        [{"country": "US", "registered_users": 100, "items_purchased": 250}],
        [{"order_items.count": 100, "users.count": 250, "users.country": "US"}],
        looker_fields=["users.country", "users.count", "order_items.count"],
    )
    assert ok_2cnt_swap is False


def test_pre_gate_order_by_round_ties_and_pr_data_json_compaction():
    sql = (
        "SELECT dc.name AS warehouse_name, "
        "ROUND(100.0 * COUNTIF(ii.sold_at IS NOT NULL) / COUNT(ii.id), 2) AS sell_through_rate_pct "
        "FROM dc INNER JOIN ii ON dc.id = ii.dc_id GROUP BY dc.name ORDER BY sell_through_rate_pct DESC"
    )
    sql_rows = [
        {"warehouse_name": "Memphis TN", "sell_through_rate_pct": 40.0},
        {"warehouse_name": "Port Authority NY/NJ", "sell_through_rate_pct": 37.06},
        {"warehouse_name": "Savannah GA", "sell_through_rate_pct": 37.06},
    ]
    looker_rows = [
        {"dc.name": "Memphis TN", "ii.sell_through_rate": 0.40},
        {"dc.name": "Savannah GA", "ii.sell_through_rate": 0.370645},
        {"dc.name": "Port Authority NY/NJ", "ii.sell_through_rate": 0.370588},
    ]
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "raw_sql": sql,
            "connection_name": "bq",
            "base_url": "https://demo.cloud.looker.com",
            "validate": "false",
            "data_json": json.dumps({"run_id": "r1"}),
            "inline_queries_json": json.dumps(
                {"0": {"model": "m", "view": "ii", "fields": ["dc.name", "ii.sell_through_rate"]}}
            ),
        },
        {
            "create_sql_query": lambda **kw: {"slug": "s0"},
            "run_sql_query": lambda **kw: json.dumps(sql_rows),
            "create_query": lambda **kw: {"id": "1", "slug": "q0"},
            "run_inline_query": lambda **kw: json.dumps(looker_rows),
        },
    )
    assert res["passed"] is True and res["all_queries_matched"] is True

    ok_rev, diffs_rev = compare_row_sets(
        sql_rows,
        list(reversed(looker_rows)),
        sql=sql,
        looker_fields=["dc.name", "ii.sell_through_rate"],
    )
    assert ok_rev is False and diffs_rev

    pr_sh = (SCRIPTS_DIR / "create_github_pr.sh").read_text()
    assert "jq -c 'del(.test_query_results, .queries[]?.sql_rows)'" in pr_sh
    assert 'elif [[ "$lang" == "json" ]]; then jq -c .' in pr_sh
    assert "limit=40000" in pr_sh

    seen_fids: list[str | None] = []
    res_fid = _run_monty(
        SCRIPTS_DIR / "validate_and_commit_branch.py",
        {
            "project_id": "p",
            "file_ids": "./data/run_1/lookml/tests/bronze/events.test.lkml",
            "test_names": "t1",
            "skip_validate": "true",
        },
        {"run_lookml_test": lambda **kw: seen_fids.append(kw.get("file_id")) or [{"success": True}]},
    )
    assert res_fid["passed"] is True and seen_fids == ["tests/bronze/events.test.lkml"]


def test_pre_gate_limit_boundary_tie_and_digit_string_preservation():
    sql = "SELECT depth, uri_segment, COUNT(id) AS click_hits, APPROX_COUNT_DISTINCT(sid) AS approx_sessions FROM e GROUP BY 1, 2 ORDER BY click_hits DESC LIMIT 3"
    sql_rows = [
        {"depth": 0, "uri_segment": "product", "click_hits": 100, "approx_sessions": 80},
        {"depth": 1, "uri_segment": "men", "click_hits": 60, "approx_sessions": 50},
        {"depth": 1, "uri_segment": "20095", "click_hits": 59, "approx_sessions": 37},
    ]
    top3_looker = [
        {"u.depth": 0, "u.uri_segment": "product", "e.count": 100, "e.approx_sessions": 80},
        {"u.depth": 1, "u.uri_segment": "men", "e.count": 60, "e.approx_sessions": 50},
        {"u.depth": 1, "u.uri_segment": "25560", "e.count": 59, "e.approx_sessions": 41},
    ]
    expanded_looker = [
        *top3_looker,
        {"u.depth": 1, "u.uri_segment": "20095", "e.count": 59, "e.approx_sessions": 37},
    ]
    limits_called: list[str | None] = []

    def fake_inline(**kw):
        lim = (kw.get("body") or {}).get("limit")
        limits_called.append(lim)
        return json.dumps(expanded_looker if lim == "500" else top3_looker)

    q_fields = ["u.depth", "u.uri_segment", "e.count", "e.approx_sessions"]
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "raw_sql": sql,
            "connection_name": "bq",
            "base_url": "https://demo.cloud.looker.com",
            "validate": "false",
            "data_json": json.dumps({"run_id": "r2"}),
            "inline_queries_json": json.dumps(
                {"0": {"model": "m", "view": "e", "fields": q_fields, "limit": "3"}}
            ),
        },
        {
            "create_sql_query": lambda **kw: {"slug": "s0"},
            "run_sql_query": lambda **kw: json.dumps(sql_rows),
            "create_query": lambda **kw: {"id": "1", "slug": "q0"},
            "run_inline_query": fake_inline,
        },
    )
    assert res["passed"] is True and limits_called == ["3", "500"]

    # Digit strings keep string formatting on mismatch; wrong value in tie pool still fails
    bad_pool = [*top3_looker, {"u.depth": 1, "u.uri_segment": "20095", "e.count": 59, "e.approx_sessions": 999}]
    ok_bad, diffs_bad = compare_row_sets(
        sql_rows, top3_looker, sql=sql, looker_fields=q_fields, fetch_extra=lambda _: bad_pool
    )
    assert ok_bad is False and "SQL=20095, Looker=25560" in diffs_bad[0]

    # Leading-zero string codes must not collide with stripped integers
    ok_zip, diffs_zip = compare_row_sets([{"zip": "02110"}], [{"u.zip": "2110"}])
    assert ok_zip is False and "SQL=02110, Looker=2110" in diffs_zip[0]


def test_pre_gate_unordered_limit_fallback_and_grain_key_stripping():
    sql = "SELECT first_name, age FROM `proj.ds.users` WHERE age < 25 LIMIT 2 -- sample;"
    raw_sql_rows = [{"first_name": "Zoe", "age": 22}, {"first_name": "Mia", "age": 19}]
    det_sql_rows = [{"first_name": "Aaron", "age": 18}, {"first_name": "Aaron", "age": 18}]
    raw_lkr_rows = [
        {"users.first_name": "Liam", "users.age": 20, "users.id": 50},
        {"users.first_name": "Noah", "users.age": 21, "users.id": 51},
    ]
    det_lkr_rows = [
        {"users.first_name": "Aaron", "users.age": 18, "users.id": 1},
        {"users.first_name": "Aaron", "users.age": 18, "users.id": 9},
    ]
    created_sqls: list[dict[str, Any]] = []
    inline_sorts: list[Any] = []

    def fake_create_sql(body):
        created_sqls.append(body)
        return {"slug": "det" if "_lkr_det" in body["sql"] else "raw"}

    def fake_run_sql(slug, **_kw):
        return json.dumps(det_sql_rows if slug == "det" else raw_sql_rows)

    def fake_inline(body, **_kw):
        inline_sorts.append(body.get("sorts"))
        return json.dumps(det_lkr_rows if body.get("sorts") else raw_lkr_rows)

    q_fields = ["users.first_name", "users.age", "users.id"]
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "data_json": json.dumps({
                "run_id": "r_det",
                "connection_name": "bq_conn",
                "queries": [
                    {
                        "query_index": 0,
                        "sql_query_id": "raw",
                        "sql": sql,
                        "inline_query": {"model": "m", "view": "users", "fields": q_fields, "limit": "2"},
                    }
                ],
            }),
        },
        {
            "create_sql_query": fake_create_sql,
            "run_sql_query": fake_run_sql,
            "run_inline_query": fake_inline,
        },
    )
    assert res["passed"] is True
    assert created_sqls == [
        {
            "connection_name": "bq_conn",
            "sql": "SELECT * FROM (\nSELECT first_name, age FROM `proj.ds.users` WHERE age < 25\n) AS _lkr_det ORDER BY 1, 2 LIMIT 2",
        }
    ]
    assert inline_sorts == [None, ["users.first_name asc", "users.age asc"]]

    # Also strips common_helpers.no_group directly while still rejecting extra non-key columns
    ok_ng, _ = compare_row_sets(
        [{"first_name": "Ada"}],
        [{"users.first_name": "Ada", "common_helpers.no_group": 1}],
        looker_fields=["users.first_name", "common_helpers.no_group"],
    )
    assert ok_ng is True
    ok_extra, diffs_extra = compare_row_sets(
        [{"first_name": "Ada"}],
        [{"users.first_name": "Ada", "users.count": 5}],
        looker_fields=["users.first_name", "users.count"],
    )
    assert ok_extra is False and "column count mismatch" in diffs_extra[0]


def test_pre_gate_timestamp_normalization_and_same_second_sort_ties():
    sql = "SELECT order_id, created_at FROM `proj.ds.orders` ORDER BY created_at DESC LIMIT 2;"
    s_rows = [
        {"order_id": 10, "created_at": "2026-10-25 00:20:01.720336 UTC"},
        {"order_id": 11, "created_at": "2026-10-25 00:20:01.105 UTC"},
    ]
    l_rows = [
        {"orders.order_id": 11, "orders.created_time": "2026-10-25 00:20:01"},
        {"orders.order_id": 12, "orders.created_time": "2026-10-25 00:20:01"},
    ]
    pool_rows = [
        *l_rows,
        {"orders.order_id": 10, "orders.created_time": "2026-10-25 00:20:01"},
    ]
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "data_json": json.dumps({
                "run_id": "r_ts",
                "queries": [
                    {
                        "query_index": 0,
                        "sql_query_id": "s_ts",
                        "sql": sql,
                        "inline_query": {
                            "model": "m",
                            "view": "orders",
                            "fields": ["orders.order_id", "orders.created_time"],
                            "sorts": ["orders.created_time desc"],
                            "limit": "2",
                        },
                    }
                ],
            }),
        },
        {
            "run_sql_query": lambda **_kw: json.dumps(s_rows),
            "run_inline_query": lambda body, **_kw: json.dumps(pool_rows if body.get("limit") == "500" else l_rows),
        },
    )
    assert res["passed"] is True
    # Discrete ORDER BY tie-pool up to 500 rows (even when limit_n > 450)
    assert compare_row_sets(
        [{"id": i, "p": 9.0} for i in range(499)], [{"o.id": i + 1, "o.p": 9.0} for i in range(499)],
        sql="SELECT id, p FROM o ORDER BY p DESC LIMIT 499", fetch_extra=lambda n: [{"o.id": i, "o.p": 9.0} for i in range(n)],
    )[0]
    # When Looker emits subseconds (<group>_microsecond), subsecond differences still fail
    ok_sub, _ = compare_row_sets(
        [{"created_at": "2026-10-25T00:20:01.000000Z"}],
        [{"orders.created_microsecond": "2026-10-25 00:20:01.500000"}],
    )
    assert ok_sub is False


def test_pre_gate_volatile_current_timestamp_pins_compiled_sql_and_falls_back_for_post_sql():
    # 1. Primary path: compiles Looker SQL via result_format="sql", pins CURRENT_TIMESTAMP / CURRENT_DATE / NOW()
    #    to run_id's fixed UTC timestamp in both raw SQL and compiled Looker SQL, remaps aliases, strips __sort_,
    #    ignores literals/comments/aliases, and preserves original sql_query_id + sql.
    raw_sql = (
        "-- keep CURRENT_TIMESTAMP() in comment\n"
        "SELECT CASE WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, DAY) < 90 "
        "THEN '1. Fresh (<90d)' ELSE '2. Aged' END AS aging_tier, "
        "COUNTIF(note != 'CURRENT_TIMESTAMP()' AND DATE(created_at) <= CURRENT_DATE('America/Los_Angeles') "
        "AND updated_at <= NOW()) AS unsold_units "
        "FROM ii GROUP BY 1 ORDER BY 2 DESC"
    )
    compiled_looker_sql = (
        "-- raw sql results do not include filled-in values\n"
        "SELECT\n"
        "  CASE WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), ii.created_at, DAY) < 90 "
        "THEN '1. Fresh (<90d)' ELSE '2. Aged' END AS ii_aging_tier,\n"
        "  CASE WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), ii.created_at, DAY) < 90 THEN 0 ELSE 1 END AS ii_aging_tier__sort_,\n"
        "  COUNTIF(ii.note != 'CURRENT_TIMESTAMP()' AND DATE(ii.created_at) <= CURRENT_DATE('America/Los_Angeles') "
        "AND ii.updated_at <= CURRENT_TIMESTAMP()) AS ii_unsold_units\n"
        "FROM ii GROUP BY 1, 2 ORDER BY 3 DESC"
    )
    pinned_sql_seen: dict[str, str] = {}

    def fake_create_sql(body):
        slug = f"pin_{len(pinned_sql_seen)}"
        pinned_sql_seen[slug] = body["sql"]
        return {"slug": slug}

    def fake_run_sql(slug, **_kw):
        assert slug.startswith("pin_"), "Pinned mode should execute pinned SQL slugs rather than stale cached slug"
        sql_txt = pinned_sql_seen[slug]
        if "AS ii_aging_tier" in sql_txt:
            return json.dumps([
                {
                    "ii_aging_tier": "1. Fresh (<90d)",
                    "ii_aging_tier__sort_": 0,
                    "ii_unsold_units": 11221,
                }
            ])
        return json.dumps([{"aging_tier": "1. Fresh (<90d)", "unsold_units": 11221}])

    inline_formats: list[str] = []

    def fake_inline(result_format, body, **_kw):
        inline_formats.append(result_format)
        assert result_format == "sql"
        return compiled_looker_sql

    base_q = {
        "query_index": 0,
        "sql_query_id": "s_saved",
        "sql": raw_sql,
        "sql_rows": [{"stale": 1}],
        "inline_query": {"model": "m", "view": "ii", "fields": ["ii.aging_tier", "ii.unsold_units"]},
    }
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "data_json": json.dumps({
                "run_id": "20261026_063352_055_1",
                "connection_name": "bq_conn",
                "queries": [base_q],
            })
        },
        {
            "create_sql_query": fake_create_sql,
            "run_sql_query": fake_run_sql,
            "run_inline_query": fake_inline,
        },
    )
    assert res["passed"] is True
    assert inline_formats == ["sql"]
    assert res["queries"][0]["sql_query_id"] == "s_saved"
    assert res["queries"][0]["sql"] == raw_sql
    assert "sql_rows" not in res["queries"][0]
    assert len(pinned_sql_seen) == 2
    for s_txt in pinned_sql_seen.values():
        assert "CAST('2026-10-26 06:33:52+00:00' AS TIMESTAMP)" in s_txt
        assert "DATE(CAST('2026-10-26 06:33:52+00:00' AS TIMESTAMP), 'America/Los_Angeles')" in s_txt
        assert "!= 'CURRENT_TIMESTAMP()'" in s_txt
    pre_mod = _load_module("pre_gate_remap", SCRIPTS_DIR / "pre_gate.py")
    assert pre_mod._remap_compiled_rows(
        [{"ii_aging_tier__sort_": 0, "ii_other__sort_": 1}], ["ii.aging_tier__sort_"]
    ) == [{"ii.aging_tier__sort_": 0}]

    # 2. Post-SQL fallback (e.g., table_calculation present): bypasses compiled-SQL mode and retries uncached live
    tc_sql = "SELECT COUNTIF(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, DAY) < 90) AS fresh_units FROM ii"
    cache_flags: list[Any] = []
    tc_q = {
        "query_index": 0,
        "sql_query_id": "s_cached",
        "sql": tc_sql,
        "inline_query": {
            "model": "m",
            "view": "ii",
            "fields": ["ii.fresh_units"],
            "dynamic_fields": json.dumps([{"table_calculation": "tc_units", "expression": "${ii.fresh_units}"}]),
        },
    }
    res_tc = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {"data_json": json.dumps({"run_id": "r_vol", "connection_name": "bq_conn", "queries": [tc_q]})},
        {
            "create_sql_query": lambda body: {"slug": "s_live"},
            "run_sql_query": lambda slug, **_kw: json.dumps(
                [{"fresh_units": 11221 if slug == "s_live" else 11222}]
            ),
            "run_inline_query": lambda body, **kw: cache_flags.append(kw.get("cache"))
            or json.dumps([{"tc_units": 11221}]),
        },
    )
    assert res_tc["passed"] is True and cache_flags == [False, False]

    # 3. Genuine LookML logic mismatch under pinned timestamp still fails immediately
    res_bad = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {"data_json": json.dumps({"run_id": "20261026_063352_055_1", "connection_name": "bq_conn", "queries": [base_q]})},
        {
            "create_sql_query": fake_create_sql,
            "run_sql_query": lambda slug, **_kw: json.dumps(
                [{"ii_aging_tier": "1. Fresh (<90d)", "ii_unsold_units": 0}]
                if "AS ii_aging_tier" in pinned_sql_seen[slug]
                else [{"aging_tier": "1. Fresh (<90d)", "unsold_units": 11221}]
            ),
            "run_inline_query": fake_inline,
        },
    )
    assert res_bad["passed"] is False


def test_pre_gate_native_case_ordinal_prefix_stripping_and_order_enforcement():
    sql = "SELECT CASE WHEN x < 10 THEN '1. North' ELSE '2. Europe' END AS region, country, COUNT(id) AS cnt FROM u GROUP BY 1, 2 ORDER BY region, cnt DESC"
    s_rows = [
        {"region": "1. North", "country": "US", "cnt": 50},
        {"region": "2. Europe", "country": "UK", "cnt": 20},
        {"region": "2. Europe", "country": "FR", "cnt": 20},
    ]
    l_rows = [
        {"u.region": "North", "u.country": "US", "u.cnt": 50},
        {"u.region": "Europe", "u.country": "FR", "u.cnt": 20},
        {"u.region": "Europe", "u.country": "UK", "u.cnt": 20},
    ]
    res = _run_monty(
        SCRIPTS_DIR / "pre_gate.py",
        {
            "data_json": json.dumps({
                "run_id": "r_ord",
                "queries": [
                    {
                        "query_index": 0,
                        "sql_query_id": "s_ord",
                        "sql": sql,
                        "inline_query": {"model": "m", "view": "u", "fields": ["u.region", "u.country", "u.cnt"]},
                    }
                ],
            })
        },
        {
            "run_sql_query": lambda **_kw: json.dumps(s_rows),
            "run_inline_query": lambda **_kw: json.dumps(l_rows),
        },
    )
    assert res["passed"] is True

    # Wrong LookML case: branch order (e.g. bucket #1 accidentally placed in else:) must still fail ORDER BY parity
    bad_order = [l_rows[1], l_rows[2], l_rows[0]]
    ok_bad, diffs_bad = compare_row_sets(s_rows, bad_order, sql=sql, looker_fields=["u.region", "u.country", "u.cnt"])
    assert ok_bad is False and "SQL=North, Looker=Europe" in diffs_bad[0]

    # Legacy LookML dimensions that retain '1. ' prefixes still match 1-to-1
    ok_leg, _ = compare_row_sets(
        [{"tier": "1. Impulse"}],
        [{"p.tier": "1. Impulse"}],
        sql="SELECT tier FROM p ORDER BY tier",
        looker_fields=["p.tier"],
    )
    assert ok_leg is True









