import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lkr.main import app
from lkr.parse.lookml_snapshot import (
    normalize_sql,
    run_lookml_snapshot,
    strip_positions,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_ci_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CI", raising=False)


@pytest.fixture
def sample_lookml_project(tmp_path: Path) -> Path:
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir(parents=True, exist_ok=True)

    (proj_dir / "manifest.lkml").write_text(
        'project_name: "ecommerce_analytics"\n'
        'constant: db_conn { value: "analytics_db" }\n',
        encoding="utf-8",
    )
    (proj_dir / "users.view.lkml").write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "    required_access_grants: [marketing, finance]\n"
        "  }\n"
        "  dimension: email {\n"
        "    type: string\n"
        "    sql: ${TABLE}.email ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (proj_dir / "shop.model.lkml").write_text(
        'connection: "snowflake_prod"\n'
        'include: "*.view.lkml"\n'
        "access_grant: pii_access {\n"
        "  user_attribute: can_view_pii\n"
        '  allowed_values: ["yes", "true"]\n'
        "}\n"
        "explore: users {\n"
        "  required_access_grants: [pii_access]\n"
        "}\n"
        "test: test_user_id_unique {\n"
        "  explore_source: users {\n"
        "    column: id { field: users.id }\n"
        "  }\n"
        "  assert: id_not_null {\n"
        "    expression: ${users.id} is not null ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    return proj_dir


def test_snapshot_first_run_writes_files(sample_lookml_project: Path):
    res = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res.exit_code == 0
    assert "4 snapshots written" in res.output

    snap_dir = sample_lookml_project / "__snapshots__"
    assert (snap_dir / "ecommerce_analytics.tests.snap.json").exists()
    assert (snap_dir / "ecommerce_analytics.access.snap.json").exists()
    assert (snap_dir / "ecommerce_analytics.connections.snap.json").exists()
    assert (snap_dir / "ecommerce_analytics.manifest.snap.json").exists()

    # Verify content of connections
    conn_data = json.loads((snap_dir / "ecommerce_analytics.connections.snap.json").read_text(encoding="utf-8"))
    assert "shop" in conn_data
    assert conn_data["shop"]["connection"] == "snowflake_prod"


def test_snapshot_verify_passes(sample_lookml_project: Path):
    # First write
    res1 = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res1.exit_code == 0

    # Second run checks and passes
    res2 = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res2.exit_code == 0
    assert "4 snapshots passed" in res2.output


def test_snapshot_line_shift_insensitivity(sample_lookml_project: Path):
    runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])

    # Prepend empty lines and comments to shift line numbers
    model_file = sample_lookml_project / "shop.model.lkml"
    content = model_file.read_text(encoding="utf-8")
    model_file.write_text("# Shift comment 1\n# Shift comment 2\n\n\n" + content, encoding="utf-8")

    # Semantic equality check must pass despite line shift
    res = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res.exit_code == 0
    assert "4 snapshots passed" in res.output


def test_snapshot_sql_normalization_and_set_sorting(sample_lookml_project: Path):
    runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])

    # Invert required_access_grants list order and add erratic SQL whitespace
    view_file = sample_lookml_project / "users.view.lkml"
    view_file.write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql:    ${TABLE}.id    ;;\n"
        "    required_access_grants: [finance, marketing]\n"
        "  }\n"
        "  dimension: email {\n"
        "    type: string\n"
        "    sql: ${TABLE}.email ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    res = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res.exit_code == 0
    assert "4 snapshots passed" in res.output


def test_snapshot_mismatch_fails_with_jest_diff(sample_lookml_project: Path):
    runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])

    # Mutate test assertion
    model_file = sample_lookml_project / "shop.model.lkml"
    content = model_file.read_text(encoding="utf-8")
    model_file.write_text(content.replace("${users.id} is not null", "${users.id} is null"), encoding="utf-8")

    res = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res.exit_code == 1
    assert "FAIL tests" in res.output
    assert "- Snapshot" in res.output
    assert "+ Received" in res.output
    assert "1 snapshot failed" in res.output


