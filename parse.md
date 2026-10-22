# LookML & SQL Parsing (`lkr parse`)

`lkr parse` provides offline and SDK-assisted tools for parsing SQL queries, assembling LookML projects (including `extends` and `+` refinements), mapping SQL queries to LookML fields, and comparing LookML models against database schemas.

## Subcommands

| Command | Description |
| :--- | :--- |
| `lkr parse sql` | Parse semicolon-delimited SQL queries (`--sql` or `--file`) into structured AST tables, columns, joins, CTEs, and aggregations. |
| `lkr parse lookml` | Parse a LookML project directory (`--path`), file (`--file`), or inline string (`--lookml`) with model assembly, extensions/refinements, and source file/line positions. |
| `lkr parse sql-lookml-compare` | Map SQL queries (`--sql` / `--sql-file`) to LookML views, dimensions, measures, and explores (`--path` / `--lookml-file` / `--lookml`) with exact source file and line numbers. |
| `lkr parse lookml-to-api` | Generate offline Looker SDK `all_lookml_models` and `lookml_model_explore` responses directly from local LookML files (pass `--exclude-hidden` to skip hidden explores and hidden fields). |
| `lkr parse lookml-database-compare` | Compile physical database tables and columns referenced across LookML explores and bidirectionally validate them against the database schema. |

---

## Database Schema Comparison (`lkr parse lookml-database-compare`)

`lkr parse lookml-database-compare` compiles physical tables and columns referenced by LookML explores (via Looker SDK `run_inline_query(result_format="sql", fields=["ALL_FIELDS*"])` when authenticated, or offline static LookML AST compilation) and compares them against your database catalog.

### How It Complements Looker CI/CD and `spectacles` SQL Validator

Looker's built-in CI/CD SQL Validator and `spectacles sql` test whether existing LookML fields generate runnable SQL by executing queries against the warehouse (`SELECT ... LIMIT 0` or `EXPLAIN`).

`lkr parse lookml-database-compare` is narrower in some ways and broader in others:
1. **Database $\rightarrow$ LookML (`unmodeled_in_lookml`)**: Identifies tables in referenced schemas and columns on modeled tables that exist in the database warehouse but have **not** been added to LookML yet. Neither Looker's SQL Validator nor `spectacles` checks for unmodeled warehouse tables or columns, because unmodeled objects never appear in LookML-generated SQL.
2. **LookML $\rightarrow$ Database (`missing_in_database`)**: Identifies tables and columns referenced in LookML that do not exist in the database catalog without executing per-explore warehouse queries (and works completely offline in CI against an `INFORMATION_SCHEMA` JSON snapshot via `--db-schema-file`).

### Usage Examples

```bash
# List all physical tables and columns referenced across explores (offline)
uvx lkr-dev-cli parse lookml-database-compare --path ./lookml --columns

# Validate tables and columns against an active Looker connection
uvx lkr-dev-cli parse lookml-database-compare --path ./lookml --validate-columns

# Validate offline in CI against a JSON database schema snapshot
uvx lkr-dev-cli parse lookml-database-compare \
  --path ./lookml \
  --validate-columns \
  --db-schema-file ./db_schema.json \
  --format json \
  --output ./compare_result.json
```

### `LookmlDatabaseCompareResult`: `warnings` and `compile_errors` Reference

When `lkr parse lookml-database-compare` runs (or when calling `parse_lookml_database_compare()` in Python), it returns a `LookmlDatabaseCompareResult` containing `warnings`, `tables`, `validation`, and `compile_errors`.

#### `warnings` (`list[str]`)
Non-fatal informational notices about compilation coverage or validation prerequisites:

| Warning Message | When It Is Emitted |
| :--- | :--- |
| `"ALL_FIELDS* SQL compilation does not evaluate filter-only fields or non-default parameter values."` | Always included as a baseline coverage notice: compiling an explore with `fields=["ALL_FIELDS*"]` expands dimensions and measures in the `SELECT` clause, but does not activate `filter:`-only fields or non-default `parameter:` branches (e.g., Liquid `{% if parameter._parameter_value == ... %}` table/column swaps). |
| `"Cannot validate against database: Looker SDK is not authenticated and no --db-schema-file was provided."` | Emitted when `--validate` or `--validate-columns` is requested, but no `--db-schema-file` was supplied and no authenticated Looker SDK session is active to call `sdk.connection_tables()` / `sdk.connection_columns()`. |

#### `compile_errors` (`list[CompileErrorInfo]`)
Per-explore compilation errors (`{"model": str, "explore": str, "error": str}`) captured when an explore cannot be compiled, allowing the remaining explores in the project to still be analyzed:

| Source | Cause & Behavior |
| :--- | :--- |
| **Looker SDK inline query compilation** (`_extract_explore_via_sdk_sql`) | Recorded when `sdk.run_inline_query(result_format="sql", body=WriteQuery(model=..., view=..., fields=["ALL_FIELDS*"]))` raises an API error (for example, an explore with broken LookML references or an undeployed local explore) or when SQLGlot cannot parse the returned SQL string. After recording the error in `compile_errors`, the tool automatically falls back to static LookML AST compilation for that explore. |
| **Static LookML AST compilation** (`_extract_explore_via_ast`) | Recorded if resolving an explore's `extends` / refinement chain, base view (`from` / `view_name`), or `sql_table_name` raises an unexpected error during static analysis. The failing explore is skipped and compilation continues for all other explores. |
