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

## Unified reference index

### SQL-to-LookML pattern playbooks (`references/`)

Each SQL query analyzed by `lkr parse sql-lookml-compare` can match one or multiple pattern categories at the same time (such as `["pk_fk_joins", "json_columns_and_extract", "window_functions_and_qualify"]`). Consult the matching playbook in `references/` for the AST signals, Medallion layer routing, and complete LookML templates:

| # | Category ID | Pattern playbook | AST trigger summary | Target layer |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `simple_single_table` | [01-simple-single-table.md](references/01-simple-single-table.md) | 1 table, no joins/CTEs/unions/windows, standard columns and single-pass aggregates | `bronze/:table.refinement.lkml` + `silver/explores/` (fact-anchored) |
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

### LookML writing reference skills (`looker-open-source/looker-skills`)

When writing or editing specific LookML constructs, consult the installed `looker-open-source/looker-skills` reference files alongside the Medallion placement rules below. Where the upstream syntax guides use generic `/views/` or `/explores/` folder paths in their examples, always apply the Medallion directory conventions (`bronze/`, `silver/`, `gold/`, `.refinement.lkml`, and `silver/:view_a_:view_b_fields.view.lkml`) defined in this skill:

| LookML domain | Primary skill reference | Sub-references | Medallion architectural rule |
| :--- | :--- | :--- | :--- |
| LookML syntax reference hub | [lookml](../lookml/SKILL.md) | `sub-skills/*/SKILL.md` | Index of all `looker-open-source/looker-skills` sub-skills and their descriptions. |
| End-to-end SQL-to-LookML session & PR workflow | [agentic-lookml-workflow](../agentic-lookml-workflow/SKILL.md) | [setup/SKILL.md](../agentic-lookml-workflow/sub-skills/setup/SKILL.md) | Orchestrates repository/package setup (`uv`, `lkr-dev-cli`, `.model.lkml`, `.github/workflows/lookml-pr-checks.yml`), `--dev` authentication (`lkr auth add-access-token`), production reset and timestamped git branch creation (`YYYYMMDD_HHMMSS_mmm_<user_id>`), `./data/:id/` session tracking (`data.json`, `summary.md`, and `./data/:id/lookml`), `sql-lookml-compare`, `lookml push --no-reset`, `validate_project`, `run_lookml_test`, `commit`, and GitHub PR creation with `summary.md` attached. |
| Generating Bronze views from physical database tables | [generate-view-from-table](../generate-view-from-table/SKILL.md) | None | Whenever `lkr parse sql-lookml-compare` shows a physical table in `parsed_query.tables` with no matching entry in `views` (or with non-empty `views[].unmodeled_db_columns`), use `generate-view-from-table` (`lkr tools lookml create --folder bronze`, `generate_lookml_with_new_files`, or MCP `generate_view_from_table`) to autogenerate `bronze/:table.view.lkml` before writing any refinements or downstream LookML. |
| Model files (`.model.lkml`) and datagroups | [lookml-model](../lookml/sub-skills/lookml-model/SKILL.md) | None | Keep `project.model.lkml` clean: define `connection:`, `datagroup:` caching policies, and explicit `include:` statements for `bronze/explores/*`, `silver/explores/*`, and `gold/explores/*`. Define explores in dedicated `.explore.lkml` files rather than inline in the model file. |
| Views (`.view.lkml`) and derived tables | [lookml-view](../lookml/sub-skills/lookml-view/SKILL.md) | [derived_table.md](../lookml/sub-skills/lookml-view/references/derived_table.md) | Never hand-edit autogenerated `bronze/:table.view.lkml` files. Place consolidated entity-grain NDTs (`explore_source:`, ephemeral by default), `${EXTENDED}` window views, and `UNION ALL` SDTs in `silver/`. Place `bind_all_filters: yes` NDTs, Liquid SDTs, `AS OF` SDTs, and OJOF `COALESCE` views in `gold/`. Every SDT must use `${...}` substitution for all tables and fields. |
| Explores (`.explore.lkml`), joins, and aggregate tables | [lookml-explore](../lookml/sub-skills/lookml-explore/SKILL.md) | [joins.md](../lookml/sub-skills/lookml-explore/references/joins.md), [advanced.md](../lookml/sub-skills/lookml-explore/references/advanced.md) | Anchor `silver/explores/` on `FROM`-clause fact tables with strict `PK = FK` equality joins (`type: left_outer` default), explicit `view_name:`, and zero Liquid. Keep `UNNEST`, bare JSON joins, wildcard `_TABLE_SUFFIX` pruning, and partition `always_filter:` in `bronze/explores/` (`extension: required`). Isolate inequality joins, OJOF, Liquid, and `aggregate_table:` blocks in `gold/explores/` (`extends: [silver]`, `tags: ["gold"]`). |
| Fields (`dimension`, `dimension_group`, `measure`, `filter`, `parameter`) | [lookml-fields](../lookml/sub-skills/lookml-fields/SKILL.md) | [dimension.md](../lookml/sub-skills/lookml-fields/references/dimension.md), [dimension_group.md](../lookml/sub-skills/lookml-fields/references/dimension_group.md), [measure.md](../lookml/sub-skills/lookml-fields/references/measure.md), [filter_parameter.md](../lookml/sub-skills/lookml-fields/references/filter_parameter.md), [value_format.md](../lookml/sub-skills/lookml-fields/references/value_format.md) | Put single-table dimensions, `type: duration` dimension groups, and single-table measures in `bronze/:table.refinement.lkml`. Put any dimension or measure whose dependency DAG references multiple views into `silver/:view_a_:view_b_fields.view.lkml` and bare-join (`sql: ;;`) into the Explore. Restrict `filter:` and `parameter:` fields with Liquid SQL to `gold/`. |
| Refinements (`+view`, `+explore`) and `include:` layering | [lookml-refinements](../lookml/sub-skills/lookml-refinements/SKILL.md) | None | Create `bronze/:table.refinement.lkml` on-demand only (first line `include: ":table.view.lkml"`). Use `extends:` (not `+` refinement) when creating Gold specialty explores from Silver explores so the Silver explore remains unmodified. |
| Liquid variables (`{% condition %}`, `{% parameter %}`, `_in_query`) | [lookml-liquid](../lookml/sub-skills/lookml-liquid/SKILL.md) | None | Zero runtime filter Liquid (`{% condition %}`, `{% parameter %}`) in Silver Explores. Restrict runtime Liquid SQL to `gold/` views and explores (always paired with `always_filter:`), with the single exception of `_TABLE_SUFFIX` wildcard shard pruning in `bronze/explores/:prefix_base.explore.lkml`. Always use `_in_query` rather than `_is_selected` for table routing or conditional joins so totals do not break. |
| Advanced Liquid DRY patterns (`{{ _table }}`, `{{ field._sql }}`, `(${EXTENDED})`) | [lookml-advanced-liquid](../lookml/sub-skills/lookml-advanced-liquid/SKILL.md) | None | Use static structural Liquid (`extends: [base_view]` + `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` + `{{ field._sql }}`, or `FROM (${EXTENDED}) AS {{ _table }}`) for PDT-safe DRY inheritance in Silver/Gold SDTs (`UNION ALL`, row windows, `QUALIFY`). Never write `GROUP BY` SDTs with `{{ measure._sql }}` (`filters: [...]` emits invalid `${view.field::filter}`); always use NDTs (`explore_source:`) paired with `cancel_grouping_fields:` when needed. For cross-view SDT bare joins, use an `_sdt_*` alias (`join: _sdt_inventory { from: inventory_items sql: ;; relationship: one_to_one fields: [] }`) so the canonical join name stays free. |
| Multi-fact Outer Join On False (`from: none`, `sql_on: FALSE ;;`, `codim_date`) | [lookml-ojof](../lookml/sub-skills/lookml-ojof/SKILL.md) | None | Isolate OJOF multi-fact Explores in `gold/explores/:name.explore.lkml` (`tags: ["gold"]`). Join peer fact tables (and aliased lifecycle milestone facts) to a 0-row base view (`from: none`) via `type: full_outer`, `relationship: one_to_one`, and `sql_on: FALSE ;;`, bind shared entity dimensions via `COALESCE({% if fact._in_query %} ${fact.fk}, {% endif %} NULL)`, and cross-join co-dimension views (`codim_date`) via `sql_table_name: UNNEST([${codim_date.SQL_TABLE_NAME}]) ;;`. |
| Sets (`set:`) and field visibility (`fields:`) | [lookml-sets](../lookml/sub-skills/lookml-sets/SKILL.md) | None | Use `set:` for reusable `drill_fields` and Explore-level field curation (`fields: [ALL_FIELDS*, -view.unmapped_col]`, especially on `UNION ALL` views that extend a base Bronze view). |
| Access grants (`access_grant:`, `required_access_grants:`) | [lookml-access-grants](../lookml/sub-skills/lookml-access-grants/SKILL.md) | None | Define `access_grant:` blocks in the model file and apply `required_access_grants:` on views, joins, explores, or sensitive dimensions/measures. |
| LookML data tests (`test:`) | [lookml-tests](../lookml/sub-skills/lookml-tests/SKILL.md) | None | Check `queries[].tests` from `lkr parse sql-lookml-compare` before modifying existing fields or joins, and add primary key uniqueness and business logic `test:` assertions when introducing complex joins or derived tables. |

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
│   └── explores/                                # Hidden explores for NDT explore_source OR the 4 physical table exceptions
│       └── order_items_base.explore.lkml        # MUST set hidden: yes or extension: required
├── silver/
│   ├── inventory_items_order_items_fields.view.lkml # Cross-view DAG dimensions & measures (alphabetical view names + _fields, bare-joined)
│   ├── user_order_facts.view.lkml               # Consolidated entity NDTs (ephemeral by default), ${EXTENDED} window views, UNION ALL SDTs
│   └── explores/                                # Core fact-anchored Explores (90% of use cases)
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

