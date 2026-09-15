# ruff: noqa: F821, BLE001, S110, C408, B018, F841
"""
Script designed to run in looker code-mode sandbox (Monty interpreter):
Pass variables via --var arguments:
  --var project=embed-demo-bryan-meep
  --var connection=looker-private-demo
  --var model=thelook
  --var view_name=order_nested_logic (optional)
  --var sql_content="..." (or --var sql_file=...)
"""

try:
    project_id = project  # ty: ignore[unresolved-reference]
except NameError:
    raise ValueError("Missing project variable via --var project=...")


connection_name = None
target_model_name = None
try:
    connection_name = connection  # ty: ignore[unresolved-reference]
except NameError:
    pass

try:
    target_model_name = model_name  # ty: ignore[unresolved-reference]
except NameError:
    try:
        target_model_name = model  # ty: ignore[unresolved-reference]
    except NameError:
        pass


sql_query_args = dict()
if not (connection_name or target_model_name):
    raise ValueError("Missing connection or model variable via --var connection=... (or --var model=...)")
else:
    if target_model_name:
        sql_query_args["model_name"] = target_model_name
    else:
        sql_query_args["connection_name"] = connection_name

try:
    custom_view_name = view_name  # ty: ignore[unresolved-reference]
except NameError:
    custom_view_name = "orders_nested_view"

try:
    sql_text = sql_content  # ty: ignore[unresolved-reference]
except NameError:
    raise ValueError("Missing sql_content variable via --var sql_content=...")

ver_info = versions()  # ty: ignore[unresolved-reference]
base_url_val = ver_info.get("web_server_url") or ver_info.get("api_server_url") or ""

all_conns = all_connections()  # ty: ignore[unresolved-reference]
conn = None
for c in all_conns:
    if isinstance(c, dict) and c.get("name") == connection_name:
        conn = c
        break

if not conn:
    raise ValueError(f"Connection '{connection_name}' not found on Looker instance.")

tmp_db_name = conn.get("tmp_db_name")
if not tmp_db_name:
    raise ValueError(f"Scratch database (tmp_db_name) is not configured for connection '{connection_name}'.")

full_view_name = f"{tmp_db_name}.{custom_view_name}"

create_sql = f"CREATE OR REPLACE VIEW `{full_view_name}` AS\n{sql_text}"

try:
    sql_query = create_sql_query(  # ty: ignore[unresolved-reference]
        body={
            **sql_query_args,
            "sql": create_sql,
        }
    )
    query_slug = sql_query.get("slug")
    run_sql_query(slug=query_slug, result_format="json")  # ty: ignore[unresolved-reference]
except Exception as e:
    raise RuntimeError(f"Error creating view: {e}")

changed_files = []
try:
    res = generate_lookml_with_new_files(  # ty: ignore[unresolved-reference]
        project_id=project_id,
        body={
            "tables": [
                {
                    "schema": tmp_db_name,
                    "table_name": custom_view_name,
                }
            ]
        },
        connection=connection_name,
        model_name=target_model_name,
        folder_name="views",
        file_type_for_explores="none",
    )
    new_files = res.get("new_files")
    if new_files:
        for f in new_files:
            fname = (f.get("path") or f.get("id") or str(f)) if isinstance(f, dict) else str(f)
            changed_files.append(fname)
except Exception as e:
    pass

try:
    drop_sql = f"DROP VIEW IF EXISTS `{full_view_name}`"
    drop_query = create_sql_query(  # ty: ignore[unresolved-reference]
        body={
            **sql_query_args,
            "sql": drop_sql,
        }
    )
    drop_slug = drop_query.get("slug")
    run_sql_query(slug=drop_slug, result_format="json")  # ty: ignore[unresolved-reference]
except Exception as e:
    pass

file_links = []
for f in changed_files:
    clean_fname = str(f).lstrip("/")
    file_links.append(f"{base_url_val.rstrip('/')}/projects/{project_id}/files/{clean_fname}")

file_links if file_links else "No Files Created"
