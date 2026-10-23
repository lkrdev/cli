---
name: agentic-lookml
description: >
  Unified LookML engineering, SQL-to-LookML refactoring, and Medallion semantic modeling skill (`agentic-lookml`).
  Combines the 14 SQL-to-LookML pattern playbooks (`lkr parse sql-lookml-compare`, Canonical Looker Query gate,
  Query-layer Table Calculations and Custom Fields with `matches_filter`, and Bronze/Silver/Gold Medallion architecture)
  with the LookML writing reference skills from `looker-open-source/looker-skills` into a single reference set.
  Use when authoring LookML models, views, explores, fields, refinements, Liquid, sets, access grants, or data tests,
  or when refactoring SQL queries into LookML.
---

# Agentic LookML (`agentic-lookml`)

## Overview and goal

When authoring LookML from scratch, migrating analyst SQL queries, auditing existing LookML projects, or expanding semantic models, agents need both a deterministic architectural blueprint and a complete LookML syntax reference in one place.

The `agentic-lookml` skill combines two complementary skill sets into a single unified reference:

- The 14 SQL-to-LookML refactoring pattern playbooks in `references/`, which pair with `lkr parse sql-lookml-compare` to evaluate SQL queries against an existing LookML project graph, separate Query-layer calculations (Quick Start `query:` blocks, Custom Fields, and Table Calculations) from LookML-layer semantics, and route every LookML change into a scalable Bronze, Silver, and Gold Medallion hierarchy.
- The 9 LookML writing reference skills from [looker-open-source/looker-skills](https://github.com/looker-open-source/looker-skills) packaged under [lookml](../lookml/SKILL.md) (`.agents/skills/lookml/sub-skills/*/SKILL.md`), which provide syntax rules and examples for models, views, derived tables, explores, joins, dimensions, dimension groups, measures, filters, parameters, value formats, refinements, Liquid variables, sets, access grants, and LookML data tests.

### Scope boundaries

- **`drill_fields:` is out of scope for now:** Do not author, add, or modify `drill_fields:` (or drill-only `set:` blocks) on views, dimensions, or measures unless explicitly requested by the user, and do not flag missing `drill_fields:` during LookML reviews or audits.

## Unified reference index

### SQL-to-LookML pattern playbooks (`references/`)

Each SQL query analyzed by `lkr parse sql-lookml-compare` can match one or multiple pattern categories at the same time (such as `["pk_fk_joins", "json_columns_and_extract", "window_functions_and_qualify"]`). Consult the matching playbook in `references/` for the AST signals, Medallion layer routing, and complete LookML templates:

| # | Category ID | Pattern playbook | AST trigger summary | Target layer |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `simple_single_table` | [01-simple-single-table.md](references/01-simple-single-table.md) | 1 table, no joins/CTEs/unions/windows, standard columns and single-pass aggregates | `bronze/:table.refinement.lkml` + `bronze/explores/:table.explore.lkml` (until a Silver join is needed) |
| 02 | `conditional_measures_and_bucketing` | [02-conditional-measures-and-bucketing.md](references/02-conditional-measures-and-bucketing.md) | `SUM(CASE WHEN ...)`, `COUNTIF`, row-level `CASE WHEN` buckets, or measure-to-measure ratios | Query Layer (`Custom Field` with `matches_filter` / `Table Calc`), `bronze/:table.refinement.lkml` (single-table DAG), or `silver/:view_a_:view_b_fields.view.lkml` (multi-view DAG, bare-joined) |
| 03 | `pk_fk_joins` | [03-pk-fk-joins.md](references/03-pk-fk-joins.md) | Equality joins (`t1.fk = t2.pk`) between entity and fact tables | `silver/explores/:name.explore.lkml` (`type: left_outer`) + `bronze/:table.refinement.lkml` (PKs) + `silver/:view_a_:view_b_fields.view.lkml` (bare-joined cross-view fields) |
| 04 | `triangle_inequality_joins` | [04-triangle-inequality-joins.md](references/04-triangle-inequality-joins.md) | Join `ON` contains `<, <=, >, >=, BETWEEN` (SCD2, rolling windows, point-in-time `AS OF`) | Strictly `gold/explores/` (`extends: [silver]`, `tags: ["gold"]`) + Gold `AS OF` view or `bronze/calendar_dates.view.lkml` |
| 05 | `dimensional_non_key_joins` | [05-dimensional-non-key-joins.md](references/05-dimensional-non-key-joins.md) | Joins on non-unique attributes (`date = date`, `country = country`) or `FULL OUTER JOIN` across facts | Gold OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` view), Silver `UNION ALL` SDT (overlapping schemas), Silver NDT (sessionization), or `bronze/calendar_dates.view.lkml` |
| 06 | `nested_ctes_and_subqueries` | [06-nested-ctes-and-subqueries.md](references/06-nested-ctes-and-subqueries.md) | Pass-through CTEs or subqueries doing renames, scalar math, row filters, or `PK = FK` joins without grain changes | Flatten into `bronze/:table.refinement.lkml` + `silver/explores/` (0 Derived Tables) |
| 07 | `measure_of_measures_reaggregation` | [07-measure-of-measures-reaggregation.md](references/07-measure-of-measures-reaggregation.md) | Outer query aggregates, tiers, or filters on an inner `GROUP BY` aggregate column | `silver/:entity_facts.view.lkml` (consolidated ephemeral NDT `explore_source:`) or `gold/` if `bind_all_filters: yes` |
| 08 | `window_functions_and_qualify` | [08-window-functions-and-qualify.md](references/08-window-functions-and-qualify.md) | `OVER (PARTITION BY ... ORDER BY ...)` (`ROW_NUMBER`, `RANK`, `LAG`, `LEAD`) or `QUALIFY` | Query Layer (`Table Calc` + Quick Start `query:`), `silver/` NDT (`derived_column:` post-`GROUP BY`), `silver/` SDT (`extends: [base_view]` with `${EXTENDED}` pre-`GROUP BY` or `QUALIFY`), or `gold/` (`bind_all_filters: yes`) |
| 09 | `unions` | [09-unions.md](references/09-unions.md) | `UNION ALL` or `UNION DISTINCT` across tables or CTEs | `silver/:name.view.lkml` (SDT with `${}` on everything, `extends: [base_view]`, `fields: [ALL_FIELDS*, -view.unneeded]`, compound PK) or `gold/` (Long Metrics unpivot) |
| 10 | `unnest_arrays` | [10-unnest-arrays.md](references/10-unnest-arrays.md) | `UNNEST(...)`, `CROSS/LEFT JOIN UNNEST`, or correlated `FROM UNNEST` scalar subqueries | `bronze/:table.refinement.lkml` (`1:1` inline using `${dimension}`) or `bronze/:table__:arr.view.lkml` (`WITH OFFSET` PK) + `bronze/explores/` and `silver/explores/` (`1:M`) |
| 11 | `json_columns_and_extract` | [11-json-columns-and-extract.md](references/11-json-columns-and-extract.md) | `JSON_VALUE`, `JSON_EXTRACT_SCALAR`, `JSON_QUERY_ARRAY`, `LAX_*`, or JSON path access | `bronze/:table.refinement.lkml` (`hidden: yes`, `suggestable: no`) + `bronze/:table__:col.view.lkml` (`SAFE_CAST`) + `bronze/explores/` (bare join `sql: ;;`) + `silver/explores/` |
| 12 | `table_wildcards` | [12-table-wildcards.md](references/12-table-wildcards.md) | `FROM table_*` or `_TABLE_SUFFIX` predicates | `bronze/` (`table_*` view, refinement, base explore with Liquid `_TABLE_SUFFIX` pruning + `always_filter:`) + `silver/explores/` (`extends: [base]`) |
| 13 | `large_tables_and_partitioning` | [13-large-tables-and-partitioning.md](references/13-large-tables-and-partitioning.md) | Partitioned/clustered tables, non-SARGable date wrappers (`DATE(ts)`), `APPROX_COUNT_DISTINCT` | `bronze/` (actual column `dimension_group`, partition min date/clustering descriptions in refinement, `always_filter:` in base explore) + `silver/explores/` (`extends: [base]`) + `gold/explores/` (`aggregate_table`) |
| 14 | `templated_filters_and_parameters` | [14-templated-filters-and-parameters.md](references/14-templated-filters-and-parameters.md) | Runtime filters required inside inner subqueries/cohorts (`{% condition %}`, `{% parameter %}`) | Strictly `gold/` and `gold/explores/` (`tags: ["gold"]`) paired with mandatory `always_filter:` |

For every SQL query—including `simple_single_table` queries without `CASE WHEN`—also apply [measures-and-sql-functions.md](references/measures-and-sql-functions.md) to evaluate outer SQL wrappers (`ROUND`, `COALESCE`, `100.0 *`, `COUNT(col)`), native `type: percentile` / `type: median` and symmetric `STDDEV` / `VARIANCE` intermediate measures, `value_format_name` vs. SQL rounding, and `WHERE` predicates vs. intrinsic measure `filters:`.

### LookML writing reference skills (`looker-open-source/looker-skills`)

When writing or editing specific LookML constructs, consult the installed `looker-open-source/looker-skills` reference files alongside the Medallion placement rules below. Where the upstream syntax guides use generic `/views/` or `/explores/` folder paths in their examples, always apply the Medallion directory conventions (`bronze/`, `silver/`, `gold/`, `.refinement.lkml`, and `silver/:view_a_:view_b_fields.view.lkml`) defined in this skill:

| LookML domain | Primary skill reference | Sub-references | Medallion architectural rule |
| :--- | :--- | :--- | :--- |
| LookML syntax reference hub | [lookml](../lookml/SKILL.md) | `sub-skills/*/SKILL.md` | Index of all `looker-open-source/looker-skills` sub-skills and their descriptions. |
| End-to-end SQL-to-LookML session & PR workflow | [agentic-lookml-workflow](../agentic-lookml-workflow/SKILL.md) | [setup/SKILL.md](../agentic-lookml-workflow/sub-skills/setup/SKILL.md) | Orchestrates repository/package setup (`uv`, `lkr-dev-cli`, `.model.lkml`, `.github/workflows/lookml-pr-checks.yml`), `--dev` authentication (`lkr auth add-access-token`), production reset and timestamped git branch creation (`YYYYMMDD_HHMMSS_mmm_<user_id>`), `./data/:id/` session tracking (`data.json`, `summary.md`, and `./data/:id/lookml`), `sql-lookml-compare`, `lookml push --no-reset`, `validate_project`, `run_lookml_test`, `commit`, and GitHub PR creation with `summary.md` attached. |
| Generating Bronze views from physical database tables | [generate-view-from-table](../generate-view-from-table/SKILL.md) | None | Whenever `lkr parse sql-lookml-compare` shows a physical table in `parsed_query.tables` with no matching entry in `views` (or with non-empty `views[].unmodeled_db_columns`), use `generate-view-from-table` (`lkr tools lookml create --folder bronze`, `generate_lookml_with_new_files`, or MCP `generate_view_from_table`) to autogenerate `bronze/:table.view.lkml` before writing any refinements or downstream LookML. |
| Model files (`.model.lkml`) and datagroups | [lookml-model](../lookml/sub-skills/lookml-model/SKILL.md) | None | Keep `project.model.lkml` clean: define `connection:`, `datagroup:` caching policies, and explicit `include:` statements for `bronze/explores/*`, `silver/explores/*`, and `gold/explores/*`. Define explores in dedicated `.explore.lkml` files rather than inline in the model file. |
| Views (`.view.lkml`) and derived tables | [lookml-view](../lookml/sub-skills/lookml-view/SKILL.md) | [derived_table.md](../lookml/sub-skills/lookml-view/references/derived_table.md) | Never hand-edit autogenerated `bronze/:table.view.lkml` files. Place consolidated entity-grain NDTs (`explore_source:`, ephemeral by default), `${EXTENDED}` window views, and `UNION ALL` SDTs in `silver/`. Place `bind_all_filters: yes` NDTs, Liquid SDTs, `AS OF` SDTs, and OJOF `COALESCE` views in `gold/`. Every SDT must use `${...}` substitution for all tables and fields. |
| Explores (`.explore.lkml`), joins, and aggregate tables | [lookml-explore](../lookml/sub-skills/lookml-explore/SKILL.md) | [joins.md](../lookml/sub-skills/lookml-explore/references/joins.md), [advanced.md](../lookml/sub-skills/lookml-explore/references/advanced.md) | Serve single-table unjoined queries directly from `bronze/explores/:table.explore.lkml` (`explore: :table`, `hidden: no`) until a cross-table join, `silver/*_fields.view.lkml`, or Silver NDT/SDT is needed; then detach Bronze into `bronze/explores/:table_base.explore.lkml` (`hidden: yes`) and promote to `silver/explores/:table.explore.lkml` (`extends: [:table_base]`, `hidden: no`, strict `PK = FK` equality joins, explicit `view_name:`, zero Liquid). Keep `UNNEST`, bare JSON joins, wildcard `_TABLE_SUFFIX` pruning, and partition `always_filter:` in `bronze/explores/`. Isolate inequality joins, OJOF, Liquid, and `aggregate_table:` blocks in `gold/explores/` (`extends: [silver]`, `tags: ["gold"]`). |
| Fields (`dimension`, `dimension_group`, `measure`, `filter`, `parameter`) | [lookml-fields](../lookml/sub-skills/lookml-fields/SKILL.md) | [dimension.md](../lookml/sub-skills/lookml-fields/references/dimension.md), [dimension_group.md](../lookml/sub-skills/lookml-fields/references/dimension_group.md), [measure.md](../lookml/sub-skills/lookml-fields/references/measure.md), [filter_parameter.md](../lookml/sub-skills/lookml-fields/references/filter_parameter.md), [value_format.md](../lookml/sub-skills/lookml-fields/references/value_format.md) | Put single-table dimensions, `type: duration` dimension groups, and single-table measures in `bronze/:table.refinement.lkml`. Put any dimension or measure whose dependency DAG references multiple views into `silver/:view_a_:view_b_fields.view.lkml` and bare-join (`sql: ;;`) into the Explore. Restrict `filter:` and `parameter:` fields with Liquid SQL to `gold/`. |
| Refinements (`+view`, `+explore`) and `include:` layering | [lookml-refinements](../lookml/sub-skills/lookml-refinements/SKILL.md) | None | Create `bronze/:table.refinement.lkml` on-demand only (first line `include: ":table.view.lkml"`). Use `extends:` (not `+` refinement) when creating Gold specialty explores from Silver explores so the Silver explore remains unmodified. |
| Liquid variables (`{% condition %}`, `{% parameter %}`, `_in_query`) | [lookml-liquid](../lookml/sub-skills/lookml-liquid/SKILL.md) | None | Zero runtime filter Liquid (`{% condition %}`, `{% parameter %}`) in Silver Explores. Restrict runtime Liquid SQL to `gold/` views and explores (always paired with `always_filter:`), with the single exception of `_TABLE_SUFFIX` wildcard shard pruning in `bronze/explores/:prefix_base.explore.lkml`. Always use `_in_query` rather than `_is_selected` for table routing or conditional joins so totals do not break. |
| Advanced Liquid DRY patterns (`{{ _table }}`, `{{ field._sql }}`, `(${EXTENDED})`) | [lookml-advanced-liquid](../lookml/sub-skills/lookml-advanced-liquid/SKILL.md) | None | Use static structural Liquid (`extends: [base_view]` + `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` + `{{ field._sql }}`, or `FROM (${EXTENDED}) AS {{ _table }}`) for PDT-safe DRY inheritance in Silver/Gold SDTs (`UNION ALL`, row windows, `QUALIFY`). Never write `GROUP BY` SDTs with `{{ measure._sql }}` (`filters: [...]` emits invalid `${view.field::filter}`); always use NDTs (`explore_source:`) paired with `cancel_grouping_fields:` when needed. For cross-view SDT bare joins, use an `_sdt_*` alias (`join: _sdt_inventory { from: inventory_items sql: ;; relationship: one_to_one fields: [] }`) so the canonical join name stays free. |
| Multi-fact Outer Join On False (`from: none`, `sql_on: FALSE ;;`, `codim_date`) | [lookml-ojof](../lookml/sub-skills/lookml-ojof/SKILL.md) | None | Isolate OJOF multi-fact Explores in `gold/explores/:name.explore.lkml` (`tags: ["gold"]`). Join peer fact tables (and aliased lifecycle milestone facts) to a 0-row base view (`from: none`) via `type: full_outer`, `relationship: one_to_one`, and `sql_on: FALSE ;;`, bind shared entity dimensions via `COALESCE({% if fact._in_query %} ${fact.fk}, {% endif %} NULL)`, and cross-join co-dimension views (`codim_date`) via `sql_table_name: UNNEST([${codim_date.SQL_TABLE_NAME}]) ;;`. |
| Sets (`set:`) and field visibility (`fields:`) | [lookml-sets](../lookml/sub-skills/lookml-sets/SKILL.md) | None | Use `set:` for Explore-level field curation (`fields: [ALL_FIELDS*, -view.unmapped_col]`, especially on `UNION ALL` views that extend a base Bronze view). Authoring or modifying `drill_fields:` is out of scope for now. |
| Access grants (`access_grant:`, `required_access_grants:`) | [lookml-access-grants](../lookml/sub-skills/lookml-access-grants/SKILL.md) | None | Define `access_grant:` blocks in the model file and apply `required_access_grants:` on views, joins, explores, or sensitive dimensions/measures. |
| LookML data tests (`test:`) | [lookml-tests](../lookml/sub-skills/lookml-tests/SKILL.md) | None | Check `queries[].tests` from `lkr parse sql-lookml-compare` before modifying existing fields or joins, add primary key uniqueness and business logic `test:` assertions on terminal/immutable slices, and never assert frozen point-in-time `= <constant>` values on mutable open-state metrics (`is_sold: "no"`). |

## How `lkr parse sql-lookml-compare` drives refactoring

The `lkr parse sql-lookml-compare` command parses both the SQL AST and the LookML project graph, outputting a `QueryLookmlMapping` object with four groups of signals:

- The `raw_sql` and `parsed_query` fields capture tables, CTEs, joins (`on_sql`, `kind`, `side`, normalized `join_type`, `equi_joins`, `non_equi_conditions`), projection columns (`is_agg`, `sql`, `table`, `column`, `except_`, `replace`, `rename`), `where`, `having`, `group_by`, `order_by`, and `limit`.
- The `views` list reports matched LookML views with file locations, matched `fields` (with transitive `${...}` and derived-table dependency chains in `via`), `unmodeled_db_columns`, and `missing_db_columns`.
- The `explores` and `join_analysis` lists identify reachable explores exposing the matched fields, alongside join diagnostics (`status`, `relationship`, `inferred_relationship`, `safety_warnings`, and `precedents`).
- The `tests`, `aggregate_tables`, `explore_queries`, and `usages` lists track existing LookML data tests, aggregate tables, Quick Start queries, and content validator `usages` in the dependency DAG.

## Canonical Looker Query translation gate

Before considering any derived table (NDT or SDT), execute a preliminary check: attempt to translate the incoming SQL query into a Canonical Looker Query based on [How Looker Generates SQL](https://docs.cloud.google.com/looker/docs/how-looker-generates-sql):

```sql
SELECT <dims>, <agg_measures>
FROM <base>
LEFT JOIN <joins>
WHERE <filters>
GROUP BY <dims>
HAVING <measure_filters>
ORDER BY ...
LIMIT ...
```

Looker generates this SQL shape deterministically:

1. The base view sits in the `FROM` clause, and foreign tables join via `join:` declarations (`sql_on:` or `sql:`).
2. Dimensions represent columns and scalar expressions grouped by `GROUP BY` and projected in `SELECT`.
3. Measures represent aggregations (`SUM`, `COUNT`, `AVG`, and filtered measures) in `SELECT`.
4. Dimension filters map to predicates in `WHERE` joined by `AND`.
5. Measure filters map to predicates in `HAVING`.
6. Sorting and paging map to `ORDER BY` (`sorts`) and `LIMIT`.

### The canonical translation test

Check whether a SQL query (even one with multiple CTEs or subqueries) can be expressed in this canonical form without changing grain or requiring non-`PK = FK` joins by combining:

- Table selections from an existing Explore graph,
- Single-table dimension projections and filters in `bronze/:table.refinement.lkml`,
- Single-table measures in `bronze/:table.refinement.lkml` or cross-view dimensions and measures in `silver/:view_a_:view_b_fields.view.lkml` (bare-joined via `sql: ;;`),
- Standard runtime filters (`WHERE`) and post-aggregation Table Calculations or Custom Fields.

When those conditions hold, the query maps directly to an Explore `query:` Quick Start block (for the underlying modeled `dimensions`, `measures`, `filters`, `pivots`, `subtotals`, `limit`, `sorts`, and `timezone`) and a corresponding Looker `WriteQuery` or `run_inline_query` payload (which carries any Table Calculations or Custom Fields in `dynamic_fields`) with zero derived tables. Never place Table Calculations or Custom Fields (`dynamic_fields`, `table_calculations`, or `custom_fields`) inside an `explore: { query: {} }` LookML block, because Looker's `explore: { query: {} }` syntax does not support them:

```lookml
# In silver/explores/orders.explore.lkml
explore: +orders {
  query: net_revenue_by_country {
    description: "Net revenue by country for active users"
    dimensions: [users.country]
    measures: [orders.order_count, orders.total_net_revenue]
    filters: [orders.status: "-Cancelled", users.is_deleted: "no"]
    sorts: [orders.total_net_revenue: desc]
    limit: 500
  }
}
```

Corresponding Looker `WriteQuery` or MCP `run_inline_query` payload (where Table Calculations and Custom Fields live in `dynamic_fields`):

```json
{
  "model": "ecommerce",
  "view": "orders",
  "fields": [
    "users.country",
    "orders.order_count",
    "orders.total_net_revenue"
  ],
  "filters": {
    "orders.status": "-Cancelled",
    "users.is_deleted": "no"
  },
  "sorts": ["orders.total_net_revenue desc"],
  "limit": "500",
  "dynamic_fields": "[{\"table_calculation\":\"pct_of_total\",\"label\":\"% of Total Revenue\",\"expression\":\"${orders.total_net_revenue} / sum(${orders.total_net_revenue})\"}]"
}
```

Only when a query fails this canonical translation test (due to grain-changing reaggregations, dynamic window rankings, unpivot unions, or non-key joins) should the agent escalate to Silver NDTs or Gold specialty explores.

## The Medallion LookML architecture (Bronze, Silver, and Gold)

Every LookML modification prescribed by the agent follows this three-layer directory structure:

```text
├── bronze/
│   ├── order_items.view.lkml                    # Autogenerated 1:1 physical table (DO NOT MODIFY)
│   ├── order_items.refinement.lkml              # Created ONLY on-demand (PKs, single-table measures/dims, hidden/suggestable, descriptions)
│   ├── orders__line_items.view.lkml             # Companion UNNEST or JSON extracted view (:table__:col.view.lkml)
│   ├── calendar_dates.view.lkml                 # Standard calendar spine view for date joins
│   ├── common_helpers.view.lkml                 # Reusable bare-joined helper view: no_group (sql: 1 ;;) for cancel_grouping_fields + current_timestamp for type: duration
│   ├── :schema/                                 # Used ONLY if table name collides across schemas
│   │   ├── users.view.lkml
│   │   └── users.refinement.lkml
│   ├── :dataset_or_database/:schema/            # Used ONLY if schema + table name collide across databases/projects
│   │   ├── events.view.lkml
│   │   └── events.refinement.lkml
│   └── explores/                                # Unjoined single-table explores (:table.explore.lkml, hidden: no) OR detached base explores (:table_base.explore.lkml, hidden: yes) once promoted to Silver
│       └── order_items_base.explore.lkml        # Detached base explore (hidden: yes) extended by silver/explores/order_items.explore.lkml when Silver joins exist
├── silver/
│   ├── inventory_items_order_items_fields.view.lkml # Cross-view DAG dimensions & measures (alphabetical view names + _fields, bare-joined)
│   ├── user_order_facts.view.lkml               # Consolidated entity NDTs (ephemeral by default), ${EXTENDED} window views, UNION ALL SDTs
│   └── explores/                                # Multi-view Explores with PK=FK joins, *_fields, NDTs, or SDTs (extends: [:table_base], hidden: no)
│       └── orders.explore.lkml                  # Strictly PK=FK equality joins (default left_outer) + bare-joined *_fields; ZERO Liquid; Quick Start query: blocks
├── gold/
│   ├── orders_dynamic_rank.view.lkml            # Specialty views: bind_all_filters NDTs, Liquid SDTs, AS OF SDTs, OJOF COALESCE views
│   └── explores/                                # Specialty Explores (extends: [silver_explore], tags: ["gold"])
│       └── orders_subscription_attribution.explore.lkml # Inequality joins, OJOF, Long Metrics, Liquid/bind_all_filters + always_filter, aggregate_table
├── tests/
│   ├── bronze/
│   │   └── order_items_base.test.lkml           # Single-table measures tested at table grain, grouped into 1 query, filtered to immutable data
│   └── silver/
│       └── orders.test.lkml                     # Silver metrics grouped by join path DAG branch, filtered to immutable data
└── project.model.lkml                           # Includes bronze/explores/*, silver/explores/*, gold/explores/*, and tests/**/*.test.lkml
```

### Bronze layer (`bronze/`, raw physical tables and single-table refinements)

The `bronze/:table.view.lkml` file is a 1:1 autogenerated physical table mapping that already includes Looker's autogenerated `measure: count { type: count }` and basic `dimension_group` blocks. Never hand-edit this file, and never generate a second field with identical logic on the same view (for example, never create a second unfiltered `type: count` measure such as `measure: total_line_items_sold { type: count }` on a view that already has `measure: count { type: count }`, or duplicate an existing dimension/measure just to match a SQL `AS <alias>`). Instead, refine the existing `measure: count` in `bronze/:table.refinement.lkml` (adding `label:`, `description:`, and optional standalone-honest `synonyms:` for genuine domain terms or SQL `AS` names; authoring or modifying `drill_fields:` is out of scope for now) and reference `<view>.count` in Explore `query:` blocks, LookML tests, and `run_inline_query`. Reserve `alias: [old_field_name]` strictly for backward-compatible URL/API redirects when renaming an already-committed LookML field—never put `alias:` on newly authored fields or reference aliased names in LookML (`lkr parse lookml-to-api --validate` enforces zero duplicate field logic and zero alias collisions across every explore view). Run `lkr parse sql-lookml-compare` offline first: **only** if a physical table in `parsed_query.tables` does not have a corresponding Bronze view in `views` or has non-empty `views[].unmodeled_db_columns`, invoke the [generate-view-from-table](../generate-view-from-table/SKILL.md) skill (`lkr tools lookml create --folder bronze`, `generate_lookml_with_new_files`, or MCP `generate_view_from_table` / `create_view_from_table`) to autogenerate `bronze/:table.view.lkml`, pull it locally, and re-run `lkr parse sql-lookml-compare`. Keep views flat in `bronze/` by default; move colliding table names to `bronze/:schema/:table.view.lkml`, and if `:schema.:table` also collides across databases or projects, move to `bronze/:dataset_or_database/:schema/:table.view.lkml`.

Bronze can hold dimensions and measures as long as their entire dependency DAG references only that single table. Self-contained single-table measures (`sum`, `average`, `count_distinct`, single-table filtered measures like `filters: [status: "Complete"]`, and single-table ratios like `1.0 * ${total_revenue} / NULLIF(${order_count}, 0)`) live in `bronze/:table.refinement.lkml`.

Place `bronze/:table.refinement.lkml` directly next to its base `.view.lkml`. Never create a refinement file automatically; it should exist on-demand only if non-generator dimension transformations, single-table measures, primary keys or composite PKs, `suggestable: no` flags on high-cardinality string or raw JSON columns (`session_id`, `uri`, `ip_address`, UUIDs, URLs, JSON), `hidden: yes` flags, or descriptions (including partition min-date and clustering column notes) are being added. When created, its first line must be `include: ":table.view.lkml"`. Maintain `bronze/calendar_dates.view.lkml` as the standard calendar spine view in Bronze for date-spine and multi-date alignment joins, and maintain `bronze/common_helpers.view.lkml` as a reusable table-less helper view that can be bare-joined (`join: common_helpers { sql: ;; relationship: one_to_one }`) into any Explore:

```lookml
# File: bronze/common_helpers.view.lkml
view: common_helpers {
  # Pair with cancel_grouping_fields: [common_helpers.no_group] on the Explore.
  # Selecting common_helpers.no_group in a dimension-only query or NDT explore_source
  # cancels Looker's automatic GROUP BY without adding a primary key to the projection.
  dimension: no_group {
    hidden: yes
    type: number
    sql: 1 ;;
  }

  # Reusable CURRENT_TIMESTAMP() helper for type: duration dimensions across views
  # (e.g., sql_start: ${created_raw} ;; sql_end: ${common_helpers.current_timestamp_raw} ;;)
  dimension_group: current_timestamp {
    type: time
    timeframes: [raw, time, date, week, month, quarter, year]
    sql: CURRENT_TIMESTAMP() ;;
  }
}
```

Explores in `bronze/explores/` serve unjoined single-table queries directly (`bronze/explores/:table.explore.lkml` with `explore: :table`, `hidden: no`, `label: "..."`, `view_name: :table`, and `tests/bronze/:table.test.lkml` targeting `explore_source: :table`) until a cross-table `join:`, `silver/*_fields.view.lkml` view, or Silver NDT/SDT is needed. Once a Silver join is required, detach the Bronze explore into `bronze/explores/:table_base.explore.lkml` (`explore: :table_base`, `hidden: yes`, `view_name: :table`, updating `tests/bronze/:table_base.test.lkml` to `explore_source: :table_base`) and create `silver/explores/:table.explore.lkml` (`explore: :table`, `extends: [:table_base]`, `hidden: no`, `label: "..."`, `view_name: :table`), keeping the public `<model>.:table` identifier unchanged. Bronze explores also isolate four physical intra-table structures and guards:

1. `UNNEST` joins for `REPEATED` columns (`explore: table_base { hidden: yes view_name: table join: table__repeated_col { sql: LEFT JOIN UNNEST(${table.repeated_col}) AS table__repeated_col WITH OFFSET AS table__repeated_col_offset ;; relationship: one_to_many } }`) with `WITH OFFSET` composite PKs. Inline `1:1` scalar subqueries in refinements must reference the LookML `${dimension}`, never `${TABLE}.?`.
2. Bare joins (`sql: ;;`) for companion JSON extracted views (`explore: table_base { hidden: yes view_name: table join: table__metadata { relationship: one_to_one sql: ;; } }`) paired with `bronze/:table__:col.view.lkml`.
3. Wildcard table base explores (`explore: events_base { hidden: yes view_name: events ... }`) with `_TABLE_SUFFIX` physical shard pruning (`always_filter:` and `sql_always_where:` using Liquid `date_start`, `date_end`, and `condition` tags). Wildcard table pruning is physical storage management that protects the warehouse from accidental full scans, making its Liquid the only sanctioned exception to the rule against Liquid in Bronze.
4. Datetime-partitioned table base explores (`explore: table_base { hidden: yes view_name: table always_filter: { filters: [table.event_date: "7 days"] } }`) on the actual column `dimension_group` to prevent unconstrained scans and warehouse `require_partition_filter` errors (no redundant `_PARTITIONDATE` pseudo-dimensions when partitioned on an actual column, and no `conditionally_filter:`).

### Silver layer (`silver/`, core semantic layer and cross-view `*_fields` views)

Any dimension or measure that anywhere in its dependency DAG references different views belongs in its own dedicated Silver view named by sorting the referenced view names alphabetically and appending `_fields` (`silver/:view_a_:view_b_fields.view.lkml`), and is bare-joined (`sql: ;;`, `relationship: one_to_one`) into the Explore that joins those views together. For example, if `order_items.gross_margin` is `${order_items.sale_price} - ${inventory_items.cost}` and `order_items.total_gross_margin` sums `${order_items.gross_margin}`, move both `gross_margin` and `total_gross_margin` (`type: sum`, `sql: ${gross_margin} ;;`) to `silver/inventory_items_order_items_fields.view.lkml` and bare-join `inventory_items_order_items_fields` into the Explore that joins `order_items` and `inventory_items`.

Derived views in `silver/:name.view.lkml` cover four additional patterns:

1. Consolidated entity-grain NDTs (`explore_source:`) combine multiple `GROUP BY entity_id` rollups into a single cohesive NDT (such as `silver/user_order_facts.view.lkml`). Silver NDTs are ephemeral by default (no premature `datagroup_trigger:` persistence), `derived_column:` in an NDT runs after `GROUP BY` for post-aggregation entity ranking and windows, and any aggregating (`GROUP BY`) derived table must use an NDT (`explore_source:`, paired with `cancel_grouping_fields:` on the Explore when grouping must be suppressed) rather than a `GROUP BY` SDT with `{{ measure._sql }}`.
2. Pre-`GROUP BY` row-level window views (`extends: [base_view]` with `${EXTENDED}` or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`) compute row-level windows before `GROUP BY` (such as `LAG({{ created_raw._sql }})` between consecutive orders) using `SELECT {{ _table }}.*, ... FROM (${EXTENDED}) AS {{ _table }}` (or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`).
3. Sessionization, windowing, and `QUALIFY` deduplication views group raw events into sessions or deduplicate single-table CDC ingestion logs (`QUALIFY ROW_NUMBER() = 1`).
4. `UNION ALL` SQL Derived Tables (SDTs) combine tables with overlapping schemas or the same table twice using `extends: [base_view]` (or multiple inheritance `extends: [view_a, view_b]`), `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` with `{{ field._sql }}` (PDT-safe), `fields: [ALL_FIELDS*, -view.unneeded]`, and a mandatory compound primary key.

Explores in `silver/explores/:name.explore.lkml` are created **only** when `:name` requires cross-table `PK = FK` joins, bare-joined `silver/*_fields.view.lkml` views, or Silver NDT/SDT views—never create empty joinless pass-through explores in `silver/explores/` (leave unjoined single-table fact or entity explores like `events` or `users` in `bronze/explores/:name.explore.lkml` until a join—such as analyzing a user's order count—prompts detaching `bronze/explores/:name_base.explore.lkml` with `hidden: yes` and creating `silver/explores/:name.explore.lkml` with `extends: [:name_base]`, `hidden: no`, `label: "..."`, `view_name: :name`). Never route a standalone `FROM :entity` query (`FROM users`) onto a fact `LEFT JOIN` explore (`FROM order_items LEFT JOIN users`), which drops 0-activity entities; conversely, when an entity table only appears in a `JOIN` on a fact query, join it into the fact Silver Explore rather than creating a standalone entity explore. Follow strict YAGNI on joins: only join tables referenced in `input.sql` or explicitly called for in `metrics.md`—do not speculatively join extra Bronze views just because foreign keys exist. Every table join in a Silver explore must be a primary-key-to-foreign-key equality relationship (`many_to_one`, `one_to_one`, `one_to_many`), defaulting SQL `INNER JOIN` to `type: left_outer` unless a metric strictly requires inner filtering, plus bare joins (`sql: ;;`, `relationship: one_to_one`) for cross-view `*_fields.view.lkml` views. Never include runtime filter Liquid (`{% condition %}`, `{% parameter %}`), `bind_all_filters: yes`, inequality or time-bounded joins (`BETWEEN`, `>=`), non-key dimension joins, or `FULL OUTER JOIN ON FALSE` in Silver. Always declare `view_name:` explicitly on the Silver explore so Gold explores can extend it. When adding Quick Start `query:` blocks on an Explore, include only modeled `dimensions`, `measures`, `filters`, `pivots`, `subtotals`, `limit`, `sorts`, `timezone`, and `description` (never Table Calculations or Custom Fields, which live in the query payload or dashboard tile).

### Gold layer (`gold/`, specialty and advanced analytical patterns)

Views in `gold/:name.view.lkml` handle dynamic query context and specialty SQL constructs: dynamic `bind_all_filters: yes` NDTs, raw `sql:` Derived Tables (SDTs) using `{% condition %}` or `{% parameter %}`, point-in-time `AS OF` attribution deduplication, coalesced field-only views (`gold/:dims.view.lkml`) for `FULL OUTER JOIN ON FALSE` (OJOF), and Long Metric unpivot views.

Whenever a SQL Derived Table (`derived_table: { sql: ... ;; }`) is written in Silver or Gold, every table and field reference must use LookML substitution or Liquid `_sql` syntax: `${view_name.SQL_TABLE_NAME} AS {{ _table }}` (when extending `view_name`) or `(${EXTENDED}) AS {{ _table }}` (never raw `db.schema.table`) for every table in `FROM`, `JOIN`, or `UNION ALL`, and `{{ field_name._sql }}` (PDT-safe), `${field_name}`, or `${TABLE}.column_name` for every referenced column. Note that two tables in the same `FROM ... JOIN ...` cannot both be aliased `AS {{ _table }}`; only the primary extended table uses `AS {{ _table }}`, while any cross-view SDT join uses an `_sdt_*` aliased bare join on the Explore (`join: _sdt_other { from: other_view sql: ;; relationship: one_to_one fields: [] }`) and `AS {{ _sdt_other._name }}` + `{{ _sdt_other.field._sql }}`. This guarantees Looker's dependency graph, PDT compiler (`forTableName = true`), and `lkr parse sql-lookml-compare` (`via` lineage) track all references cleanly. See [lookml-advanced-liquid](../lookml/sub-skills/lookml-advanced-liquid/SKILL.md) for the full reference.

Explores in `gold/explores/:name.explore.lkml` extend a Silver explore (`extends: [silver_explore]` with explicit `view_name:`) and carry `tags: ["gold"]`. Gold is strictly a folder structure (`gold/` and `gold/explores/`) and a LookML tag (`tags: ["gold"]`), never an explore name suffix (use `explore: orders_subscription_attribution`, never `orders_gold`). Gold explores isolate inequality and SCD Type 2 joins, OJOF (`FULL OUTER JOIN ON FALSE` plus a `COALESCE` view joined via `sql: ;;`), Long Metrics, dynamic `bind_all_filters: yes` or templated filters and parameters (`{% condition %}`, `{% parameter %}`) paired with mandatory `always_filter:` (never `conditionally_filter:`), and `aggregate_table` rollups.

## Standardized agent diagnostic output contract

When the agent analyzes a query via `lkr parse sql-lookml-compare`, it outputs its diagnosis using this structure:

```markdown
### SQL pattern match: [Pattern name]
- Detected SQL signature: [Specific AST elements from `parsed_query`: e.g., `ctes`, `joins`, `columns[].is_agg`, `where`]
- LookML mapping and lineage:
  - Matched views: [view_name](file:///path/to/bronze/view.view.lkml)
  - Matched fields: [field_name](file:///path/to/bronze/view.refinement.lkml) (via: `...`)
  - Unmodeled columns: `[col_a, col_b]`
  - Affected explores and tests: `[explore_a]`, `[test_b]`
- Target layer: `Query Layer (Table Calc / Custom Field)` | `Bronze Refinement` | `Silver (*_fields / NDT / PK-FK Explore)` | `Gold (Specialty Explore / View)`
- Impact: [Why naive translation fails: fanout risk, partition scan, measure sprawl, or duplicate maintenance]
- How to handle (prescribed action):
  - Autonomy tier: `Tier 1 (Auto-Apply)` | `Tier 2 (Batch Confirm)` | `Tier 3 (Architectural Escalation)`
  - Proposed diff: [Exact surgical LookML block or Query/Dashboard custom field config]
```

## Operational summary tracking (`./data/:id/summary.md`)

Throughout every `agentic-lookml` session, maintain a high-level operations log in `./data/:id/summary.md`. Update `summary.md` incrementally as each phase completes or self-heals so reviewers have a clear audit trail attached to the GitHub pull request:

1. Record the physical tables extracted from the input SQL and the `bronze/:table.view.lkml` base views generated or refreshed via `generate-view-from-table`.
2. Document how each input SQL query deconstructs into the Canonical Looker Query form (`FROM` base table, `LEFT JOIN` paths, projected dimensions, aggregated measures, `WHERE` and `HAVING` filters, `ORDER BY`, `LIMIT`), the key modeling decisions made (such as flattening pass-through CTEs, routing cross-view calculations to `silver/*_fields.view.lkml`, or bare-joining `common_helpers`), and, whenever a derived table (NDT or SDT) or Gold explore is required, the exact structural reason why the query could not be reduced any further into a flat Canonical Looker Query (for example, `UNION ALL` across distinct tables, multi-pass grain-changing reaggregation, pre-aggregation row-level windowing/`QUALIFY` filtering, or non-equi join predicates).
3. List the detected pattern categories from the 14 SQL-to-LookML playbooks (for example, single-table with union `["simple_single_table", "unions"]`, or `["pk_fk_joins", "conditional_measures_and_bucketing"]`) and their AST triggers.
4. Log every LookML file authored or modified across Bronze refinements (`bronze/:table.refinement.lkml`), hidden base explores (`bronze/explores/:table_base.explore.lkml`), Silver cross-view fields, NDTs, SDTs, and explores (`silver/`), and Gold specialty views and explores (`gold/`).
5. Record the outcome of the pre-modeling gate and final LookML validator and SQL-to-LookML parity checks. Whenever validation or query parity fails, log `Validation failed:` with the compiler error, missing reference, or row mismatch, followed by `Updating LookML:` describing the fix applied before re-validating.
6. Log the LookML data tests authored in `tests/bronze/:table_base.test.lkml` and `tests/silver/:explore.test.lkml`, the immutable filter slice chosen (such as `created_date = "2026-01-01"` or a primary key fallback), the frozen baseline values from `code-mode`, and the targeted `run_lookml_test` execution result.

Use this structure for `./data/:id/summary.md`:

```markdown
# Agentic LookML operations summary (`<run_id>`)

## Generating base views
- Generated and refreshed `bronze/orders.view.lkml` from `public.orders`
- Generated and refreshed `bronze/archived_orders.view.lkml` from `public.archived_orders`

## Deconstructing query to canonical form
- Query 1 deconstructs CTE and `UNION ALL` branches into canonical base view `orders_all`, grouping by `status` and `created_date` with measures `order_count` and `total_net_revenue`.
- Decisions made: Flattened outer filter CTE into Explore runtime filters; extended `orders` in `silver/orders_all.view.lkml` using `AS {{ _table }}` and `{{ field._sql }}` with a compound primary key (`compound_pk`) so all Bronze dimensions and labels are inherited without duplication.
- Why the query cannot be reduced further to a flat Canonical Looker Query: Looker's canonical `FROM base LEFT JOIN ... GROUP BY ...` query generator operates on a single `FROM` table and cannot natively emit `UNION ALL` across `public.orders` and `public.archived_orders` without a `UNION ALL` SQL Derived Table.

## Query patterns from original query
- Query 1 matched `simple_single_table` and `unions` (single-table aggregation combined with `UNION ALL` across active and archived tables).

## Writing LookML (Bronze, Silver, and Gold)
- Created `bronze/orders.refinement.lkml` (primary key `id`, measure `total_net_revenue`)
- Created `bronze/explores/orders_base.explore.lkml` (`hidden: yes`)
- Created `silver/orders_all.view.lkml` (`UNION ALL` SDT extending `orders` with compound PK)
- Created `silver/explores/orders.explore.lkml` (`extends: [orders_base]`, `hidden: no`, fact-anchored explore with Quick Start `query:` block)

## Pre-test validation and parity gate
- Initialized SQL Runner query (`/sql/<sql_id>`)
- Validation failed: `Unknown field "orders.net_amount" referenced in bronze/orders.refinement.lkml`
- Updating LookML: Replaced `${net_amount}` with `${amount}` in `bronze/orders.refinement.lkml`
- Validation passed: LookML Validator passed with 0 errors and SQL-to-LookML parity matched (`/x/<query_id>`).

## Writing and evaluating tests
- Created `tests/bronze/orders_base.test.lkml` (grouped single-table refinement measures filtered to immutable date `orders.created_date = "2026-01-01"`)
- Created `tests/silver/orders.test.lkml` (Silver `orders_all` SDT metrics at `orders.created_date = "2026-01-01"`)
- Targeted test execution via `run_lookml_test` passed.
```

## Triage between Table Calculations, Custom Fields, and LookML

Before writing LookML, check whether the SQL expression belongs in the LookML semantic model or in the query and dashboard layer. In `sql-lookml-compare`, this applies when all underlying physical columns referenced by the SQL expression are already modeled in `views[].fields` (with no `unmodeled_db_columns` for those columns), and the SQL expression is a filtered aggregation, a `CASE WHEN` bucketing expression, a ratio of two aggregations, or a cross-row calculation. Note that Custom Fields and Table Calculations cannot be placed inside an `explore: { query: {} }` Quick Start block; they belong in the Looker API query payload (`dynamic_fields`), a Saved Look, or a LookML Dashboard tile.

| Calculation type | Keep in Query / Dashboard when... | Promote to LookML (`bronze/*.refinement.lkml` for single-table DAG, `silver/*_fields.view.lkml` for multi-view DAG) when... |
| :--- | :--- | :--- |
| Filtered measure (`SUM(CASE WHEN country = 'US' THEN rev END)`) | Prefer a Custom Measure using [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) or [`matches_filter(${view.field}, \`expr\`)`](https://docs.cloud.google.com/looker/docs/matches-filter) when the slice (including an ad-hoc cross-column `OR` condition) is used infrequently on a single tile. Avoids polluting the view with $N \times M$ country and status measures. | The filtered metric is a canonical, organization-wide KPI reused across many dashboards and explores (such as single-table `net_completed_revenue` in `bronze/:table.refinement.lkml`, or cross-view filtered KPIs in `silver/:view_a_:view_b_fields.view.lkml` bare-joined into the Explore). |
| Row-level bucketing / expression (`CASE WHEN ...`, string/math expressions) | Use a Custom Dimension when the logic is specific to a single ad-hoc report or campaign (such as `CASE WHEN promo_id IN (12, 45) THEN 'Target' ELSE 'Control' END`). | The logic is simple and reusable for other users (standard age tiers, `is_enterprise`, clean status category) or references an unmodeled `${TABLE}.col`; promote single-table dimensions to `bronze/:table.refinement.lkml` and cross-view dimensions (`${order_items.sale_price} - ${inventory_items.cost}`) to `silver/:view_a_:view_b_fields.view.lkml`. |
| Measure-to-measure math and visual offsets (`SUM(a)/SUM(b)`, `% of total`, `LAG`, running total) | Prefer a Table Calculation in the query or dashboard layer (optionally paired with a Quick Start `query:` block on the Silver Explore for the underlying modeled fields) for post-aggregation visual math (`${measure_a} / nullif(${measure_b}, 0)`, `${measure} / sum(${measure})`, `running_total()`, `offset()`). | A ratio is a foundational business metric (such as single-table `average_order_value` in `bronze/:table.refinement.lkml`, or cross-table `revenue_per_user` in `silver/order_items_users_fields.view.lkml`) that users sort by, drill into, or reuse in NDTs. |

## Core pattern rules summary

### Scalability of approach and blast-radius triage

Inspect `views[].fields`, `views[].unmodeled_db_columns`, `views[].missing_db_columns`, `views[].fields[].via`, `join_analysis`, and `queries[].tests`, then route into one of three autonomy tiers:

1. Tier 1 (autonomous auto-apply) applies when the query maps cleanly to existing Bronze and Silver views, `tests` are unaffected, and gaps consist only of missing or out-of-date Bronze views, reusable single-table dimensions, durations, JSON companion extractions, inline `1:1` `UNNEST` dimensions, or core single-table measures (`SUM` or `COUNT`). If a Bronze view does not exist yet in `views` or is missing a physical column in `views[].unmodeled_db_columns`, use the [generate-view-from-table](../generate-view-from-table/SKILL.md) skill (`lkr tools lookml create --folder bronze`, `generate_lookml_with_new_files`, or MCP `generate_view_from_table`) to autogenerate or sync `bronze/:table.view.lkml` (never hand-edit it); for single-table calculated dimensions, durations, or single-table measures, create or append to `bronze/:table.refinement.lkml` (on-demand only).
2. Tier 2 (batch proposal) applies when the query requires adding a new `PK = FK` join or bare-joined `silver/:view_a_:view_b_fields.view.lkml` view to a fact-anchored Silver Explore, creating a Bronze base explore for one of the four physical table exceptions (`UNNEST`, bare JSON join, wildcard `_TABLE_SUFFIX` pruning, or datetime partition `always_filter:`), creating a consolidated Silver NDT, or triaging Custom Measures versus LookML Measures. Present a concise batch table of proposed Bronze and Silver updates.
3. Tier 3 (architectural escalation / plan first) applies when the query requires spinning up a Gold Specialty Explore (`tags: ["gold"]` with `bind_all_filters: yes`, Liquid `{% condition %}`, inequality or time-bound joins, OJOF `FULL OUTER JOIN ON FALSE`, or `aggregate_table`), or editing a dimension with downstream `via` dependents or `tests`. Present the blast radius (`via` lineage plus `tests`) and confirm the Gold design with the user.

### Evaluating measures, SQL functions, and filter semantics

Consult [measures-and-sql-functions.md](references/measures-and-sql-functions.md) for the complete SQL-to-measure evaluation matrix and worked examples:

1. **Strip cosmetic SQL wrappers (`ROUND(<agg>, k)`, `TRUNC`, `CAST`, `COALESCE(<agg>, 0)`, `100.0 *`) & normalize measure names:** Normalize colloquial SQL `AS` aliases (`unique_chaotic_sessions`, `distinct_clicking_humans`) into canonical LookML identifiers (`unique_sessions` / `session_count`, `distinct_users` / `user_count`), preserving persona phrasing in `label:` / `description:`—and never end `count` or `count_distinct` names in `id`, `year`, or `decade`, which suppresses Looker's default thousands-separator commas (skip blanket `value_format_name: decimal_0` unless `.xlsx` `#,##0` styling or a legitimate `*(id|year|decade)` name requires it, applying equally to `count` and `count_distinct`). Treat outer `ROUND(<agg>, k)` in SQL as a presentation formatting signal 99% of the time: model **one** native aggregate measure (`type: sum`, `type: average`, `type: number`) with `value_format_name` (`usd`, `decimal_2`, `percent_2`) or `value_format`—never put `ROUND(${col}, 2)` inside `type: sum` (row-level rounding drift) and never split into a hidden `type: sum` + visible `type: number` `ROUND(${base}, 2)` pair. `pre_gate.py` aligns numeric comparison precision automatically when `input.sql` applies outer `ROUND(..., k)` and orders Looker columns deterministically by `inline_query.fields`.
2. **`COUNT(*)` / `COUNT(pk)` vs. `COUNT(nullable_col)`:** Reuse and refine autogenerated `measure: count` only for `COUNT(*)` or non-null primary keys. SQL `COUNT(nullable_col)` excludes `NULL`s and requires `type: count` with `filters: [nullable_col: "-NULL"]` (or a `type: yesno` dimension when `nullable_col` is a date/timestamp).
3. **`WHERE` predicates vs. intrinsic metric `filters:` ("No Lying Measure Names or Synonyms") & positive `yesno` polarity:** A measure's name, `label:`, `description:`, and `synonyms:` must match what it computes standalone with zero Explore filters—never name, label, or add a `synonyms:` entry on an unfiltered measure after a `WHERE`-filtered SQL alias (`sunk_dusty_shelf_cost` without `filters:`, or `synonyms: ["unsold units"]` on unfiltered `count`, is banned). Add `synonyms: [...]` only for genuine standalone domain terms, acronyms, or honest SQL `AS` names not already covered by `label:` (no thesaurus filler), and use `alias: [old_name]` strictly when renaming an existing LookML field. Whenever a condition checks `NULL` / `NOT NULL` on a date or timestamp (`sold_at IS NULL`), promote **one** positive-polarity `type: yesno` dimension on the `raw` timeframe (`is_sold`: `${sold_raw} IS NOT NULL`, see [02-conditional-measures-and-bucketing.md](references/02-conditional-measures-and-bucketing.md)) and filter via `is_sold: "no"` / `"yes"`. Never create negated or opposite `yesno` twins (`is_unsold`, `is_not_sold`, `is_inactive` alongside `is_sold` / `is_active`), and use judgment before creating `yesno` fields for non-date columns:
   - **Intrinsic filtered KPI:** When `metrics.md` defines a named domain KPI whose meaning inherently depends on the predicate (e.g., *"Unsold Dusty Shelf Inventory Cost"* with `WHERE sold_at IS NULL`), bake `filters: [is_sold: "no"]` directly onto `sunk_dusty_shelf_cost` (`type: sum`, `sql: ${cost} ;;`, `value_format_name: usd`). Follow YAGNI: skip creating unrequested unfiltered (`total_cost`) or opposite (`sold_cost`) measures unless another metric, ratio, or query in the run needs them. If an intrinsic KPI requires `OR` across two columns, define a hidden positive `type: yesno` helper dimension in `bronze/:table.refinement.lkml` and filter via `filters: [is_cond: "yes"]`.
   - **Ad-hoc query slice:** When `WHERE` (or a repeated `CASE WHEN`) is just a report-time slice (`created_at >= '2026-01-01'`, `country = 'US'`), strip it into the Explore Quick Start `query:` / runtime filter **and** name the measures strictly after their unfiltered math (`total_cost`, `total_product_retail_price`, `count`).
   - **Infrequent side-by-side slice:** Keep one-off comparisons (`US Orders` vs. `UK Orders`) in the Query/Dashboard Layer as Custom Measures using [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) or [`matches_filter`](https://docs.cloud.google.com/looker/docs/matches-filter).
4. **Cross-view DAG routing:** Any dimension, filtered measure, or ratio that anywhere in its dependency DAG references multiple joined views belongs in a dedicated alphabetically named Silver view (`silver/inventory_items_order_items_fields.view.lkml`) bare-joined (`sql: ;;`, `relationship: one_to_one`) into the Explore.

### Join paths, primary keys, fanouts, and layer routing

1. Bronze Explores (`bronze/explores/*.explore.lkml`) hold unjoined single-table explores (`explore: :table`, `hidden: no`) until a Silver join is needed—at which point they detach into hidden base explores (`explore: :table_base`, `hidden: yes`)—along with physical intra-table joins only: `UNNEST` joins on `REPEATED` columns (`sql: LEFT JOIN UNNEST(${table.array_col}) AS table__array_col WITH OFFSET AS table__array_col_offset ;;`, `relationship: one_to_many`, paired with a `WITH OFFSET` composite PK in `bronze/:table__:array_col.view.lkml`) and bare joins (`sql: ;;`, `relationship: one_to_one`) for companion JSON views (`bronze/:table__:json_col.view.lkml`). Inline `1:1` array lookups live as scalar dimensions in `bronze/:table.refinement.lkml` referencing LookML `${array_col}`, never `${TABLE}.?`.
2. Silver Explores (`silver/explores/*.explore.lkml`, `extends: [:table_base]`, `hidden: no`) are created **only** when cross-table `PK = FK` equality joins (`sql_on: ${orders.user_id} = ${users.id} ;;`), bare-joined `silver/:view_a_:view_b_fields.view.lkml` views, or Silver NDT/SDT views are required (never create joinless pass-through explores in `silver/explores/`, and never route standalone `FROM :entity` queries onto a fact `LEFT JOIN` explore that drops 0-activity entities). Join strictly tables referenced in `input.sql` or explicitly called for in `metrics.md` (strict YAGNI: never speculatively join unreferenced Bronze views), defaulting SQL `INNER JOIN` to `type: left_outer` (`many_to_one`, `one_to_one`, `one_to_many`). For date alignment, join `bronze/calendar_dates.view.lkml`.
3. Gold Explores (`gold/explores/*.explore.lkml`, `extends: [silver_explore]`, `tags: ["gold"]`) hold all inequality and time-bounded joins (`BETWEEN`, `>=`, `<`, SCD2, point-in-time `AS OF` deduplication SDTs) and OJOF (`FULL OUTER JOIN ON FALSE` plus `COALESCE` view) joins for unrelated fact schemas.
4. Ensure every joined view has a verified primary key (`primary_key: yes` in `bronze/:table.refinement.lkml`), and run the Two-Table Cardinality Audit SQL in [03-pk-fk-joins.md](references/03-pk-fk-joins.md) via `lkr code-mode` whenever a join's target view lacks a verified PK or relationship.

### Nested CTEs, reaggregations, windows, unions, and Liquid isolation

- Walk CTE chains from leaf to root ([06-nested-ctes-and-subqueries.md](references/06-nested-ctes-and-subqueries.md)): flatten pass-through projections, filters, and `PK = FK` joins into Bronze refinements, Silver `*_fields` views, and Silver Explores with zero derived tables; consolidate static entity-grain rollups into ephemeral Silver NDTs ([07-measure-of-measures-reaggregation.md](references/07-measure-of-measures-reaggregation.md)); and isolate filter-dependent CTEs in Gold (`bind_all_filters: yes` or `{% condition %}` paired with `always_filter:`).
- Route window functions and `QUALIFY` ([08-window-functions-and-qualify.md](references/08-window-functions-and-qualify.md)) across query-layer Table Calculations (display-set windows), Silver NDT `derived_column:` (post-`GROUP BY` windows), Silver `extends: [base_view]` with `${EXTENDED}` (pre-`GROUP BY` row-level windows or single-table CDC `QUALIFY`), and Gold `bind_all_filters: yes` NDTs or `AS OF` SDTs.
- Route `UNION ALL` and multi-fact stitching ([09-unions.md](references/09-unions.md), [05-dimensional-non-key-joins.md](references/05-dimensional-non-key-joins.md), [12-table-wildcards.md](references/12-table-wildcards.md)) across Bronze wildcard `_TABLE_SUFFIX` base explores (the sole Liquid exception outside Gold), Silver `UNION ALL` SDTs (`${}` substitution on every table and column, `extends: [base_view]`, mandatory compound PK, and `fields: [ALL_FIELDS*, -view.unmapped_col]`), and Gold OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` view) or Long Metrics explores.
- Enforce partition pruning and Liquid isolation ([13-large-tables-and-partitioning.md](references/13-large-tables-and-partitioning.md), [14-templated-filters-and-parameters.md](references/14-templated-filters-and-parameters.md)): model off actual partition columns (never redundant `_PARTITIONDATE` pseudo-dimensions when partitioned on a real column), document partition min-dates and clustering columns in `bronze/:table.refinement.lkml`, enforce `always_filter:` in `bronze/explores/:table_base.explore.lkml`, and keep `aggregate_table:`, `{% condition %}`, `{% parameter %}`, and `bind_all_filters: yes` strictly in `gold/` paired with `always_filter:`.

## Opinionated LookML testing and evaluation (`tests/`)

LookML tests (`test: [name] { explore_source: ... assert: ... }`) run in the Looker compiler and warehouse via `run_lookml_test` to verify that semantic models, joins, and calculations produce the expected numbers without regressions. Follow these rules whenever adding or refactoring LookML.

### Single-push pre-test verification gate

Author Bronze refinements (`bronze/:table.refinement.lkml`), Bronze explores (`bronze/explores/:table.explore.lkml` with `hidden: no` when single-table unjoined, or detached `bronze/explores/:table_base.explore.lkml` with `hidden: yes`), **and** any required Silver/Gold views and explores (`silver/explores/:table.explore.lkml` with `extends: [:table_base]`, `hidden: no`, `label: "..."`, `view_name: :table` when Silver joins exist) **together before the first push** so `pre_gate.py` runs once against the real target Explore instead of making redundant round-trips:

1. Validate local LookML and inline queries offline (`lkr parse lookml-to-api --validate`, `lkr schema generate`, `lkr schema validate`), then push all authored Bronze, Silver, and Gold LookML files once (`lkr --dev tools lookml push --no-reset --only-changed`).
2. Run [pre_gate.py](../agentic-lookml-workflow/scripts/pre_gate.py) with `--var validate="true"` (and optional `--var test_queries_json="$TEST_QUERIES_JSON"` for any terminal/immutable test slices) against the final target Explore via `lkr --dev code-mode sandbox` to initialize SQL Runner queries (`/sql/:sql_id`), execute `validate_project`, register the Explore query (`/x/:query_id`), confirm SQL-to-LookML parity, and fetch test-slice baseline numbers (`.test_query_results`) in a single sandbox call.
3. Never author LookML data tests on top of a model that fails validation or parity. Once parity passes, author `tests/`, push `.test.lkml`, and run `validate_and_commit_branch.py` without re-running `pre_gate.py` unless LookML view/explore logic changed.

### Bronze refinement testing rule (`tests/bronze/`, single-table measures)

Test single-table measures **only** in `tests/bronze/` (never duplicate single-table measure assertions in `tests/silver/`):
- Test all self-contained single-table measures (`type: sum`, `type: count`, `type: average`, filtered single-table KPIs, single-table ratios) defined or refined in `bronze/:table.refinement.lkml`, grouped into a single `explore_source:` test block with multiple `column:` and `assert:` statements.
- While `:table` is single-table unjoined (`bronze/explores/:table.explore.lkml`, `hidden: no`), test directly against `explore_source: :table` in `tests/bronze/:table.test.lkml`. Once `:table` is detached for a Silver join, keep `bronze/explores/:table_base.explore.lkml` (`hidden: yes`), point `tests/bronze/:table_base.test.lkml` at `explore_source: :table_base`, and have `silver/explores/:table.explore.lkml` extend `:table_base` with `hidden: no` and `label:`:
  ```lookml
  # In bronze/explores/order_items_base.explore.lkml
  include: "../order_items.view.lkml"
  include: "../order_items.refinement.lkml"

  explore: order_items_base {
    label: "Order Items (Base)"
    view_name: order_items
    hidden: yes
  }
  ```
  ```lookml
  # In silver/explores/order_items.explore.lkml
  include: "../../bronze/explores/order_items_base.explore.lkml"

  explore: order_items {
    extends: [order_items_base]
    label: "Order Items"
    view_name: order_items
    hidden: no
  }
  ```
  Every standalone `.explore.lkml` (`bronze/explores/*`, `silver/explores/*`, `gold/explores/*`) and `.test.lkml` (`tests/bronze/*`, `tests/silver/*`) file must explicitly `include:` the `.view.lkml`, `.refinement.lkml`, or `.explore.lkml` files it references.

### State-machine immutability, filtering to immutable data, and rounding in test expressions

Tests that query volatile data (such as `"today"`, `"yesterday"`, unconstrained table scans, or mutable open-state rows) break over time as underlying rows change. Enforce both **historical slice filtering** and **state-machine immutability**:
- **Distinguish terminal/monotonic states from open/mutable states:**
  - **Terminal / monotonic states** (`is_sold: "yes"` anchored on a past `sold_date`, settled/completed orders anchored on `completed_date`, immutable append-only event logs anchored on `created_date`): Once reached, rows cannot transition out of a terminal state, so historical slices can be asserted deterministically with frozen equality constants (`expression: round(${view.measure}, 2) = 125.50 ;;`).
  - **Open / mutable states** (`is_sold: "no"` / `sold_at IS NULL`, open or processing orders, active carts, unpaid invoices, in-transit shipments): Filtering by a historical `created_date` (`2024-01-01`) does **not** freeze an open-state metric—an unsold item from `2024-01-01` can sell tomorrow, flipping `is_sold: "no" -> "yes"` and breaking hardcoded equality assertions on `sunk_dusty_shelf_cost` or `hypothetical_retail_value`.
  - **Rule for open-state metrics:** Do **not** write frozen point-in-time `test:` equality assertions (`= <constant>`) on measures filtered to mutable open states. Rely on PR-time SQL Runner vs. Explore query parity (`pre_gate.py`) for exact numerical verification, and—only if a LookML `test:` is required—assert structural invariants that remain true across state transitions (such as `${inventory_items.sunk_dusty_shelf_cost} >= 0` or `${inventory_items.sunk_dusty_shelf_cost} <= ${inventory_items.total_cost}`).
- **Choose an immutable historical slice for terminal/append-only metrics:** Inspect the view's dimensions for immutable event timestamps (`*_created_*`, `*_event_*`, `*_ordered_*`, `*_inserted_*`, `*_occurred_*`, or the terminal state timestamp like `sold_date` when testing `is_sold: "yes"`) and filter to a fixed historical calendar date (`2024-01-01`), falling back to a specific primary key (`id = 123`) if no immutable date exists.
- **Fetch baselines inside `pre_gate.py` (`test_queries_json`) and round in LookML `assert:`:** Pass `test_queries_json` to `pre_gate.py` so raw unformatted baseline values (`result_format="json"`, without `apply_formatting=True`) return in `.test_query_results` in the same `code-mode sandbox` call. Keep LookML measures unrounded (`type: sum`, `type: average`, `type: number`) and round inside the test assertion expression (`expression: round(${view.measure}, 2) = 125.50 ;;`).

Example Bronze test:
```lookml
# In tests/bronze/order_items_base.test.lkml
include: "../../bronze/explores/order_items_base.explore.lkml"

test: order_items_base_refinement_metrics {
  explore_source: order_items_base {
    column: total_sale_price { field: order_items.total_sale_price }
    column: order_item_count { field: order_items.count }
    filters: {
      field: order_items.created_date
      value: "2026-01-01"
    }
  }
  assert: total_sale_price_matches {
    expression: round(${order_items.total_sale_price}, 2) = 4520.25 ;;
  }
  assert: order_item_count_matches {
    expression: ${order_items.count} = 84 ;;
  }
}
```

### Silver layer testing (`tests/silver/`, joins, `*_fields`, and NDTs only)

Restrict `tests/silver/:explore.test.lkml` strictly to Silver-layer joins, cross-view `silver/:view_a_:view_b_fields.view.lkml` metrics, and Silver NDT/SDT views (`user_order_facts.lifetime_orders`)—**skip `tests/silver/` entirely on single-table explores with no joins, `*_fields`, or NDTs**. Group Silver measures that share a join path branch into one `explore_source` test block:
1. On the `orders -> users` join branch, test `users` measures joined to `orders` alongside `orders_users_fields` metrics (`revenue_per_user`) in one test block.
2. On the `orders -> order_items -> inventory_items` join branch, test `inventory_items` and `inventory_items_order_items_fields` metrics (`total_gross_margin`) in one test block.

Example Silver test (only join branches and `*_fields` / NDTs—single-table `orders` measures live in `tests/bronze/orders_base.test.lkml`):
```lookml
# In tests/silver/orders.test.lkml
include: "../../silver/explores/orders.explore.lkml"

test: orders_users_join_path_metrics {
  explore_source: orders {
    column: user_count { field: users.count }
    column: revenue_per_user { field: orders_users_fields.revenue_per_user }
    filters: {
      field: orders.created_date
      value: "2026-01-01"
    }
  }
  assert: user_count_matches {
    expression: ${users.count} = 38 ;;
  }
  assert: revenue_per_user_matches {
    expression: round(${orders_users_fields.revenue_per_user}, 2) = 101.32 ;;
  }
}
```

### File structure, model inclusion, and targeted test execution

- Partition tests by Medallion layer in `tests/`:
  - `tests/bronze/:table_base.test.lkml`
  - `tests/silver/:explore.test.lkml`
- Include all tests in `project.model.lkml`:
  ```lookml
  include: "tests/**/*.test.lkml"
  ```
- Target every new or additional test with `lkr code-mode` before committing and pushing to the pull request. Looker's `run_lookml_test(project_id, file_id=None, test=None, model=None)` endpoint (inspectable via `lkr code-mode sandbox --code="return lookup('run_lookml_test')"` or `help('lookml_test')`) filters test execution by `file_id`, `test`, and `model`.
- After pushing new or modified `.test.lkml` files to the developer branch (`lkr --dev tools lookml push --no-reset`), target each new or additional test directly via `lkr --dev code-mode sandbox` before committing or opening the pull request:
  ```bash
  lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --code='return run_lookml_test(project_id="my_project", file_id="tests/silver/orders.test.lkml", test="orders_fact_metrics_at_fixed_date")'
  ```
- Pass `--var file_ids="..."` and `--var test_names="..."` when running `validate_and_commit_branch.py` so only the targeted tests are evaluated before committing. Commit is blocked if any targeted test fails.
