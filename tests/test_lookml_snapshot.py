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
    assert (snap_dir / "ecommerce_analytics.tests.snap").exists()
    assert (snap_dir / "ecommerce_analytics.access.snap").exists()
    assert (snap_dir / "ecommerce_analytics.connections.snap").exists()
    assert (snap_dir / "ecommerce_analytics.manifest.snap").exists()

    # Verify content of connections
    conn_data = json.loads((snap_dir / "ecommerce_analytics.connections.snap").read_text(encoding="utf-8"))
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
    conn_snap = snap_dir / "ecommerce_analytics.connections.snap"
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
    conn_snap = sample_lookml_project / "__snapshots__" / "ecommerce_analytics.connections.snap"
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
    assert (snap_dir / "ecommerce_analytics.tests.snap").exists()
    assert (snap_dir / "ecommerce_analytics.access.snap").exists()
    assert not (snap_dir / "ecommerce_analytics.connections.snap").exists()
    assert not (snap_dir / "ecommerce_analytics.manifest.snap").exists()


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

    conn_snap = sample_lookml_project / "__snapshots__" / "ecommerce_analytics.connections.snap"
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
