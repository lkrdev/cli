# ruff: noqa: F821, BLE001
"""Initialize a Looker project with a bare Git repository and developer copy.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/init_project.py \
    --var project_name=<project_name>
"""


def main():
    proj = globals().get("project_name", "my_new_project")

    try:
        p = project(proj)  # ty: ignore[unresolved-reference]
    except Exception:
        p = create_project(body={"name": proj})  # ty: ignore[unresolved-reference]

    if not p.get("uses_git"):
        p = update_project(project_id=proj, body={"git_service_name": "bare"})  # ty: ignore[unresolved-reference]

    dev_copy_status = "verified"
    try:
        create_developer_copy(proj)  # ty: ignore[unresolved-reference]
    except Exception as e:
        dev_copy_status = f"notice: {e}"

    return {
        "project_id": p.get("id"),
        "uses_git": p.get("uses_git"),
        "git_remote_url": p.get("git_remote_url"),
        "developer_copy": dev_copy_status,
        "status": "ready",
    }


main()
