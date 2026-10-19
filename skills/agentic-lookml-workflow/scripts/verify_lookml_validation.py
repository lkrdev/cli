# ruff: noqa: F821
"""PR check script: validate LookML project syntax and data tests via the Looker API."""

import json
import sys


def main():
    p_id = str(project_id)  # ty: ignore[unresolved-reference]

    # 1. Project Syntax & Semantic Validation
    val = validate_project(project_id=p_id) or {}  # ty: ignore[unresolved-reference]
    raw_errors = val.get("errors") or []
    errors = [
        e
        for e in raw_errors
        if e.get("severity", "error") in ("error", "fatal", "")
    ]

    # 2. LookML Data Tests Execution
    test_results = run_lookml_test(project_id=p_id) or []  # ty: ignore[unresolved-reference]
    failed_tests = [
        t
        for t in (test_results if isinstance(test_results, list) else [test_results])
        if not (t.get("success") if isinstance(t, dict) else getattr(t, "success", True))
    ]

    passed = (len(errors) == 0) and (len(failed_tests) == 0)
    result = {
        "passed": passed,
        "project_id": p_id,
        "validation_errors": errors,
        "failed_tests": failed_tests,
    }

    print(json.dumps(result, indent=2))
    if not passed:
        sys.exit(1)
    return result


try:
    main()
except NameError:
    pass