The `bronze/:table.view.lkml` file is a 1:1 autogenerated physical table mapping that already includes Looker's autogenerated `measure: count { type: count }` and basic `dimension_group` blocks. Never hand-edit this file, and never generate a second field with identical logic on the same view (for example, never create a second unfiltered `type: count` measure such as `measure: total_line_items_sold { type: count }` on a view that already has `measure: count { type: count }`, or duplicate an existing dimension/measure just to match a SQL `AS <alias>`). Instead, refine the existing `measure: count` (adding `label:`, `description:`, or `drill_fields:`) in `bronze/:table.refinement.lkml` and reference `<view>.count` in Explore `query:` blocks, LookML tests, and `run_inline_query` (`lkr parse lookml-to-api --validate` enforces zero duplicate field logic across every explore view). If `lkr parse sql-lookml-compare` shows that a physical table in `parsed_query.tables` does not have a corresponding Bronze view in `views` (or has unmodeled physical database columns in `views[].unmodeled_db_columns`), invoke the [generate-view-from-table](../generate-view-from-table/SKILL.md) skill (`lkr tools lookml create --folder bronze`, `generate_lookml_with_new_files`, or MCP `generate_view_from_table` / `create_view_from_table`) to autogenerate `bronze/:table.view.lkml`, pull it locally, and re-run `lkr parse sql-lookml-compare`. Keep views flat in `bronze/` by default; move colliding table names to `bronze/:schema/:table.view.lkml`, and if `:schema.:table` also collides across databases or projects, move to `bronze/:dataset_or_database/:schema/:table.view.lkml`.