def test_snapshot_ci_flag_fails_on_missing_and_mismatch(sample_lookml_project: Path):
    # 1. CI fails when snapshot file missing without writing files
    res_missing = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--ci"])
    assert res_missing.exit_code == 1
    assert "missing in CI mode" in res_missing.output
    snap_dir = sample_lookml_project / "__snapshots__"
    assert not snap_dir.exists()

    # 2. Write snapshots normally
    runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])

    # 3. In CI mode, matching snapshots pass
    res_pass = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--ci"])
    assert res_pass.exit_code == 0
    assert "4 snapshots passed" in res_pass.output

    # 4. In CI mode, mismatch fails with exit code 1
    conn_snap = snap_dir / "ecommerce_analytics.connections.snap.json"
    conn_snap.write_text('{"shop": {"connection": "corrupted"}}\n', encoding="utf-8")
    res_fail = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--ci"])
    assert res_fail.exit_code == 1
    assert "FAIL connections" in res_fail.output


def test_snapshot_ci_env_var(sample_lookml_project: Path):
    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)],
        env={"CI": "true"},
    )
    assert res.exit_code == 1
    assert "missing in CI mode" in res.output


def test_snapshot_update_mode(sample_lookml_project: Path):
    runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])

    # Change connection in model
    model_file = sample_lookml_project / "shop.model.lkml"
    content = model_file.read_text(encoding="utf-8")
    model_file.write_text(content.replace('connection: "snowflake_prod"', 'connection: "bigquery_analytics"'), encoding="utf-8")

    # Mismatch first
    res_check = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)])
    assert res_check.exit_code == 1

    # Update in place with -u
    res_update = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "-u"])
    assert res_update.exit_code == 0
    assert "4 snapshots updated" in res_update.output

    # Verify updated content
    conn_snap = sample_lookml_project / "__snapshots__" / "ecommerce_analytics.connections.snap.json"
    data = json.loads(conn_snap.read_text(encoding="utf-8"))
    assert data["shop"]["connection"] == "bigquery_analytics"


def test_snapshot_only_filter(sample_lookml_project: Path):
    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--only", "tests,access"],
    )
    assert res.exit_code == 0
    assert "2 snapshots written" in res.output

    snap_dir = sample_lookml_project / "__snapshots__"
    assert (snap_dir / "ecommerce_analytics.tests.snap.json").exists()
    assert (snap_dir / "ecommerce_analytics.access.snap.json").exists()
    assert not (snap_dir / "ecommerce_analytics.connections.snap.json").exists()
    assert not (snap_dir / "ecommerce_analytics.manifest.snap.json").exists()


def test_snapshot_only_invalid_object(sample_lookml_project: Path):
    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--only", "invalid_obj"],
    )
    assert res.exit_code == 1
    assert "Invalid snapshot object 'invalid_obj'" in res.output


def test_snapshot_model_filter(sample_lookml_project: Path):
    # Add a second model
    (sample_lookml_project / "other.model.lkml").write_text(
        'connection: "postgres_db"\n'
        'include: "*.view.lkml"\n',
        encoding="utf-8",
    )

    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--model", "shop"],
    )
    assert res.exit_code == 0

    conn_snap = sample_lookml_project / "__snapshots__" / "ecommerce_analytics.connections.snap.json"
    data = json.loads(conn_snap.read_text(encoding="utf-8"))
    assert "shop" in data
    assert "other" not in data


def test_snapshot_format_json(sample_lookml_project: Path):
    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "--format", "json"],
    )
    assert res.exit_code == 0
    parsed = json.loads(res.output)
    assert parsed["success"] is True
    assert parsed["project"] == "ecommerce_analytics"
    assert parsed["written"] == 4
    assert parsed["failed"] == 0
    assert "tests" in parsed["snapshots"]


def test_snapshot_output_file(sample_lookml_project: Path, tmp_path: Path):
    out_file = tmp_path / "out_report.txt"
    res = runner.invoke(
        app,
        ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project), "-o", str(out_file)],
    )
    assert res.exit_code == 0
    assert out_file.exists()
    assert "4 snapshots written" in out_file.read_text(encoding="utf-8")


