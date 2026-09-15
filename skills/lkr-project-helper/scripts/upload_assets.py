# ruff: noqa: F821
"""Upload non-standard assets (e.g. custom visualization JS/CSS) to a Looker project.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/upload_assets.py \
    --var project_name=<project> \
    --var file_path="custom_viz.js" \
    --var file_content="<content>"
"""


def main():
    proj = globals().get("project_name", "my_new_project")
    target_path = globals().get("file_path", "")
    target_content = globals().get("file_content", "")

    if not target_path:
        return {"error": "Missing file_path parameter."}

    existing = {
        (f.get("path") if isinstance(f, dict) else getattr(f, "path", "")): f
        for f in (all_project_files(proj) or [])  # ty: ignore[unresolved-reference]
    }

    if target_path in existing:
        update_file(  # ty: ignore[unresolved-reference]
            project_id=proj,
            file_content={"path": target_path, "content": target_content},
        )
        action = "updated"
    else:
        create_file(  # ty: ignore[unresolved-reference]
            project_id=proj,
            file_content={"path": target_path, "content": target_content},
        )
        action = "created"

    return {
        "action": action,
        "project_id": proj,
        "file_path": target_path,
    }


main()