Bronze can hold dimensions and measures as long as their entire dependency DAG references only that single table. Self-contained single-table measures (`sum`, `average`, `count_distinct`, single-table filtered measures like `filters: [status: "Complete"]`, and single-table ratios like `1.0 * ${total_revenue} / NULLIF(${order_count}, 0)`) live in `bronze/:table.refinement.lkml`.

Place `bronze/:table.refinement.lkml` directly next to its base `.view.lkml`. Never create a refinement file automatically; it should exist on-demand only if non-generator dimension transformations, single-table measures, primary keys or composite PKs, `hidden: yes` and `suggestable: no` flags (for raw JSON columns), or descriptions (including partition min-date and clustering column notes) are being added. When created, its first line must be `include: ":table.view.lkml"`. Maintain `bronze/calendar_dates.view.lkml` as the standard calendar spine view in Bronze for date-spine and multi-date alignment joins, and maintain `bronze/common_helpers.view.lkml` as a reusable table-less helper view that can be bare-joined (`join: common_helpers { sql: ;; relationship: one_to_one }`) into any Explore:

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

Explores in `bronze/explores/:name.explore.lkml` must declare `hidden: yes` (or `extension: required` when extended by Silver explores) and only exist if actively referenced by an `explore_source:` in a Silver or Gold Native Derived Table, with four physical table exceptions:

1. `UNNEST` joins for `REPEATED` columns (`explore: table_base { extension: required view_name: table join: table__repeated_col { sql: LEFT JOIN UNNEST(${table.repeated_col}) AS table__repeated_col WITH OFFSET AS table__repeated_col_offset ;; relationship: one_to_many } }`) with `WITH OFFSET` composite PKs. Inline `1:1` scalar subqueries in refinements must reference the LookML `${dimension}`, never `${TABLE}.?`.
2. Bare joins (`sql: ;;`) for companion JSON extracted views (`explore: table_base { extension: required view_name: table join: table__metadata { relationship: one_to_one sql: ;; } }`) paired with `bronze/:table__:col.view.lkml`.
3. Wildcard table base explores (`explore: events_base { extension: required view_name: events ... }`) with `_TABLE_SUFFIX` physical shard pruning (`always_filter:` and `sql_always_where:` using Liquid `date_start`, `date_end`, and `condition` tags). Wildcard table pruning is physical storage management that protects the warehouse from accidental full scans, making its Liquid the only sanctioned exception to the rule against Liquid in Bronze.
4. Datetime-partitioned table base explores (`explore: table_base { extension: required view_name: table always_filter: { filters: [table.event_date: "7 days"] } }`) on the actual column `dimension_group` to prevent unconstrained scans and warehouse `require_partition_filter` errors (no redundant `_PARTITIONDATE` pseudo-dimensions when partitioned on an actual column, and no `conditionally_filter:`).

In all four cases, downstream Silver explores inherit these physical structures and protections via `extends: [base]`.

### Silver layer (`silver/`, core semantic layer and cross-view `*_fields` views)

Any dimension or measure that anywhere in its dependency DAG references different views belongs in its own dedicated Silver view named by sorting the referenced view names alphabetically and appending `_fields` (`silver/:view_a_:view_b_fields.view.lkml`), and is bare-joined (`sql: ;;`, `relationship: one_to_one`) into the Explore that joins those views together. For example, if `order_items.gross_margin` is `${order_items.sale_price} - ${inventory_items.cost}` and `order_items.total_gross_margin` sums `${order_items.gross_margin}`, move both `gross_margin` and `total_gross_margin` (`type: sum`, `sql: ${gross_margin} ;;`) to `silver/inventory_items_order_items_fields.view.lkml` and bare-join `inventory_items_order_items_fields` into the Explore that joins `order_items` and `inventory_items`.

Derived views in `silver/:name.view.lkml` cover four additional patterns:

1. Consolidated entity-grain NDTs (`explore_source:`) combine multiple `GROUP BY entity_id` rollups into a single cohesive NDT (such as `silver/user_order_facts.view.lkml`). Silver NDTs are ephemeral by default (no premature `datagroup_trigger:` persistence), `derived_column:` in an NDT runs after `GROUP BY` for post-aggregation entity ranking and windows, and any aggregating (`GROUP BY`) derived table must use an NDT (`explore_source:`, paired with `cancel_grouping_fields:` on the Explore when grouping must be suppressed) rather than a `GROUP BY` SDT with `{{ measure._sql }}`.
2. Pre-`GROUP BY` row-level window views (`extends: [base_view]` with `${EXTENDED}` or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`) compute row-level windows before `GROUP BY` (such as `LAG({{ created_raw._sql }})` between consecutive orders) using `SELECT {{ _table }}.*, ... FROM (${EXTENDED}) AS {{ _table }}` (or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`).
3. Sessionization, windowing, and `QUALIFY` deduplication views group raw events into sessions or deduplicate single-table CDC ingestion logs (`QUALIFY ROW_NUMBER() = 1`).
4. `UNION ALL` SQL Derived Tables (SDTs) combine tables with overlapping schemas or the same table twice using `extends: [base_view]` (or multiple inheritance `extends: [view_a, view_b]`), `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` with `{{ field._sql }}` (PDT-safe), `fields: [ALL_FIELDS*, -view.unneeded]`, and a mandatory compound primary key.