def test_snapshot_missing_directory(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist"
    res = runner.invoke(app, ["parse", "lookml", "snapshot", "--path", str(non_existent)])
    assert res.exit_code == 1
    assert "LookML directory not found" in res.output


def test_snapshot_pure_helpers():
    assert normalize_sql("  SELECT   a,\n  b \n FROM   c  ") == "SELECT a, b FROM c"
    assert normalize_sql(None) is None

    dirty = {
        "name": "foo",
        "line": 10,
        "position": [1, 2, 3, 4],
        "$p": [0, 0, 1, 1],
        "nested": {"line": 20, "val": "ok"},
        "items": [{"line": 30, "id": 1}],
    }
    cleaned = strip_positions(dirty)
    assert cleaned == {
        "name": "foo",
        "nested": {"val": "ok"},
        "items": [{"id": 1}],
    }


def test_run_lookml_snapshot_python_api(sample_lookml_project: Path):
    result, text = run_lookml_snapshot(path=sample_lookml_project)
    assert result.success is True
    assert result.written == 4
    assert "4 snapshots written" in text


def test_snapshot_allow_additions_passes_on_new_tests_asserts_columns_and_measure_labels(
    sample_lookml_project: Path,
):
    # Initialize baseline with an unlabeled measure and a labeled measure
    (sample_lookml_project / "users.view.lkml").write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "    required_access_grants: [marketing, finance]\n"
        "  }\n"
        "  dimension: email {\n"
        "    type: string\n"
        "    sql: ${TABLE}.email ;;\n"
        "  }\n"
        "  measure: count {\n"
        "    type: count\n"
        "  }\n"
        "  measure: total_users {\n"
        "    type: count_distinct\n"
        "    sql: ${id} ;;\n"
        '    label: "Total Users"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    runner.invoke(
        app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)]
    )

    # Now add:
    # 1. A label to the previously unlabeled measure `count`
    # 2. A brand-new measure `active_users` with a label
    # 3. A new column, derived_column, and assert to existing `test_user_id_unique`
    # 4. A brand-new test `test_user_count_positive`
    (sample_lookml_project / "users.view.lkml").write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id {\n"
        "    primary_key: yes\n"
        "    type: number\n"
        "    sql: ${TABLE}.id ;;\n"
        "    required_access_grants: [marketing, finance]\n"
        "  }\n"
        "  dimension: email {\n"
        "    type: string\n"
        "    sql: ${TABLE}.email ;;\n"
        "  }\n"
        "  measure: count {\n"
        "    type: count\n"
        '    label: "User Count"\n'
        "  }\n"
        "  measure: total_users {\n"
        "    type: count_distinct\n"
        "    sql: ${id} ;;\n"
        '    label: "Total Users"\n'
        "  }\n"
        "  measure: active_users {\n"
        "    type: count\n"
        '    label: "Active Users"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (sample_lookml_project / "shop.model.lkml").write_text(
        'connection: "snowflake_prod"\n'
        'include: "*.view.lkml"\n'
        "access_grant: pii_access {\n"
        "  user_attribute: can_view_pii\n"
        '  allowed_values: ["yes", "true"]\n'
        "}\n"
        "explore: users {\n"
        "  required_access_grants: [pii_access]\n"
        "}\n"
        "test: test_user_id_unique {\n"
        "  explore_source: users {\n"
        "    column: id { field: users.id }\n"
        "    column: email { field: users.email }\n"
        "    derived_column: id_plus_one { sql: ${id} + 1 ;; }\n"
        "  }\n"
        "  assert: id_not_null {\n"
        "    expression: ${users.id} is not null ;;\n"
        "  }\n"
        "  assert: id_positive {\n"
        "    expression: ${users.id} > 0 ;;\n"
        "  }\n"
        "}\n"
        "test: test_user_count_positive {\n"
        "  explore_source: users {\n"
        "    column: count { field: users.count }\n"
        "  }\n"
        "  assert: count_pos {\n"
        "    expression: ${users.count} >= 0 ;;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    # Strict mode fails because snapshots grew
    strict_res, _ = run_lookml_snapshot(path=sample_lookml_project)
    assert strict_res.success is False
    assert strict_res.requires_review is False
    assert strict_res.material_changes == []

    # Additive mode passes without requiring human review
    add_res = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "snapshot",
            "--path",
            str(sample_lookml_project),
            "--allow-additions",
            "--format",
            "json",
        ],
    )
    assert add_res.exit_code == 0
    payload = json.loads(add_res.output)
    assert payload["success"] is True
    assert payload["requires_review"] is False
    assert payload["material_changes"] == []
    assert payload["passed"] == 4


