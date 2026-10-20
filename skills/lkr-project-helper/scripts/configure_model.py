# ruff: noqa: F821
"""Create or update a LookML model configuration with allowed database connections.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/configure_model.py \
    --var project_name=<project> --var model_name=<model> --var connection_name=<conn>
"""


def main():
    try:
        proj = (str(project_name).strip() if project_name is not None else "") or "my_new_project"  # ty: ignore[unresolved-reference]
    except NameError:
        proj = "my_new_project"
    try:
        model = (str(model_name).strip() if model_name is not None else "") or proj  # ty: ignore[unresolved-reference]
    except NameError:
        model = proj
    try:
        conn = str(connection_name).strip() if connection_name is not None else ""  # ty: ignore[unresolved-reference]
    except NameError:
        conn = ""

    if not conn or "PLACEHOLDER" in conn:
        conns = all_connections()  # ty: ignore[unresolved-reference]
        if conns:
            first_c = conns[0]
            conn = first_c.get("name") if isinstance(first_c, dict) else getattr(first_c, "name", "")
        else:
            return {"error": "No database connections found on this Looker instance"}

    existing_models = [
        m.get("name") if isinstance(m, dict) else getattr(m, "name", "")
        for m in (all_lookml_models() or [])  # ty: ignore[unresolved-reference]
    ]

    body = {
        "name": model,
        "project_name": proj,
        "allowed_db_connection_names": [conn],
    }

    if model in existing_models:
        res = update_lookml_model(lookml_model_name=model, body=body)  # ty: ignore[unresolved-reference]
        action = "updated"
    else:
        res = create_lookml_model(body=body)  # ty: ignore[unresolved-reference]
        action = "created"

    res_name = res.get("name") if isinstance(res, dict) else getattr(res, "name", str(res))

    return {
        "action": action,
        "model_name": res_name,
        "project_name": proj,
        "allowed_connections": [conn],
    }


main()