Explores in `silver/explores/:name.explore.lkml` are anchored exclusively on fact, event, or transaction tables in the `FROM` clause (`orders`, `order_items`, `events`). Dimensional and lookup tables (`products`, `users`) are joined into fact Silver Explores rather than getting standalone Silver Explores. Every table join in a Silver explore must be a primary-key-to-foreign-key equality relationship (`many_to_one`, `one_to_one`, `one_to_many`), defaulting SQL `INNER JOIN` to `type: left_outer` unless a metric strictly requires inner filtering, plus bare joins (`sql: ;;`, `relationship: one_to_one`) for cross-view `*_fields.view.lkml` views. Never include runtime filter Liquid (`{% condition %}`, `{% parameter %}`), `bind_all_filters: yes`, inequality or time-bounded joins (`BETWEEN`, `>=`), non-key dimension joins, or `FULL OUTER JOIN ON FALSE` in Silver. Always declare `view_name:` explicitly on the Silver explore so Gold explores can extend it. When adding Quick Start `query:` blocks on the Silver Explore, include only modeled `dimensions`, `measures`, `filters`, `pivots`, `subtotals`, `limit`, `sorts`, `timezone`, and `description` (never Table Calculations or Custom Fields, which live in the query payload or dashboard tile).

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

## Writing LookML (Bronze)
- Created `bronze/orders.refinement.lkml` (primary key `id`, measure `total_net_revenue`)
- Created `bronze/explores/orders_base.explore.lkml` (`hidden: yes`)

## Pre-modeling validation and parity gate
- Initialized SQL Runner query (`/sql/<sql_id>`)
- Validation failed: `Unknown field "orders.net_amount" referenced in bronze/orders.refinement.lkml`
- Updating LookML: Replaced `${net_amount}` with `${amount}` in `bronze/orders.refinement.lkml`
- Validation passed: LookML Validator passed with 0 errors and early Bronze query parity matched.

## Writing LookML (Silver and Gold)
- Created `silver/orders_all.view.lkml` (`UNION ALL` SDT extending `orders` with compound PK)
- Created `silver/explores/orders.explore.lkml` (fact-anchored explore with Quick Start `query:` block)

## Writing and evaluating tests
- Created `tests/bronze/orders_base.test.lkml` (grouped refinement measures filtered to immutable date `orders.created_date = "2026-01-01"`)
- Created `tests/silver/orders.test.lkml` (grouped by join path DAG branch at `orders.created_date = "2026-01-01"`)
- Targeted test execution via `run_lookml_test` passed and final SQL-to-LookML parity matched (`/x/<query_id>`).
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

### Fixed conditional measures versus runtime filters and Custom Measures

1. If the query only computes metrics for a single slice (or repeats the same condition across all metrics), strip the condition from the measure. Ensure the base measure (`total_amount`) and filter dimensions (`status`, `country`) exist in `bronze/:table.refinement.lkml`, and apply the slice as a runtime Explore or Dashboard filter.
2. For infrequent multi-slice comparisons or ad-hoc cross-column `OR` conditions in a single report (such as `US Orders` versus `UK Orders`), do not add permanent LookML measures to `.refinement.lkml`. Keep `orders.count` in LookML and define the slice as a Custom Measure using [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) or Looker's [`matches_filter` syntax](https://docs.cloud.google.com/looker/docs/matches-filter) (`matches_filter(${orders.country}, \`US\`)` or `matches_filter(${orders.status}, \`Complete\`) OR ${orders.is_override}`) on the dashboard tile or Look query.
3. If a conditional measure is a core single-table domain KPI (requiring no joins across its entire dependency DAG, such as `completed_revenue`), define it in `bronze/:table.refinement.lkml` using Looker's declarative `filters:` syntax (never raw SQL `CASE WHEN` inside `sql:`). If a canonical single-table KPI requires `OR` across two columns, define a hidden `type: yesno` dimension in `bronze/:table.refinement.lkml` and filter on `filters: [is_cond: "yes"]`:
   ```lookml
   # In bronze/orders.refinement.lkml
   include: "orders.view.lkml"
   view: +orders {
     measure: completed_revenue {
       type: sum
       sql: ${amount} ;;
       filters: [status: "Complete"]
       value_format_name: usd
     }
   }
   ```