def test_snapshot_allow_additions_fails_on_material_changes(
    sample_lookml_project: Path,
):
    # Setup baseline with measure label, test assert, test column, and connection
    (sample_lookml_project / "users.view.lkml").write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        '  measure: total_revenue { type: sum sql: ${TABLE}.rev ;; label: "Total Revenue" }\n'
        "}\n",
        encoding="utf-8",
    )
    runner.invoke(
        app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)]
    )

    # 1. Change assert expression -> requires review
    model_file = sample_lookml_project / "shop.model.lkml"
    orig_model = model_file.read_text(encoding="utf-8")
    model_file.write_text(
        orig_model.replace("${users.id} is not null", "${users.id} > 10"),
        encoding="utf-8",
    )
    res1, _ = run_lookml_snapshot(path=sample_lookml_project, allow_additions=True)
    assert res1.success is False
    assert res1.requires_review is True
    assert any("assert.id_not_null.expression" in c for c in res1.material_changes)

    # 2. Remove test column -> requires review
    model_file.write_text(
        orig_model.replace(
            "column: id { field: users.id }", "column: other { field: users.id }"
        ),
        encoding="utf-8",
    )
    res2, _ = run_lookml_snapshot(path=sample_lookml_project, allow_additions=True)
    assert res2.success is False
    assert res2.requires_review is True
    assert any("column.id: removed" in c for c in res2.material_changes)

    # 3. Change connection name -> requires review
    model_file.write_text(
        orig_model.replace(
            'connection: "snowflake_prod"', 'connection: "bigquery_prod"'
        ),
        encoding="utf-8",
    )
    res3, _ = run_lookml_snapshot(path=sample_lookml_project, allow_additions=True)
    assert res3.success is False
    assert res3.requires_review is True
    assert any("connections.shop.connection" in c for c in res3.material_changes)
    model_file.write_text(orig_model, encoding="utf-8")

    # 4. Change measure label -> requires review
    view_file = sample_lookml_project / "users.view.lkml"
    orig_view = view_file.read_text(encoding="utf-8")
    view_file.write_text(
        orig_view.replace('label: "Total Revenue"', 'label: "Gross Revenue"'),
        encoding="utf-8",
    )
    res4, _ = run_lookml_snapshot(path=sample_lookml_project, allow_additions=True)
    assert res4.success is False
    assert res4.requires_review is True
    assert any(
        "access.fields.shop.users.total_revenue.label" in c
        for c in res4.material_changes
    )

    # 5. Remove measure label -> requires review
    view_file.write_text(
        orig_view.replace('label: "Total Revenue"', ""),
        encoding="utf-8",
    )
    res5, _ = run_lookml_snapshot(path=sample_lookml_project, allow_additions=True)
    assert res5.success is False
    assert res5.requires_review is True
    assert any(
        "access.fields.shop.users.total_revenue: removed" in c
        for c in res5.material_changes
    )


