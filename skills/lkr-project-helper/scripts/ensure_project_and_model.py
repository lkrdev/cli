# ruff: noqa: F821, BLE001
"""Ensure Looker project, bare Git repo, developer copy, and model configuration exist.

Run with `--dev-mode` flag so session is automatically in development workspace:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/ensure_project_and_model.py \
    --var project_name="my_new_project" \
    --var model_name="my_model" \
    --var connection_name="looker-private-demo"
"""


def main():
    proj = globals().get("project_name", "my_new_project")
    model = globals().get("model_name", proj)
    conn = globals().get("connection_name", "")

    # 1. Check if project exists or create it
    project_created = False
    try:
        p = project(proj)  # ty: ignore[unresolved-reference]
    except Exception:
        p = create_project(body={"name": proj})  # ty: ignore[unresolved-reference]
        project_created = True

    # 2. Ensure bare Git repository is configured
    git_configured = bool(p.get("uses_git"))
    if not git_configured:
        p = update_project(  # ty: ignore[unresolved-reference]
            project_id=proj,
            body={"git_service_name": "bare"},
        )
        git_configured = bool(p.get("uses_git"))

    # 3. Ensure active developer copy exists via ExtendedLooker40SDK create_developer_copy
    dev_copy_status = "verified"
    try:
        create_developer_copy(proj)  # ty: ignore[unresolved-reference]
    except Exception as e:
        dev_copy_status = f"notice: {e}"

    # 4. Resolve database connection
    if not conn or "PLACEHOLDER" in conn:
        conns = all_connections()  # ty: ignore[unresolved-reference]
        if conns:
            first_c = conns[0]
            conn = (
                first_c.get("name")
                if isinstance(first_c, dict)
                else getattr(first_c, "name", "")
            )
        else:
            return {"error": "No database connections found on this Looker instance"}

    # 5. Check if model configuration exists; create or update it
    existing_models = [
        m.get("name") if isinstance(m, dict) else getattr(m, "name", "")
        for m in (all_lookml_models() or [])  # ty: ignore[unresolved-reference]
    ]

    model_body = {
        "name": model,
        "project_name": proj,
        "allowed_db_connection_names": [conn],
    }

    if model in existing_models:
        model_res = update_lookml_model(  # ty: ignore[unresolved-reference]
            lookml_model_name=model, body=model_body
        )
        model_action = "updated"
    else:
        model_res = create_lookml_model(body=model_body)  # ty: ignore[unresolved-reference]
        model_action = "created"

    model_name_out = (
        model_res.get("name")
        if isinstance(model_res, dict)
        else getattr(model_res, "name", str(model_res))
    )

    return {
        "project_id": p.get("id") if isinstance(p, dict) else getattr(p, "id", proj),
        "project_created": project_created,
        "uses_git": git_configured,
        "git_remote_url": p.get("git_remote_url") if isinstance(p, dict) else None,
        "developer_copy": dev_copy_status,
        "model_action": model_action,
        "model_name": model_name_out,
        "allowed_connections": [conn],
        "status": "ready_for_push_or_generation",
    }


main()
