# ruff: noqa: F821, BLE001
"""Inspect database connections, schemas, and tables on the Looker instance.

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox \
    --file=skills/lkr-project-helper/scripts/inspect_connections.py \
    [--var connection_name=<name>] [--var schema_name=<schema>]
"""


def main():
    target_conn = globals().get("connection_name", "")
    target_schema = globals().get("schema_name", "")

    all_conns = all_connections()  # ty: ignore[unresolved-reference]
    conn_list = [
        {
            "name": c.get("name") if isinstance(c, dict) else getattr(c, "name", ""),
            "dialect_name": c.get("dialect_name") if isinstance(c, dict) else getattr(c, "dialect_name", ""),
            "host": c.get("host") if isinstance(c, dict) else getattr(c, "host", ""),
            "database": c.get("database") if isinstance(c, dict) else getattr(c, "database", ""),
        }
        for c in (all_conns or [])
    ]

    result = {
        "available_connections": conn_list,
        "total_connections": len(conn_list),
    }

    if target_conn:
        # Test connection health
        test_results = []
        try:
            tests = test_connection(target_conn)  # ty: ignore[unresolved-reference]
            for t in (tests or []):
                msg = t.get("message") if isinstance(t, dict) else getattr(t, "message", "")
                status = t.get("status") if isinstance(t, dict) else getattr(t, "status", "")
                test_results.append({"message": msg, "status": status})
        except Exception as e:
            test_results = [{"message": str(e), "status": "error"}]
        result["test_results"] = test_results

        # Retrieve schemas
        try:
            schemas = connection_schemas(target_conn)  # ty: ignore[unresolved-reference]
            schema_names = []
            for s in (schemas or []):
                name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
                if name:
                    schema_names.append(name)
            result["schemas"] = schema_names
        except Exception as e:
            result["schema_error"] = str(e)

        # If schema is specified, list tables
        if target_schema:
            try:
                tables = connection_tables(target_conn, schema_name=target_schema)  # ty: ignore[unresolved-reference]
                table_names = []
                for st in (tables or []):
                    tbl_list = st.get("tables") if isinstance(st, dict) else getattr(st, "tables", [])
                    for t in (tbl_list or []):
                        name = t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t))
                        if name:
                            table_names.append(name)
                result["tables"] = table_names
            except Exception as e:
                result["table_error"] = str(e)

    return result


main()
