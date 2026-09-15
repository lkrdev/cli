# ruff: noqa: F821
"""Generate LookML views and model files using generate_lookml_with_new_files.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/generate_lookml.py \
    --var project_name=<project> \
    --var model_name=<model> \
    --var connection_name=<conn> \
    --var schema_name=<schema> \
    --var table_names="orders,users,products" \
    [--var folder_name="views"] \
    [--var file_type_for_explores="model"]
"""


def main():
    proj = globals().get("project_name", "my_new_project")
    model = globals().get("model_name", proj)
    conn = globals().get("connection_name", "")
    schema = globals().get("schema_name", "")
    raw_tables = globals().get("table_names", "")
    folder = globals().get("folder_name", "views")
    file_type = globals().get("file_type_for_explores", "model")
    intention = globals().get("user_intention", "")
    questions = globals().get("questions", "")
    instructions = globals().get("user_instructions", "")

    if not conn:
        conns = all_connections()  # ty: ignore[unresolved-reference]
        if conns:
            first_c = conns[0]
            conn = first_c.get("name") if isinstance(first_c, dict) else getattr(first_c, "name", "")
        else:
            return {"error": "No database connection available on this instance."}

    tables_list = []
    if raw_tables:
        for t in raw_tables.split(","):
            t_clean = t.strip()
            if t_clean:
                tables_list.append({
                    "schema": schema,
                    "table_name": t_clean,
                    "base_view": True,
                })

    body = {}
    if tables_list:
        body["tables"] = tables_list

    sem_gen = {}
    if intention:
        sem_gen["user_intention"] = intention
    if questions:
        sem_gen["questions"] = questions
    if instructions:
        sem_gen["user_instructions"] = instructions
    if sem_gen:
        body["semantic_generation_input"] = sem_gen

    if not tables_list and not sem_gen:
        return {"error": "Must specify either table_names (with schema_name) or semantic generation parameters."}

    response = generate_lookml_with_new_files(  # ty: ignore[unresolved-reference]
        project_id=proj,
        body=body,
        connection=conn,
        model_name=model,
        folder_name=folder,
        file_type_for_explores=file_type,
        generate_descriptions=True,
        generate_helper_text=True,
    )

    new_files_list = []
    raw_files = getattr(response, "new_files", None) or (
        response.get("new_files") if isinstance(response, dict) else []
    )
    for f in raw_files:
        if isinstance(f, dict):
            new_files_list.append(f.get("id") or f.get("path") or str(f))
        elif hasattr(f, "id") and f.id:
            new_files_list.append(str(f.id))
        elif hasattr(f, "path") and f.path:
            new_files_list.append(str(f.path))
        else:
            new_files_list.append(str(f))

    return {
        "status": "success",
        "project_id": proj,
        "model_name": model,
        "connection": conn,
        "folder_name": folder,
        "file_type_for_explores": file_type,
        "new_files_count": len(new_files_list),
        "new_files": new_files_list,
    }


main()
