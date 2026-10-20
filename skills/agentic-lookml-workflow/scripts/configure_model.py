# ruff: noqa: F821
"""Configure LookML model on the Looker instance via create_lookml_model (defaulting model_name to project_id)."""


def main():
    try:
        p_id = str(project_id).strip() if project_id is not None else ""  # ty: ignore[unresolved-reference]
        c_name = str(connection_name).strip() if connection_name is not None else ""  # ty: ignore[unresolved-reference]
    except NameError:
        return None
    if not p_id:
        return None
    try:
        raw_m = str(model_name).strip() if model_name is not None else ""  # ty: ignore[unresolved-reference]
        m_name = (raw_m or p_id).replace("-", "_")
    except NameError:
        m_name = p_id.replace("-", "_")

    existing_models = {m.get("name"): m for m in (all_lookml_models() or []) if isinstance(m, dict)}  # ty: ignore[unresolved-reference]
    existing = existing_models.get(m_name)
    if not existing:
        create_lookml_model(  # ty: ignore[unresolved-reference]
            body={
                "name": m_name,
                "project_name": p_id,
                "allowed_db_connection_names": [c_name] if c_name else [],
            }
        )
        action = "created"
    else:
        allowed = [str(x) for x in (existing.get("allowed_db_connection_names") or [])]
        if c_name and c_name not in allowed:
            allowed.append(c_name)
        update_lookml_model(  # ty: ignore[unresolved-reference]
            lookml_model_name=m_name,
            body={"name": m_name, "project_name": p_id, "allowed_db_connection_names": allowed},
        )
        action = "updated"

    return {
        "action": action,
        "project_id": p_id,
        "model_name": m_name,
        "connection_name": c_name,
    }


main()
