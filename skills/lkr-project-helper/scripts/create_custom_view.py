# ruff: noqa: F821, BLE001, S110
"""Create a custom SQL derived table LookML view.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/create_custom_view.py \
    --var project_name=<project> \
    --var view_name=<view_name> \
    --var sql_query="SELECT id, user_id, status FROM orders" \
    [--var folder_name="views"]
"""


def main():
    try:
        proj = str(project_name) or "my_new_project"  # ty: ignore[unresolved-reference]
    except NameError:
        proj = "my_new_project"
    try:
        view = str(view_name) or "custom_derived_table"  # ty: ignore[unresolved-reference]
    except NameError:
        view = "custom_derived_table"
    try:
        sql = str(sql_query) or "SELECT 1 as id"  # ty: ignore[unresolved-reference]
    except NameError:
        sql = "SELECT 1 as id"
    try:
        folder = str(folder_name)  # ty: ignore[unresolved-reference]
    except NameError:
        folder = "views"

    path = f"{folder}/{view}.view.lkml" if folder else f"{view}.view.lkml"
    content = f"""view: {view} {{
  derived_table: {{
    sql: {sql} ;;
  }}

  measure: count {{
    type: count
  }}
}}
"""

    existing = {
        (f.get("path") if isinstance(f, dict) else getattr(f, "path", "")): f
        for f in (all_project_files(proj) or [])  # ty: ignore[unresolved-reference]
    }

    if path in existing:
        update_file(  # ty: ignore[unresolved-reference]
            project_id=proj,
            file_content={"path": path, "content": content},
        )
        action = "updated"
    else:
        if folder:
            try:
                create_project_directory(  # ty: ignore[unresolved-reference]
                    project_id=proj, directory_path=folder
                )
            except Exception:
                pass
        create_file(  # ty: ignore[unresolved-reference]
            project_id=proj,
            file_content={"path": path, "content": content},
        )
        action = "created"

    return {
        "action": action,
        "project_id": proj,
        "file_path": path,
    }


main()
