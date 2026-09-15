# ruff: noqa: F821, BLE001
"""Validate LookML project syntax, commit changes to Git, deploy to production, and reset dev workspace.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/validate_and_commit.py \
    --var project_name=<project> \
    [--var commit_message="Initial LookML setup"] \
    [--var deploy="true"]
"""


def main():
    proj = globals().get("project_name", "my_new_project")
    msg = globals().get("commit_message", "Initial project generation")
    raw_deploy = globals().get("deploy", "false")
    should_deploy = str(raw_deploy).lower() in ("true", "1", "yes")

    validation = validate_project(proj)  # ty: ignore[unresolved-reference]
    errors = (
        validation.get("errors", [])
        if isinstance(validation, dict)
        else getattr(validation, "errors", [])
    )

    result = {
        "project_id": proj,
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
        "committed": False,
        "deployed": False,
        "dev_workspace_reset": False,
    }

    if len(errors) > 0:
        return result

    try:
        commit(project_id=proj, body={"message": msg})  # ty: ignore[unresolved-reference]
        result["committed"] = True
    except Exception as e:
        result["commit_error"] = str(e)

    if should_deploy and result["committed"]:
        try:
            deploy_to_production(proj)  # ty: ignore[unresolved-reference]
            result["deployed"] = True
            # Reset developer workspace to match production so IDE does not enter degraded state
            try:
                reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
            except Exception:
                create_developer_copy(proj)  # ty: ignore[unresolved-reference]
                reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
            result["dev_workspace_reset"] = True
        except Exception as e:
            result["deploy_error"] = str(e)

    return result


main()