4. If any dimension, filtered measure, or ratio anywhere in its dependency DAG references fields from multiple joined views (such as `gross_margin` defined as `${order_items.sale_price} - ${inventory_items.cost}` and `total_gross_margin` defined as `type: sum` of `${gross_margin}`, or `${orders.gross_revenue} / NULLIF(${users.count}, 0)`), define all fields in that cross-view DAG inside a dedicated Silver view named alphabetically with `_fields` (`silver/inventory_items_order_items_fields.view.lkml` or `silver/orders_users_fields.view.lkml`) and bare-join it (`sql: ;;`, `relationship: one_to_one`) into the Explore that joins those views.

### Join paths, primary keys, fanouts, and layer routing

1. Bronze Explores (`bronze/explores/*.explore.lkml`) hold physical intra-table joins only: `UNNEST` joins on `REPEATED` columns (`sql: LEFT JOIN UNNEST(${table.array_col}) AS table__array_col WITH OFFSET AS table__array_col_offset ;;`, `relationship: one_to_many`, paired with a `WITH OFFSET` composite PK in `bronze/:table__:array_col.view.lkml`) and bare joins (`sql: ;;`, `relationship: one_to_one`) for companion JSON views (`bronze/:table__:json_col.view.lkml`). Inline `1:1` array lookups live as scalar dimensions in `bronze/:table.refinement.lkml` referencing LookML `${array_col}`, never `${TABLE}.?`.
2. Silver Explores (`silver/explores/*.explore.lkml`) are created only for `FROM`-clause fact or event tables (never standalone lookup or dimension tables like `users` or `products`) and contain strictly `PK = FK` equality joins (`sql_on: ${orders.user_id} = ${users.id} ;;`), defaulting SQL `INNER JOIN` to `type: left_outer` (`many_to_one`, `one_to_one`, `one_to_many`), plus bare joins (`sql: ;;`, `relationship: one_to_one`) for `silver/:view_a_:view_b_fields.view.lkml` cross-view field views. For date alignment, join `bronze/calendar_dates.view.lkml`.
3. Gold Explores (`gold/explores/*.explore.lkml`, `extends: [silver_explore]`, `tags: ["gold"]`) hold all inequality and time-bounded joins (`BETWEEN`, `>=`, `<`, SCD2, point-in-time `AS OF` deduplication SDTs) and OJOF (`FULL OUTER JOIN ON FALSE` plus `COALESCE` view) joins for unrelated fact schemas.
4. Ensure every joined view has a verified primary key (`primary_key: yes` in `bronze/:table.refinement.lkml`), and run the Two-Table Cardinality Audit SQL in [03-pk-fk-joins.md](references/03-pk-fk-joins.md) via `lkr code-mode` whenever a join's target view lacks a verified PK or relationship.

### Nested CTEs, reaggregations, windows, unions, and Liquid isolation