def test_snapshot_base_path_comparison_and_update_guard(
    sample_lookml_project: Path, tmp_path: Path
):
    import shutil

    base_dir = tmp_path / "base_lookml"
    shutil.copytree(sample_lookml_project, base_dir)

    # Add a new assert in head project and compare against base_dir (without __snapshots__)
    model_file = sample_lookml_project / "shop.model.lkml"
    orig_model = model_file.read_text(encoding="utf-8")
    model_file.write_text(
        orig_model.replace(
            "  assert: id_not_null {\n    expression: ${users.id} is not null ;;\n  }\n",
            "  assert: id_not_null {\n    expression: ${users.id} is not null ;;\n  }\n"
            "  assert: id_gt_zero {\n    expression: ${users.id} > 0 ;;\n  }\n",
        ),
        encoding="utf-8",
    )

    res_add, _ = run_lookml_snapshot(
        path=sample_lookml_project,
        base_path=base_dir,
        allow_additions=True,
    )
    assert res_add.success is True
    assert res_add.requires_review is False

    # Mutate connection in head project and verify --allow-additions -u refuses to overwrite
    runner.invoke(
        app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)]
    )
    model_file.write_text(
        orig_model.replace('connection: "snowflake_prod"', 'connection: "mutated_db"'),
        encoding="utf-8",
    )
    res_mut, _ = run_lookml_snapshot(
        path=sample_lookml_project,
        update=True,
        allow_additions=True,
    )
    assert res_mut.success is False
    assert res_mut.requires_review is True
    assert res_mut.updated < 4
    conn_snap = (
        sample_lookml_project / "__snapshots__" / "ecommerce_analytics.connections.snap.json"
    )
    assert (
        json.loads(conn_snap.read_text(encoding="utf-8"))["shop"]["connection"]
        == "snowflake_prod"
    )


def test_snapshot_codeowners_resolution_on_material_changes(
    sample_lookml_project: Path,
):
    gh_dir = sample_lookml_project / ".github"
    gh_dir.mkdir(parents=True, exist_ok=True)
    (gh_dir / "CODEOWNERS").write_text(
        "# Project code owners\n"
        "* @default-owner\n"
        "*.model.lkml @model-owner @org/data-eng\n"
        "/users.view.lkml @view-owner\n"
        "__snapshots__/*.snap.json @snap-owner\n",
        encoding="utf-8",
    )
    view_file = sample_lookml_project / "users.view.lkml"
    view_file.write_text(
        "view: users {\n"
        "  sql_table_name: public.users ;;\n"
        "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
        '  measure: total_revenue { type: sum sql: ${TABLE}.rev ;; label: "Total Revenue" }\n'
        "}\n",
        encoding="utf-8",
    )
    runner.invoke(
        app, ["parse", "lookml", "snapshot", "--path", str(sample_lookml_project)]
    )

    # Material change in users.view.lkml -> resolves view-owner and snap-owner
    orig_view = view_file.read_text(encoding="utf-8")
    view_file.write_text(
        orig_view.replace('label: "Total Revenue"', 'label: "Net Revenue"'),
        encoding="utf-8",
    )
    res_view, text_view = run_lookml_snapshot(
        path=sample_lookml_project, allow_additions=True
    )
    assert res_view.success is False
    assert res_view.requires_review is True
    assert "users.view.lkml" in res_view.material_change_files
    assert (
        "__snapshots__/ecommerce_analytics.access.snap.json"
        in res_view.material_change_files
    )
    assert res_view.required_reviewers == ["view-owner", "snap-owner"]
    assert "Required CODEOWNERS: view-owner, snap-owner" in text_view

    # Restore view and make material change in shop.model.lkml -> resolves model-owner, org/data-eng, snap-owner
    view_file.write_text(orig_view, encoding="utf-8")
    model_file = sample_lookml_project / "shop.model.lkml"
    orig_model = model_file.read_text(encoding="utf-8")
    model_file.write_text(
        orig_model.replace(
            'connection: "snowflake_prod"', 'connection: "bigquery_prod"'
        ),
        encoding="utf-8",
    )
    res_model, _ = run_lookml_snapshot(
        path=sample_lookml_project, allow_additions=True
    )
    assert res_model.requires_review is True
    assert "shop.model.lkml" in res_model.material_change_files
    assert res_model.required_reviewers == [
        "model-owner",
        "org/data-eng",
        "snap-owner",
    ]

