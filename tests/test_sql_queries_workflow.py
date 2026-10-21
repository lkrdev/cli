import importlib.util
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "agentic-lookml-workflow" / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


init_mod = _load_module("init_sql_queries", SCRIPTS_DIR / "init_sql_queries.py")
verify_mod = _load_module("record_query_parity", SCRIPTS_DIR / "record_query_parity.py")

split_sql_statements = init_mod.split_sql_statements
compare_row_sets = verify_mod.compare_row_sets
normalize_val = verify_mod.normalize_val


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


def test_init_sql_queries_defaults_to_connection_name():
    script_path = SCRIPTS_DIR / "init_sql_queries.py"
    source = script_path.read_text()
    called_bodies = []

    def fake_create_sql_query(body):
        called_bodies.append(body)
        return {"slug": "sql123"}

    ns = {
        "raw_sql": "SELECT 1",
        "base_url": "https://example.looker.com",
        "connection_name": "bq_conn",
        "data_json": "{}",
        "create_sql_query": fake_create_sql_query,
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    assert called_bodies == [{"connection_name": "bq_conn", "sql": "SELECT 1"}]


def test_init_branch_prefers_remote_ref_over_ref():
    script_path = SCRIPTS_DIR / "init_branch.py"
    source = script_path.read_text()
    assert "globals(" not in source

    updated_branches = []

    def fake_update_git_branch(project_id, body):
        updated_branches.append((project_id, body))
        return body

    ns: dict[str, Any] = {
        "project_id": "agentic-thelook",
        "ts_utc": "20261021_070000_000",
        "me": lambda: {"id": "42"},
        "project": lambda **_kw: {"git_production_branch_name": "main", "git_remote_url": "git@github.com:org/repo.git"},
        "reset_project_to_production": lambda **_kw: None,
        "create_developer_copy": lambda **_kw: None,
        "all_git_branches": lambda **_kw: [
            {"name": "main", "is_production": True, "ref": "local_stale_sha", "remote_ref": "origin_latest_sha"},
            {"name": "feature", "is_production": False, "ref": "feat_sha", "remote_ref": "feat_remote_sha"},
        ],
        "git_branch": lambda **_kw: {"name": "main", "ref": "local_stale_sha"},
        "create_git_branch": lambda **_kw: None,
        "update_git_branch": fake_update_git_branch,
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    result: dict[str, Any] = ns["main"]()
    assert result["production_ref"] == "origin_latest_sha"
    assert updated_branches == [
        ("agentic-thelook", {"name": "20261021_070000_000_42", "ref": "origin_latest_sha"}),
        ("agentic-thelook", {"name": "20261021_070000_000_42", "ref": "origin_latest_sha"}),
    ]



def test_validate_and_commit_pushes_branch_to_remote():
    script_path = SCRIPTS_DIR / "validate_and_commit_branch.py"
    source = script_path.read_text()
    assert "globals(" not in source

    pushed_paths = []

    def fake_post(path, **_kw):
        pushed_paths.append(path)
        return ""

    ns = {
        "project_id": "agentic-thelook",
        "commit_message": "feat(lookml): refactor SQL queries",
        "skip_tests": "true",
        "validate_project": lambda **_kw: {"errors": []},
        "run_lookml_test": lambda **_kw: [],
        "commit": lambda **_kw: {},
        "post": fake_post,
        "encode_path_param": lambda s: s,
        "git_branch": lambda **_kw: {"name": "20261020_093734_975_1", "ref": "abc1234"},
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    assert pushed_paths == ["/projects/agentic-thelook/push_branch"]


def test_no_monty_globals_in_skill_scripts():
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    for py_file in skills_dir.rglob("*.py"):
        text = py_file.read_text()
        assert "globals().get(" not in text, f"{py_file} uses globals().get()"
        assert "locals().get(" not in text, f"{py_file} uses locals().get()"


def test_record_query_parity_compare_row_sets_matches_aliased_count():
    script_path = SCRIPTS_DIR / "record_query_parity.py"
    source = script_path.read_text()
    # Extract everything up to the main execution loop
    helper_src = source.split("data = json.loads(data_json)")[0]
    ns: dict = {}
    exec(compile(helper_src, str(script_path), "exec"), ns)  # noqa: S102
    compare_row_sets = ns["compare_row_sets"]

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

    ns: dict[str, Any] = {
        "raw_sql": "SELECT id, count FROM orders WHERE status = 'Complete';",
        "connection_name": "thelook_conn",
        "data_json": '{"project_id": "thelook"}',
        "base_url": "https://example.looker.com",
        "validate": "true",
        "validate_project": lambda **_kw: {"errors": []},
        "inline_queries_json": '{"0": {"model": "thelook", "view": "orders", "fields": ["orders.id", "orders.count"]}}',
        "create_sql_query": fake_create_sql_query,
        "create_query": fake_create_query,
        "run_sql_query": lambda **_kw: '[{"id": 1, "count": 10}]',
        "run_inline_query": lambda **_kw: '[{"orders.id": 1, "orders.count": 10}]',
    }
    exec(compile(source, str(script_path), "exec"), ns)  # noqa: S102
    res: dict[str, Any] = ns["result"]

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
    assert created_sql == [{"connection_name": "thelook_conn", "sql": "SELECT id, count FROM orders WHERE status = 'Complete'"}]
    assert len(created_looker_queries) == 1
