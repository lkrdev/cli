# ruff: noqa: F821
"""Validate LookML project and commit changes to the active Looker git branch."""


def main():
    val = validate_project(project_id=project_id) or {}  # ty: ignore[unresolved-reference]
    errors = [
        e
        for e in (val.get("errors") or [])
        if e.get("severity", "error") in ("error", "fatal", "")
    ]
    if errors:
        return {"committed": False, "errors": errors, "failed_tests": []}

    # Evaluate LookML data tests before committing
    test_results = run_lookml_test(project_id=project_id) or []  # ty: ignore[unresolved-reference]
    failed_tests = [
        t
        for t in (test_results if isinstance(test_results, list) else [test_results])
        if not (t.get("success") if isinstance(t, dict) else getattr(t, "success", True))
    ]
    if failed_tests:
        return {"committed": False, "errors": [], "failed_tests": failed_tests}

    commit(project_id=project_id, body={"message": commit_message})  # ty: ignore[unresolved-reference]
    branch = git_branch(project_id=project_id) or {}  # ty: ignore[unresolved-reference]
    return {
        "committed": True,
        "branch_name": branch.get("name"),
        "commit_sha": branch.get("ref"),
        "errors": [],
        "failed_tests": [],
    }


main()
