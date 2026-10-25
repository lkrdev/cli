# ruff: noqa: F821, BLE001
"""Validate LookML, commit, optionally deploy to production, and reset developer workspace in dev mode.

Run with `--dev-mode` flag so session is in development workspace without manual workspace toggling:
  uvx --from "lkr-dev-cli[code-mode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/deploy_and_reset_workspace.py \
    --var project_name="my_new_project" \
    [--var commit_message="Sync and deploy LookML changes"] \
    [--var strict="true"] \
    [--var deploy="true"]
"""


def _g(fn, default=""):
    try:
        v = fn()
        return (str(v).strip() or default) if v is not None else default
    except NameError:
        return default


def _attr(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def main():
    proj = _g(lambda: project_name, "my_new_project")  # ty: ignore[unresolved-reference]
    msg = _g(lambda: commit_message, "Automated LookML sync and deploy")  # ty: ignore[unresolved-reference]
    is_strict = _g(lambda: strict, "false").lower() in ("true", "1", "yes")  # ty: ignore[unresolved-reference]
    should_deploy = _g(lambda: deploy, "true").lower() in ("true", "1", "yes")  # ty: ignore[unresolved-reference]

    raw_errors = _attr(validate_project(proj), "errors") or []  # ty: ignore[unresolved-reference]
    blocking_errors = [
        err for err in raw_errors if str(_attr(err, "severity", "") or "").lower() in ("error", "fatal")
    ]
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

    try:
        result["commit_response"] = commit(project_id=proj, body={"message": msg})  # ty: ignore[unresolved-reference]
        result["committed"] = True
    except Exception as e:
        result["commit_error"] = str(e)
        result["status"] = "commit_failed"
        return result

    if not should_deploy:
        result["status"] = "committed_without_deploy"
        return result

    try:
        result["deploy_response"] = deploy_to_production(proj)  # ty: ignore[unresolved-reference]
        result["deployed"] = True
    except Exception as e:
        result["deploy_error"] = str(e)
        result["status"] = "deploy_failed"
        return result

    try:
        try:
            reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
        except Exception:
            create_developer_copy(proj)  # ty: ignore[unresolved-reference]
            reset_project_to_production(proj)  # ty: ignore[unresolved-reference]
        result["dev_workspace_reset"] = True
        result["dev_branch_name"] = _attr(git_branch(proj), "name", "") or ""  # ty: ignore[unresolved-reference]
    except Exception as e:
        result["dev_reset_notice"] = str(e)

    result["status"] = "deployed_and_synchronized"
    return result


main()
