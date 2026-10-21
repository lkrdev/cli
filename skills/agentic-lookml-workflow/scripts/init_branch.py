# ruff: noqa: F821, BLE001
"""Reset developer workspace to production and create a timestamped Looker git branch."""


def main():
    user = me()  # ty: ignore[unresolved-reference]
    run_id = f"{ts_utc}_{user['id']}"  # ty: ignore[unresolved-reference]
    proj = project(project_id=project_id) or {}  # ty: ignore[unresolved-reference]

    try:
        reset_project_to_production(project_id=project_id)  # ty: ignore[unresolved-reference]
    except Exception:
        create_developer_copy(project_id=project_id)  # ty: ignore[unresolved-reference]
        reset_project_to_production(project_id=project_id)  # ty: ignore[unresolved-reference]

    branches = all_git_branches(project_id=project_id) or []  # ty: ignore[unresolved-reference]
    prod_branch = next(
        (
            b
            for b in branches
            if (
                b.get("is_production")
                if isinstance(b, dict)
                else getattr(b, "is_production", False)
            )
        ),
        None,
    )

    target_ref = None
    if prod_branch is not None:
        target_ref = (
            (prod_branch.get("remote_ref") or prod_branch.get("ref"))
            if isinstance(prod_branch, dict)
            else (
                getattr(prod_branch, "remote_ref", None)
                or getattr(prod_branch, "ref", None)
            )
        )

    if not target_ref:
        curr_branch = git_branch(project_id=project_id) or {}  # ty: ignore[unresolved-reference]
        target_ref = (
            curr_branch.get("ref")
            if isinstance(curr_branch, dict)
            else getattr(curr_branch, "ref", None)
        )

    create_git_branch(project_id=project_id, body={"name": run_id})  # ty: ignore[unresolved-reference]
    if target_ref:
        update_git_branch(project_id=project_id, body={"name": run_id, "ref": target_ref})  # ty: ignore[unresolved-reference]

    return {
        "run_id": run_id,
        "user_id": str(user["id"]),
        "project_id": project_id,  # ty: ignore[unresolved-reference]
        "production_branch": proj.get("git_production_branch_name") or "main",
        "production_ref": target_ref,
        "branch_name": run_id,
        "git_remote_url": proj.get("git_remote_url") or "",
    }


main()
