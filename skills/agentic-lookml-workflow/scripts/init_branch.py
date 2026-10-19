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

    prod_ref = (git_branch(project_id=project_id) or {}).get("ref")  # ty: ignore[unresolved-reference]
    create_git_branch(project_id=project_id, body={"name": run_id})  # ty: ignore[unresolved-reference]
    if prod_ref:
        update_git_branch(project_id=project_id, body={"name": run_id, "ref": prod_ref})  # ty: ignore[unresolved-reference]

    return {
        "run_id": run_id,
        "user_id": str(user["id"]),
        "project_id": project_id,  # ty: ignore[unresolved-reference]
        "production_branch": proj.get("git_production_branch_name") or "main",
        "production_ref": prod_ref,
        "branch_name": run_id,
        "git_remote_url": proj.get("git_remote_url") or "",
    }


main()
