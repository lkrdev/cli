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

    prod_name = proj.get("git_production_branch_name") or "main"
    try:
        prod_branch = find_git_branch(project_id=project_id, branch_name=prod_name) or {}  # ty: ignore[unresolved-reference]
    except Exception:
        prod_branch = {}

    target_ref = (
        prod_branch.get("remote_ref")
        or prod_branch.get("ref")
        or (git_branch(project_id=project_id) or {}).get("ref")  # ty: ignore[unresolved-reference]
    )
    body = {"name": run_id, "ref": target_ref} if target_ref else {"name": run_id}
    create_git_branch(project_id=project_id, body=body)  # ty: ignore[unresolved-reference]

    return {
        "run_id": run_id,
        "user_id": str(user["id"]),
        "project_id": project_id,  # ty: ignore[unresolved-reference]
        "production_branch": prod_name,
        "production_ref": target_ref,
        "branch_name": run_id,
        "git_remote_url": proj.get("git_remote_url") or "",
    }


main()
