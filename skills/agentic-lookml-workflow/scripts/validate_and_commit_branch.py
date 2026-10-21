# ruff: noqa: F821
"""Validate LookML project, run targeted LookML data tests, and optionally commit to the active Looker branch."""


def main():
    try:
        p_id = str(project_id)  # ty: ignore[unresolved-reference]
    except NameError:
        return None
    try:
        c_msg = str(commit_message)  # ty: ignore[unresolved-reference]
    except NameError:
        c_msg = ""
    try:
        t_names = [x.strip() for x in str(test_names).split(",") if x.strip()] if test_names is not None else []  # ty: ignore[unresolved-reference]
    except NameError:
        t_names = []
    try:
        f_ids = [x.strip() for x in str(file_ids).split(",") if x.strip()] if file_ids is not None else []  # ty: ignore[unresolved-reference]
    except NameError:
        f_ids = []
    try:
        s_tests = str(skip_tests).lower() in ("true", "1", "yes")  # ty: ignore[unresolved-reference]
    except NameError:
        s_tests = False

    val = validate_project(project_id=p_id) or {}  # ty: ignore[unresolved-reference]
    errors = [
        e for e in (val.get("errors") or []) if e.get("severity", "error") in ("error", "fatal", "")
    ]
    if errors:
        return {"passed": False, "committed": False, "errors": errors, "failed_tests": []}

    targets = (
        list(zip(f_ids, t_names))
        if f_ids and len(f_ids) == len(t_names)
        else [(f_ids[0] if len(f_ids) == 1 else None, t) for t in t_names]
        if t_names
        else [(f, None) for f in (f_ids or [None])]
    )

    test_results = (
        []
        if s_tests
        else [
            r
            for f, t in targets
            for r in (run_lookml_test(project_id=p_id, file_id=f, test=t) or [])  # ty: ignore[unresolved-reference]
        ]
    )
    failed_tests = [t for t in test_results if not t.get("success")]
    if failed_tests:
        return {"passed": False, "committed": False, "errors": [], "failed_tests": failed_tests}

    if not c_msg:
        return {"passed": True, "committed": False, "errors": [], "failed_tests": []}

    commit(project_id=p_id, body={"message": c_msg})  # ty: ignore[unresolved-reference]
    try:
        encoded_pid = encode_path_param(p_id)  # ty: ignore[unresolved-reference]
    except NameError:
        encoded_pid = p_id.replace("%", "%25").replace("/", "%2F").replace(" ", "%20")
    try:
        post(path=f"/projects/{encoded_pid}/push_branch", structure=str)  # ty: ignore[unresolved-reference]
    except NameError:
        pass
    branch = git_branch(project_id=p_id) or {}  # ty: ignore[unresolved-reference]
    return {
        "passed": True,
        "committed": True,
        "branch_name": branch.get("name"),
        "commit_sha": branch.get("ref"),
        "errors": [],
        "failed_tests": [],
    }


main()
