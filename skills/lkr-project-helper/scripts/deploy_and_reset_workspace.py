# ruff: noqa: F821, BLE001
"""Validate LookML, commit, deploy to production, and reset developer workspace in dev mode.

Run with `--dev-mode` flag so session is in development workspace without manual workspace toggling:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/deploy_and_reset_workspace.py \
    --var project_name="my_new_project" \
    [--var commit_message="Sync and deploy LookML changes"] \
    [--var strict="true"]
"""


def main():
    proj = globals().get("project_name", "my_new_project")
    msg = globals().get("commit_message", "Automated LookML sync and deploy")
    raw_strict = globals().get("strict", "false")
    is_strict = str(raw_strict).lower() in ("true", "1", "yes")

    # 1. Validate LookML syntax & semantics
    validation = validate_project(proj)  # ty: ignore[unresolved-reference]
    raw_errors = (
        validation.get("errors", [])
        if isinstance(validation, dict)
        else getattr(validation, "errors", [])
    ) or []

    blocking_errors = []
    for err in raw_errors:
        sev = err.get("severity", "") if isinstance(err, dict) else getattr(err, "severity", "")
        if str(sev).lower() in ("error", "fatal"):
            blocking_errors.append(err)

    result = {
        "project_id": proj,
        "total_validation_issues": len(raw_errors),
        "blocking_error_count": len(blocking_errors),
        "blocking_errors": blocking_errors,
        "committed": False,
        "deployed": False,
        "dev_workspace_reset": False,
    }

    if blocking_errors and is_strict:
        result["status"] = "aborted_due_to_validation_errors"
        return result

    # 2. Commit staged changes to bare repository
    try:
        commit_res = commit(project_id=proj, body={"message": msg})  # ty: ignore[unresolved-reference]
        result["committed"] = True
        result["commit_response"] = commit_res
    except Exception as e:
        result["commit_error"] = str(e)
        result["status"] = "commit_failed"
        return result

    # 3. Deploy to production
    try:
        deploy_res = deploy_to_production(proj)  # ty: ignore[unresolved-reference]
        result["deployed"] = True
        result["deploy_response"] = deploy_res
    except Exception as e:
        result["deploy_error"] = str(e)
        result["status"] = "deploy_failed"
        return result

    # 4. Reset developer workspace to match production (prevents Looker degraded IDE state)
    try:
        try:
            reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
        except Exception:
            create_developer_copy(proj)  # ty: ignore[unresolved-reference]
            reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
        dev_branch = git_branch(proj)  # ty: ignore[unresolved-reference]
        result["dev_workspace_reset"] = True
        result["dev_branch_name"] = (
            dev_branch.get("name") if isinstance(dev_branch, dict) else getattr(dev_branch, "name", "")
        )
    except Exception as e:
        result["dev_reset_notice"] = str(e)

    result["status"] = "deployed_and_synchronized"
    return result


main()
