# ruff: noqa: F821, BLE001
"""Ensure Looker project, bare Git repo, developer copy, and model configuration exist.

Run with `--dev-mode` flag so session is automatically in development workspace:
  uvx --from "lkr-dev-cli[code-mode]" lkr-dev-cli code-mode sandbox --dev-mode \
    --file=skills/lkr-project-helper/scripts/ensure_project_and_model.py \
    --var project_name="my_new_project" \
    [--var model_name="my_model"] \
    [--var connection_name="looker-private-demo"] \
    [--var skip_model="false"]
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
    model = _g(lambda: model_name, proj)  # ty: ignore[unresolved-reference]
    conn = _g(lambda: connection_name)  # ty: ignore[unresolved-reference]
    should_skip_model = _g(lambda: skip_model, "false").lower() in ("true", "1", "yes")  # ty: ignore[unresolved-reference]

    project_created = False
    try:
        p = project(proj)  # ty: ignore[unresolved-reference]
    except Exception:
        p = create_project(body={"name": proj})  # ty: ignore[unresolved-reference]
        project_created = True

    if not _attr(p, "uses_git"):
        p = update_project(project_id=proj, body={"git_service_name": "bare"})  # ty: ignore[unresolved-reference]

    dev_copy_status = "verified"
    try:
        create_developer_copy(proj)  # ty: ignore[unresolved-reference]
    except Exception as e:
        dev_copy_status = f"notice: {e}"

    out = {
        "project_id": _attr(p, "id") or proj,
        "project_created": project_created,
        "uses_git": bool(_attr(p, "uses_git")),
        "git_remote_url": _attr(p, "git_remote_url"),
        "developer_copy": dev_copy_status,
    }
    if should_skip_model:
        out["status"] = "ready"
        return out

    if not conn or "PLACEHOLDER" in conn:
        conns = all_connections() or []  # ty: ignore[unresolved-reference]
        conn = (_attr(conns[0], "name", "") if conns else "") or ""
        if not conn:
            return {"error": "No database connections found on this Looker instance"}

    existing = {_attr(m, "name"): m for m in (all_lookml_models() or []) if _attr(m, "name")}  # ty: ignore[unresolved-reference]
    if model in existing:
        allowed = [c for c in (_attr(existing[model], "allowed_db_connection_names") or []) if c]
        if conn not in allowed:
            allowed.append(conn)
        res = update_lookml_model(  # ty: ignore[unresolved-reference]
            lookml_model_name=model,
            body={"name": model, "project_name": proj, "allowed_db_connection_names": allowed},
        )
        action = "updated"
    else:
        allowed = [conn]
        res = create_lookml_model(  # ty: ignore[unresolved-reference]
            body={"name": model, "project_name": proj, "allowed_db_connection_names": allowed}
        )
        action = "created"

    out.update({
        "model_action": action,
        "model_name": _attr(res, "name") or model,
        "allowed_connections": allowed,
        "status": "ready_for_push_or_generation",
    })
    return out


main()
