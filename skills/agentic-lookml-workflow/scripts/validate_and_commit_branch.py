# ruff: noqa: F821
"""Validate LookML project and commit changes to the active Looker git branch."""


def main():
    val = validate_project(project_id=project_id)  # ty: ignore[unresolved-reference]
    errors = [
        e
        for e in (val.get("errors") or [])
        if e.get("severity", "error") in ("error", "fatal", "")
    ]
    if errors:
        return {"committed": False, "errors": errors}

    commit(project_id=project_id, body={"message": commit_message})  # ty: ignore[unresolved-reference]
    branch = git_branch(project_id=project_id)  # ty: ignore[unresolved-reference]
    return {
        "committed": True,
        "branch_name": branch.get("name"),
        "commit_sha": branch.get("ref"),
        "errors": [],
    }


main()
