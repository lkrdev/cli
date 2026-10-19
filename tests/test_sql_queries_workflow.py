import importlib.util
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "agentic-lookml-workflow" / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


init_mod = _load_module("init_sql_queries", SCRIPTS_DIR / "init_sql_queries.py")
verify_mod = _load_module("verify_sql_lookml_parity", SCRIPTS_DIR / "verify_sql_lookml_parity.py")

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
