---
name: looker-field-profiler-scratch-search
description: >
  Profile LookML string dimensions across one or more models (offline via `lkr parse lookml-to-api` or
  online via `lookml_model_explore` + `profile_fields`), compile each Explore + field SQL branch via
  `run_inline_query(result_format="sql")`, combine them into a per-model `UNION ALL` Persistent Derived
  Table (`view: _field_value_search_<model>`) with `sql_trigger_value: SELECT CURRENT_DATE ;;` and
  dialect-specific search index DDL (`create_process`), and expose a hidden LookML Explore
  (`explore: _field_value_search_<model> { hidden: yes }`) across 5 SQL dialects (`bigquery`,
  `snowflake`, `postgres`, `databricks`, `duckdb`).
---

# Scratch Schema Value Search (`sub-skills/scratch-search`)

This sub-skill profiles LookML string dimensions per model, generates the exact Explore SQL for each searchable field using `run_inline_query(result_format="sql")`, and writes a complete model-scoped LookML PDT view and hidden Explore (`_field_value_search_<model>`) with `sql_trigger_value: SELECT CURRENT_DATE ;;` and `create_process:` search index DDL—with zero Liquid required.

---

## 1. How It Works

1. **Discover Candidate String Dimensions per Model (Offline or Online)**:
   - Offline (`--path`): Uses `parse_lookml_to_api` to inspect all visible Explores in each model without extra Looker API calls.
   - Online: Uses `sdk.lookml_model` + `sdk.lookml_model_explore`.
2. **Profile & Filter Searchable Subtypes**:
   - Calls `sdk.profile_fields` per Explore (or reuses existing `profile:*` tags on LookML fields) and keeps `enum`, `categorical`, `entity_label`, and `tier` dimensions while hard-excluding PII (`profile:pii`, `profile:email`, `profile:phone`, `profile:json_payload`, `profile:uuid_or_hash`).
   - `entity_label` (`profile:searchable_entity_label`) is **not** capped at 5,000 rows (`--limit-per-field 0` by default).
3. **Compile Each Branch via `run_inline_query(result_format="sql")`**:
   - For each `(explore_name, field_name)` pair in the model, calls `sdk.run_inline_query(result_format="sql")` with `dynamic_fields` (`model_name`, `explore_name`, `field_name`, `subtype`, `field_value`) and `filters={field_name: "-NULL, -EMPTY"}`.
   - Looker compiles the exact `FROM <explore_base_table>` and pruned `LEFT JOIN` chain (plus any CTE derived tables or `sql_always_where` clauses), strips trailing `ORDER BY 1 LIMIT 100000`, and places each query directly into the model's `UNION ALL`.
4. **Embed in Per-Model `view: _field_value_search_<model>` (`create_process`)**:
   - Uses `sql_trigger_value: SELECT CURRENT_DATE ;;` and `create_process:` (`sql_step:`) with `${SQL_TABLE_NAME}` so Looker builds both the `UNION ALL` table and the dialect search index inside the connection's scratch schema automatically without view/explore collisions across models in the same project.

---

## 2. Supported SQL Dialects & Dialect Scripts

| Dialect Script | Dialect Names | `create_process` `sql_step` DDL | Search / Fuzzy Capabilities |
| :--- | :--- | :--- | :--- |
| [`dialects/bigquery.py`](../../scripts/dialects/bigquery.py) | `bigquery_standard_sql`, `bigquery` | `CREATE OR REPLACE TABLE ${SQL_TABLE_NAME} CLUSTER BY explore_name, field_name, subtype AS <union_sql>` + `CREATE SEARCH INDEX IF NOT EXISTS idx_field_value ON ${SQL_TABLE_NAME}(field_value)` | `SEARCH(field_value, q)`, `CONTAINS_SUBSTR`, `EDIT_DISTANCE <= 2` |
| [`dialects/snowflake.py`](../../scripts/dialects/snowflake.py) | `snowflake` | `CREATE OR REPLACE TABLE ${SQL_TABLE_NAME} CLUSTER BY (explore_name, field_name, subtype) AS <union_sql>` + `ALTER TABLE ${SQL_TABLE_NAME} ADD SEARCH OPTIMIZATION ON SUBSTRING(field_value), EQUALITY(explore_name, field_name)` | `CONTAINS`, `JAROWINKLER_SIMILARITY >= 80`, `EDITDISTANCE <= 2` |
| [`dialects/postgres.py`](../../scripts/dialects/postgres.py) | `postgres`, `alloydb`, `cloudsql_postgres`, `redshift` | `CREATE TABLE ${SQL_TABLE_NAME} AS <union_sql>` + `CREATE INDEX IF NOT EXISTS idx_field_value_fts ON ${SQL_TABLE_NAME} USING GIN (to_tsvector('simple', field_value))` | `to_tsvector('simple', field_value) @@ websearch_to_tsquery('simple', q)`, `ts_rank`, `LIKE` |
| [`dialects/databricks.py`](../../scripts/dialects/databricks.py) | `databrickssql`, `sparksql`, `databricks` | `CREATE OR REPLACE TABLE ${SQL_TABLE_NAME} CLUSTER BY (explore_name, field_name) AS <union_sql>` + `OPTIMIZE ${SQL_TABLE_NAME}` | Delta Liquid Clustering + `CONTAINS` + `levenshtein <= 2` |
| [`dialects/duckdb.py`](../../scripts/dialects/duckdb.py) | `duckdb` | `CREATE OR REPLACE TABLE ${SQL_TABLE_NAME} AS <union_sql>` + `PRAGMA create_fts_index('${SQL_TABLE_NAME}', 'field_value', 'field_value', overwrite=1)` | BM25 FTS index + `CONTAINS` + `jaro_winkler_similarity >= 0.80` |

---

## 3. Usage (Single Model or Multiple Models)

```bash
# Generate per-model _field_value_search_<model>.explore.lkml files for two models at once:
uv run python skills/looker-field-profiler/scripts/scratch_search.py \
  --oauth-account dev-argolis \
  --model agentic_thelook,streaming_platform_analytics \
  --write-lookml ./lookml_output_dir

# Or invoke a specific dialect script directly:
uv run python skills/looker-field-profiler/scripts/dialects/bigquery.py \
  --oauth-account dev-argolis \
  --model agentic_thelook \
  --explore order_items \
  --write-lookml ./_field_value_search_agentic_thelook.explore.lkml
```