- Walk CTE chains from leaf to root ([06-nested-ctes-and-subqueries.md](references/06-nested-ctes-and-subqueries.md)): flatten pass-through projections, filters, and `PK = FK` joins into Bronze refinements, Silver `*_fields` views, and Silver Explores with zero derived tables; consolidate static entity-grain rollups into ephemeral Silver NDTs ([07-measure-of-measures-reaggregation.md](references/07-measure-of-measures-reaggregation.md)); and isolate filter-dependent CTEs in Gold (`bind_all_filters: yes` or `{% condition %}` paired with `always_filter:`).
- Route window functions and `QUALIFY` ([08-window-functions-and-qualify.md](references/08-window-functions-and-qualify.md)) across query-layer Table Calculations (display-set windows), Silver NDT `derived_column:` (post-`GROUP BY` windows), Silver `extends: [base_view]` with `${EXTENDED}` (pre-`GROUP BY` row-level windows or single-table CDC `QUALIFY`), and Gold `bind_all_filters: yes` NDTs or `AS OF` SDTs.
- Route `UNION ALL` and multi-fact stitching ([09-unions.md](references/09-unions.md), [05-dimensional-non-key-joins.md](references/05-dimensional-non-key-joins.md), [12-table-wildcards.md](references/12-table-wildcards.md)) across Bronze wildcard `_TABLE_SUFFIX` base explores (the sole Liquid exception outside Gold), Silver `UNION ALL` SDTs (`${}` substitution on every table and column, `extends: [base_view]`, mandatory compound PK, and `fields: [ALL_FIELDS*, -view.unmapped_col]`), and Gold OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` view) or Long Metrics explores.
- Enforce partition pruning and Liquid isolation ([13-large-tables-and-partitioning.md](references/13-large-tables-and-partitioning.md), [14-templated-filters-and-parameters.md](references/14-templated-filters-and-parameters.md)): model off actual partition columns (never redundant `_PARTITIONDATE` pseudo-dimensions when partitioned on a real column), document partition min-dates and clustering columns in `bronze/:table.refinement.lkml`, enforce `always_filter:` in `bronze/explores/:table_base.explore.lkml`, and keep `aggregate_table:`, `{% condition %}`, `{% parameter %}`, and `bind_all_filters: yes` strictly in `gold/` paired with `always_filter:`.

## Opinionated LookML testing and evaluation (`tests/`)

LookML tests (`test: [name] { explore_source: ... assert: ... }`) run in the Looker compiler and warehouse via `run_lookml_test` to verify that semantic models, joins, and calculations produce the expected numbers without regressions. Follow these rules whenever adding or refactoring LookML.

### Pre-modeling and pre-test verification gate

Execute the LookML validator, Explore schema generation (`lkr schema generate` and `lkr schema validate`), and query parity checks immediately after generating Bronze views and refinements, before writing any downstream LookML tests and before completing Silver modeling. Once `bronze/:table.view.lkml`, `bronze/:table.refinement.lkml`, and `bronze/explores/:table_base.explore.lkml` are generated:

1. Push the Bronze files to Looker development mode (`lkr --dev tools lookml push --no-reset`).
2. Generate the strongly-typed Explore query JSON Schema offline from local LookML using `lkr parse lookml-to-api --path "./data/$RUN_ID/lookml" -m "$MODEL_NAME" -e "$EXPLORE_NAME" -o "./data/$RUN_ID/explore_${EXPLORE_NAME}.json"` followed by `lkr schema generate -m "$MODEL_NAME" -e "$EXPLORE_NAME" --explore-file "./data/$RUN_ID/explore_${EXPLORE_NAME}.json" -o "./data/$RUN_ID/schema_${EXPLORE_NAME}.json"`. Use the generated schema's `fields`, `filters`, `sorts`, `pivots`, and `dynamic_fields` definitions to construct `run_inline_query` payloads and LookML `test:` `explore_source:` blocks, and pre-validate every inline query locally via `lkr schema validate --schema-file "./data/$RUN_ID/schema_${EXPLORE_NAME}.json" --query "$INLINE_QUERY_JSON"`.
3. Run [pre_gate.py](../agentic-lookml-workflow/scripts/pre_gate.py) with `--var validate="true"` via `lkr --dev code-mode sandbox` to initialize SQL Runner queries, execute Looker's `validate_project`, and confirm that Looker's generated query returns the same rows as SQL Runner in a single sandbox invocation. If syntax errors, broken references, or parity mismatches exist, resolve them before writing any tests.
4. Never author LookML data tests on top of a model that fails validation or diverges from the user's SQL query results. Both checks must pass before writing tests and finalizing Silver modeling.

### Silver layer testing rule

Every metric in any Silver layer must have a Looker test at an appropriate grain:
- Fact-level measures on base fact views (`orders.total_net_revenue`, `orders.order_count`), Silver NDT rollups (`user_order_facts.lifetime_orders`), and cross-view dimensions and measures in `silver/:view_a_:view_b_fields.view.lkml` (`inventory_items_order_items_fields.total_gross_margin`) must have corresponding test assertions in `tests/silver/:explore.test.lkml`.
- Untested metrics in the Silver layer are considered incomplete.

### Bronze refinement testing rule

Every measure added to a Bronze refinement must be tested, and all measures for a given refinement must be grouped into a single test query:
- Test all self-contained single-table measures (`type: sum`, `type: count`, `type: average`, filtered single-table KPIs) defined in `bronze/:table.refinement.lkml`.
- Rather than creating individual single-measure test queries, group all measures for that Bronze table into a single `explore_source` test block with multiple `column:` definitions and multiple `assert:` statements.
- To test Bronze refinement measures without polluting public explores or colliding with Silver explore names, create a hidden base explore that explicitly `include:`s its referenced `.view.lkml` and `.refinement.lkml` files (Looker's project validator validates standalone `.explore.lkml` and `.test.lkml` files in their own scope):
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
  Use the `:table_base` naming convention with `hidden: yes` to avoid any namespace collision with `silver/explores/order_items.explore.lkml`. Every standalone `.explore.lkml` (`bronze/explores/*`, `silver/explores/*`, `gold/explores/*`) and `.test.lkml` (`tests/bronze/*`, `tests/silver/*`) file must explicitly `include:` the `.view.lkml`, `.refinement.lkml`, or `.explore.lkml` files it references.

### Filtering to immutable data

Tests that query volatile data (such as "today", "yesterday", or unconstrained table scans) break over time as underlying rows change. Filter every test to an immutable slice:
- First, inspect the view's dimensions for immutable date or timestamp columns by matching name patterns such as `*_created_*`, `*_event_*`, `*_ordered_*`, `*_inserted_*`, `*_occurred_*`, `*_at`, or `*_date` (for example, `orders.created_date`), and filter to a fixed historical calendar date with stable data (such as `2026-01-01`).
- Second, if no immutable timestamp or date dimension exists on the table, filter by a specific primary key (such as `id = 123`).
- During test authoring, query the instance via `code-mode` (`run_inline_query` or `run_query`) on the chosen immutable slice (such as `created_date = '2026-01-01'`) to retrieve the exact calculated metric value, then freeze that number in the LookML `assert:` expression (for example, `${order_items.total_sale_price} = 125.50`).

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
    expression: ${order_items.total_sale_price} = 4520.25 ;;
  }
  assert: order_item_count_matches {
    expression: ${order_items.count} = 84 ;;
  }
}
```

### Grouping Silver layer tests by join path DAG branch

In Silver explores, foreign tables and bare-joined cross-view `*_fields` views join along explicit paths in the explore DAG (`orders -> users`, `orders -> order_items -> inventory_items`). Group all measures that depend on the same join path branch into a single `explore_source` test block. For example, in `orders.explore.lkml`:
1. On the base fact branch, test `orders` measures (`order_count`, `total_revenue`) filtered to the immutable date.
2. On the `orders -> users` join branch, test `users` measures joined to `orders` alongside `orders_users_fields` metrics (`revenue_per_user`) in one test block.
3. On the `orders -> order_items -> inventory_items` join branch, test `inventory_items` and `inventory_items_order_items_fields` metrics (`total_gross_margin`) in one test block.

Example Silver test:
```lookml
# In tests/silver/orders.test.lkml
include: "../../silver/explores/orders.explore.lkml"

test: orders_fact_metrics_at_fixed_date {
  explore_source: orders {
    column: order_count { field: orders.order_count }
    column: total_net_revenue { field: orders.total_net_revenue }
    filters: {
      field: orders.created_date
      value: "2026-01-01"
    }
  }
  assert: order_count_matches {
    expression: ${orders.order_count} = 42 ;;
  }
  assert: total_net_revenue_matches {
    expression: ${orders.total_net_revenue} = 3850.00 ;;
  }
}

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
