# `lkr schema` Notes & Findings from `system__activity::history` (`vdAt9IRgn89vVzHSLxOczt`)

## Answered Questions & Implemented Pipeline Steps

Using `system__activity::history` (starting from query slug `vdAt9IRgn89vVzHSLxOczt`, schema saved in `tmp/system_activity_history.json`), we inspected real completed queries across multiple Looker models and explores and updated `lkr/schema/` accordingly:

1. **Resolving `system__activity::history` `query.id` to `get_query` (`lkr/schema/history.py`)**:
   - In `system__activity::history`, `query.id` is the internal database integer ID (e.g. `314`, `324`, `142769`), whereas Looker API 4.0 `sdk.query(query_id)` (`GET /queries/{query_id}`) requires the string `query.slug` (e.g. `"P2BfdfcRGtgx3QWn48RwnHFSsCPwWPKY"`).
   - `resolve_history_queries` starts from `vdAt9IRgn89vVzHSLxOczt` (or custom `--history-slug`), queries `system__activity::history` for `["query.id", "query.slug", "query.model", "query.view"]` filtered by `--model`, `--explore`, and/or `--query-id`, calls `sdk.query(slug)`, strips read-only `Query` fields via `sanitize_read_query_to_write_query`, and validates each query via `validate_query`.

2. **Real-world `dynamic_fields` Shapes (`lkr/schema/dynamic_fields.py` & `lkr/schema/validator.py`)**:
   - **`TableCalculation`**: Can be expression-based (`expression`) OR shortcut-based (`calculation_type` such as `rank_of_column`, `percent_of_column_sum`, `running_total`, `percent_of_previous` + `args: [<field>]` + `based_on` / `source_field`, with no `expression`). Both forms and Looker UI metadata (`category`, `_kind_hint`, `_type_hint`, `is_disabled`, `__PARAMETER_LINE_NUMS`) are now supported and validated.
   - **`CustomMeasure`**: Often omits `type` when derived from an existing measure (`based_on: "<view.measure>"`, `measure: "<name>"`) and may include `filters` (dict of `<field>: <filter_expr>`) or `filter_expression` (Looker custom filter formula). Both `based_on` and custom measure `filters` are now validated against the explore schema.
   - **`CustomDimension`**: Supports `dimension`, `expression`, `based_on`, `calculation_type` + `args`, and Looker UI hints.
   - **`${view.field}` Formula Reference Validation**: `_validate_expression_field_refs` validates that all `${view.field}` references inside `dynamic_fields[*].expression`, `dynamic_fields[*].filter_expression`, and `body.filter_expression` resolve to non-hidden explore fields or defined `dynamic_fields` `.name`s (ignoring Looker table calculation functions like `row()`, `offset()`, `pivot_index()`, `now()`).

3. **Real-world `sorts` & Dashboard `filters` (`lkr/schema/fields.py` & `lkr/schema/filter_expressions.py`)**:
   - Pivoted column sorts in Looker can omit `asc`/`desc` (`"<field> 0"` as well as `"<field> desc 0"`).
   - `type: tier` dimensions in LookML emit companion sort fields `"<dimension>__sort_"` in `body.sorts` (`users.age_tier__sort_`, `user_order_facts.lifetime_orders_tier__sort_`), which are validated against visible dimensions.
   - Unfiltered dashboard tiles frequently pass `""` (empty string) in `body.filters`.

## TODO Bucket

- [ ] **Capture `case_sensitive` on string filter properties (`x-case-sensitive: bool`)**:
  - **API Limitation**: Looker's REST API (`LookmlModel`, `LookmlModelExplore`, and `LookmlModelExploreField` from `sdk.lookml_model_explore(model, explore)`) does **not** serialize `case_sensitive` at the model, explore, or field level.
  - **Sourcing via LookML Parser**: Parse the underlying `.lkml` files (using `project_name` + `source_file` from the explore/field metadata with a LookML parser library) to resolve the effective boolean using Looker's inheritance cascade:
    `field.case_sensitive ?? explore.case_sensitive ?? model.case_sensitive ?? True`
  - **Schema Representation (Option B)**: In `build_filter_property_schema` (`lkr/schema/filter_expressions.py`), annotate string filter properties in `body.filters.properties.<field>` with:
    - `"x-case-sensitive": bool` (machine-readable JSON Schema extension tag)
    - Appended `[case_sensitive: true|false]` in `description` (for LLM/agent visibility).

- [ ] **Strongly type `body.vis_config`**:
  - Replace the untyped Swagger passthrough (`"additionalProperties": {"type": "any", "format": "any"}`) with strongly-typed schemas discriminated by `vis_config.type` (e.g., `looker_grid`, `looker_column`, `looker_bar`, `looker_line`, `looker_area`, `looker_pie`, `single_value`, maps, etc.).
