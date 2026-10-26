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

## Overview and scope

`agentic-lookml` combines:
- The 14 SQL-to-LookML pattern playbooks in `references/`, paired with `lkr parse sql-lookml-compare`, the Canonical Looker Query translation gate, Query-layer triage, and the Bronze / Silver / Gold Medallion hierarchy.
- The 9 LookML syntax reference sub-skills under [lookml](../lookml/SKILL.md) (`.agents/skills/lookml/sub-skills/*/SKILL.md`).

**Scope boundaries:**
- **`drill_fields:` is out of scope:** Never author, add, or modify `drill_fields:` (or drill-only `set:` blocks) unless explicitly requested, and do not flag missing `drill_fields:`.
- **Field curation (`suggestable:`, bulk descriptions) is on-demand:** Only run [lookml-field-curation](../lookml-field-curation/SKILL.md) when explicitly asked to curate fields.

## Unified reference index

### SQL-to-LookML pattern playbooks (`references/`)

Each SQL query analyzed by `lkr parse sql-lookml-compare` can match one or multiple pattern categories simultaneously. Consult the matching playbook in `references/` after inspecting `compare_initial.json` (skip `01-simple-single-table.md` and `02-conditional-measures-and-bucketing.md` when single-table / existing-Explore routing and the Triage table below already cover the query):

| # | Category ID | Pattern playbook | AST trigger summary | Target layer |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `simple_single_table` | [01-simple-single-table.md](references/01-simple-single-table.md) | 1 table, no joins/CTEs/unions/windows, standard columns and single-pass aggregates | `bronze/:table.refinement.lkml` + `bronze/explores/:table.explore.lkml` (until a Silver join is needed) |
| 02 | `conditional_measures_and_bucketing` | [02-conditional-measures-and-bucketing.md](references/02-conditional-measures-and-bucketing.md) | `SUM(CASE WHEN ...)`, `COUNTIF`, row-level `CASE WHEN` buckets, or measure-to-measure ratios | Query Layer (`Custom Field` / `Table Calc`), `bronze/:table.refinement.lkml` (single-table DAG), or `silver/:view_a_:view_b_fields.view.lkml` (multi-view DAG, bare-joined) |
| 03 | `pk_fk_joins` | [03-pk-fk-joins.md](references/03-pk-fk-joins.md) | Equality joins (`t1.fk = t2.pk`) between entity and fact tables | `silver/explores/:name.explore.lkml` (`type: left_outer`) + `bronze/:table.refinement.lkml` (PKs) + `silver/:view_a_:view_b_fields.view.lkml` |
| 04 | `triangle_inequality_joins` | [04-triangle-inequality-joins.md](references/04-triangle-inequality-joins.md) | Join `ON` contains `<, <=, >, >=, BETWEEN` (SCD2, rolling windows, point-in-time `AS OF`) | Strictly `gold/explores/` (`extends: [silver]`, `tags: ["gold"]`) + Gold `AS OF` view or `bronze/calendar_dates.view.lkml` |
| 05 | `dimensional_non_key_joins` | [05-dimensional-non-key-joins.md](references/05-dimensional-non-key-joins.md) | Joins on non-unique attributes (`date = date`, `country = country`) or `FULL OUTER JOIN` across facts | Gold OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` view), Silver `UNION ALL` SDT, Silver NDT, or `bronze/calendar_dates.view.lkml` |
| 06 | `nested_ctes_and_subqueries` | [06-nested-ctes-and-subqueries.md](references/06-nested-ctes-and-subqueries.md) | Pass-through CTEs or subqueries doing renames, scalar math, row filters, or `PK = FK` joins without grain changes | Flatten into `bronze/:table.refinement.lkml` + `silver/explores/` (0 Derived Tables) |
| 07 | `measure_of_measures_reaggregation` | [07-measure-of-measures-reaggregation.md](references/07-measure-of-measures-reaggregation.md) | Outer query aggregates, tiers, or filters on an inner `GROUP BY` aggregate column | `silver/:entity_facts.view.lkml` (consolidated ephemeral NDT `explore_source:`) or `gold/` if `bind_all_filters: yes` |
| 08 | `window_functions_and_qualify` | [08-window-functions-and-qualify.md](references/08-window-functions-and-qualify.md) | `OVER (PARTITION BY ... ORDER BY ...)` (`ROW_NUMBER`, `RANK`, `LAG`, `LEAD`) or `QUALIFY` | Query Layer (`Table Calc`), `silver/` NDT (`derived_column:` post-`GROUP BY`), `silver/` SDT (`${EXTENDED}` pre-`GROUP BY` / `QUALIFY`), or `gold/` (`bind_all_filters: yes`) |
| 09 | `unions` | [09-unions.md](references/09-unions.md) | `UNION ALL` or `UNION DISTINCT` across tables or CTEs | `silver/:name.view.lkml` (SDT with `${}` on everything, `extends: [base_view]`, `fields: [ALL_FIELDS*, -view.unneeded]`, compound PK) or `gold/` (Long Metrics) |
| 10 | `unnest_arrays` | [10-unnest-arrays.md](references/10-unnest-arrays.md) | `UNNEST(...)`, `CROSS/LEFT JOIN UNNEST`, or correlated `FROM UNNEST` scalar subqueries | `bronze/:table.refinement.lkml` (`1:1` inline using `${dimension}`) or `bronze/:table__:arr.view.lkml` (`WITH OFFSET` PK) + `bronze/explores/` and `silver/explores/` (`1:M`) |
| 11 | `json_columns_and_extract` | [11-json-columns-and-extract.md](references/11-json-columns-and-extract.md) | `JSON_VALUE`, `JSON_EXTRACT_SCALAR`, `JSON_QUERY_ARRAY`, `LAX_*`, or JSON path access (if SQL only wraps scalar columns via `TO_JSON_STRING(STRUCT(...))` in a pass-through CTE with no physical JSON column, unwrap directly to Bronze dimensions with zero companion views/derived tables) | `bronze/:table.refinement.lkml` (`hidden: yes`) + `bronze/:table__:col.view.lkml` (`SAFE_CAST`) + `bronze/explores/` (bare join `sql: ;;`) + `silver/explores/` |
| 12 | `table_wildcards` | [12-table-wildcards.md](references/12-table-wildcards.md) | `FROM table_*` or `_TABLE_SUFFIX` predicates | `bronze/` (`table_*` view, refinement, `bronze/explores/:prefix.explore.lkml` with Liquid `_TABLE_SUFFIX` pruning + `always_filter:`; detach `:prefix_base` + `silver/explores/` only when joined) |
| 13 | `large_tables_and_partitioning` | [13-large-tables-and-partitioning.md](references/13-large-tables-and-partitioning.md) | Physically partitioned/clustered warehouse tables, `APPROX_COUNT_DISTINCT`, or `aggregate_table` (on unpartitioned tables, rewrite `DATE(ts)` directly to `<group>_date` filters without `always_filter:`) | `bronze/` (actual column `dimension_group`, partition notes in refinement, `always_filter:` on physically partitioned tables only) + `gold/explores/` (`aggregate_table`) |
| 14 | `templated_filters_and_parameters` | [14-templated-filters-and-parameters.md](references/14-templated-filters-and-parameters.md) | Runtime filters required inside inner subqueries/cohorts (`{% condition %}`, `{% parameter %}`) | Strictly `gold/` and `gold/explores/` (`tags: ["gold"]`) paired with mandatory `always_filter:` |

Standard `sum`/`average`/`min`/`max`/`count_distinct` measures strip outer `ROUND(<agg>, k)` / `COALESCE(<agg>, 0)` into one native measure (`value_format_name: usd` / `decimal_0..4` / `id`, omitting `decimal_0` on `count_distinct` named with a plural/count noun not ending in `id`/`year`/`decade`), and `100.0 * <num_agg> / <den_agg>` or `<agg>(<ratio>) * 100` strips `100.0 *` / `* 100` with `value_format_name: percent_2` and renames `*_pct` / `*_percent` to `*_ratio` / `*_rate` / `*_share` (`pre_gate.py` aligns `ROUND`, `* 100`, and aliases); only open [measures-and-sql-functions.md](references/measures-and-sql-functions.md) **after** `compare_initial.json` returns for `COUNT(nullable_col)`, `WHERE` vs `filters:` splits, `percentile`/`median`, `STDDEV`/`VARIANCE`, or `CORR`/`COVAR_*`.

### Companion skills & LookML syntax references

- **Workflow & tooling:** [agentic-lookml-workflow](../agentic-lookml-workflow/SKILL.md) ([setup](../agentic-lookml-workflow/sub-skills/setup/SKILL.md)), [generate-view-from-table](../generate-view-from-table/SKILL.md), and on-demand [lookml-field-curation](../lookml-field-curation/SKILL.md).
- **Filters & expressions:** [looker-filters](../looker-filters/SKILL.md) (single-field `filters:` string syntax, Custom Filters, and SDK filter keys; `type: string` filters only `^`-escape literal `"`, `%`, `_`, `,`, `^`, and leading `-`/space—`()`, `+`, `$`, `.`, `/`, and `&` need no escape; `"after YYYY/MM/DD"` is inclusive `>=` and `"before YYYY/MM/DD"` is exclusive `<`) and [looker-expressions](../looker-expressions/SKILL.md) (Looker expression formulas across post-query Table Calculations and `.test.lkml` `assert:` vs. SQL-pushdown Custom Fields, Custom Filters `filter_expression`, `matches_filter`, and NDT `expression_custom_filter:`). Skip reading both on standard LookML dimensions/measures, date/string `filters:` slices, `dynamic_fields` covered below, and `.test.lkml` equality/row-`index()` assertions—only open them for exotic filter/expression functions.
- **LookML syntax (`../lookml/`, read-only upstream):** [lookml](../lookml/SKILL.md) (`lookml-model`, `lookml-view`, `lookml-explore`, `lookml-fields`, `lookml-refinements`, `lookml-liquid`, `lookml-ojof`, `lookml-sets`, `lookml-access-grants`, `lookml-tests`). `agentic-lookml` + `references/` are self-contained for views, refinements, explores, Quick Start `query:` blocks, and `.test.lkml`—only open `../lookml/` for specialized parameters (`html:`, `link:`, `access_grant:`, `map_layer:`), and `agentic-lookml` rules (Medallion paths; ephemeral Silver NDTs; no unrequested `drill_fields:` / `set: detail`; no inline `view: +name` refinements in `.explore.lkml`) always supersede `../lookml/`.

## How `lkr parse sql-lookml-compare` drives refactoring

`lkr parse sql-lookml-compare` outputs per-query `parsed_query` ASTs, matched `views`/`fields` (`primary_key`, `timeframes`, `via`, `unmodeled_db_columns`), `explores` & `join_analysis` (`status`, `relationship`, `inferred_relationship`, `safety_warnings`, `precedents`), plus `tests`, `aggregate_tables`, and `explore_queries` (`coverage`).

## Canonical Looker Query translation gate

Before creating any derived table (NDT or SDT), check whether the SQL query reduces to a flat Canonical Looker Query (`SELECT dims, agg_measures FROM base LEFT JOIN joins WHERE filters GROUP BY dims HAVING measure_filters ORDER BY ... LIMIT ...`; see [How Looker Generates SQL](https://docs.cloud.google.com/looker/docs/how-looker-generates-sql)).

When a query (even with pass-through CTEs/subqueries) maps to this shape without grain changes or non-`PK = FK` joins using Bronze refinements, Silver `PK = FK` joins + bare-joined `*_fields` views, runtime filters, and post-aggregation `dynamic_fields`, model zero derived tables:
- Author an Explore Quick Start `query:` block containing **only** modeled `dimensions`, `measures`, `filters` (including `HAVING` measure predicates), `pivots`, `subtotals`, `limit` (unquoted integer), `sorts` (`[view.field: desc]`), `timezone`, and `description` (Looker's `explore: { query: {} }` never accepts `dynamic_fields`, so when a multi-query `input.sql` defines distinct filter/ratio variants across its queries, promote each variant with predicate-distinct canonical names so every query gets a native Quick Start `query:` block):

```lookml
query: top_countries {
  dimensions: [users.country]
  measures: [orders.count, orders.total_net_revenue]
  filters: [orders.status: "-Cancelled", orders.count: ">=30"]
  sorts: [orders.total_net_revenue: desc]
  limit: 20
}
```

- Place any Table Calculations or Custom Fields in `dynamic_fields` on the Looker `WriteQuery` / `run_inline_query` payload (`{"dimension": "d", "label": "D", "expression": "case(when(${v.f} = \"a\", \"A\"), \"B\")"}`, `{"measure": "m", "label": "M", "based_on": "v.f", "type": "count_distinct", "filter_expression": "${v.x} > 0"}`, or `{"table_calculation": "tc", "label": "TC", "expression": "if(${v.den} = 0, null, ${v.num} / ${v.den})"}`; any Custom Dimension/Measure in `dynamic_fields` must **also** list its `.name` in `fields`, `based_on` must reference a `hidden: no` field, and `table_calculation` sorts must appear *after* database sorts in `sorts` like `["orders.total_net_revenue desc", "pct_of_total desc"]`, with `"limit": "500"` string in `WriteQuery` JSON; use a Custom Dimension when a query projects ad-hoc string labels distinct from a canonical LookML dimension while keeping the canonical dimension in Quick Start `query:`). Dimension-only row-level queries omit `measures:` in `query:` (and omit `sorts:` when `input.sql` has no `ORDER BY`); map raw SQL `TIMESTAMP`/`DATETIME` projections and `ORDER BY` columns directly to `<group>_time` (`orders.created_time`—never `<group>_raw`, which is `hidden: yes` `date_raw`, and never invent duplicate `*_timestamp` dimensions; `pre_gate.py` normalizes UTC/subsecond `TIMESTAMP` strings, general `ORDER BY` sort ties, and `LIMIT N` boundary tie-pools automatically); if an ungrouped non-`DISTINCT` row-level `SELECT` omits the base view's `primary_key`, append `<base_view>.<pk>` (or `common_helpers.no_group`) as the last item in `inline_query.fields` so Looker cancels `GROUP BY` deduplication (`pre_gate.py` strips the trailing grain key automatically).

Escalate to Silver NDTs/SDTs or Gold specialty explores **only** when grain-changing reaggregations, pre-`GROUP BY` row windows/`QUALIFY`, `UNION ALL`, runtime-filtered subqueries, or non-key/inequality joins prevent a flat canonical query.

## The Medallion LookML architecture (Bronze, Silver, and Gold)

```text
├── bronze/
│   ├── order_items.view.lkml                        # Autogenerated 1:1 physical table (DO NOT MODIFY)
│   ├── order_items.refinement.lkml                  # Created on-demand (PKs, single-table dims/measures, descriptions)
│   ├── orders__line_items.view.lkml                 # Companion UNNEST or JSON extracted view (:table__:col.view.lkml)
│   ├── calendar_dates.view.lkml                     # Standard calendar spine view for date joins
│   ├── common_helpers.view.lkml                     # Bare-joined helper: no_group (sql: 1 ;;) + current_timestamp
│   ├── :schema/ (:dataset/:schema/ on collision)    # Nested ONLY when table names collide across schemas/projects
│   └── explores/
│       ├── events.explore.lkml                      # Unjoined single-table explore (hidden: no)
│       └── order_items_base.explore.lkml            # Detached base explore (hidden: yes) once promoted to Silver
├── silver/
│   ├── inventory_items_order_items_fields.view.lkml # Cross-view DAG dims & measures (alphabetical views + _fields, bare-joined)
│   ├── user_order_facts.view.lkml                   # Consolidated entity NDTs (ephemeral), ${EXTENDED} windows, UNION ALL SDTs
│   └── explores/
│       └── order_items.explore.lkml                 # PK=FK joins (default left_outer) + bare-joined *_fields; extends: [:table_base], hidden: no; ZERO Liquid
├── gold/
│   ├── orders_dynamic_rank.view.lkml                # Specialty views: bind_all_filters NDTs, Liquid SDTs, AS OF SDTs, OJOF COALESCE views
│   └── explores/
│       └── orders_subscription_attribution.explore.lkml # extends: [silver_explore], tags: ["gold"]; inequality joins, OJOF, Liquid + always_filter, aggregate_table
├── tests/
│   ├── bronze/                                      # Single-table measures tested at table grain on immutable slices
│   └── silver/                                      # Silver joins, *_fields, and NDT/SDT metrics ONLY
└── project.model.lkml                               # Includes bronze/explores/**, silver/explores/**, gold/explores/**, tests/**/*.test.lkml
```

### Bronze layer (`bronze/`)

- **Immutable base views (`bronze/:table.view.lkml`):** Never hand-edit autogenerated base views or duplicate logic (`lkr parse lookml-to-api --validate` rejects duplicate logic and alias collisions). Reuse committed fields as-is (snapshots track `connections`, `measures`, `access`, `sql`, and `tests`, not dimension `description`/`synonyms` or Explore `query:` blocks). On newly authored or touched fields, sanitize quirky SQL `AS` aliases into canonical domain identifiers, put genuine business terms/acronyms/standalone-honest SQL aliases in `synonyms: [...]` (never thesaurus filler or `WHERE`-filtered aliases on unfiltered fields), and reserve `alias: [...]` strictly for renaming already-committed LookML fields. Refine autogenerated `measure: count` in `bronze/:table.refinement.lkml` (`description:`, standalone-honest `synonyms:`, and `label:` **only** on a brand-new Explore—existing Explores already snapshot `"Count"`) and reference `<view>.count` everywhere.
- **Refinements (`bronze/:table.refinement.lkml`):** Create on-demand with first line `include: ":table.view.lkml"`. Holds verified PKs, single-table dimensions (`type: yesno`, `type: duration`, `EXTRACT(... FROM ${<group>_raw})` with `value_format_name: id` on years and `DAYOFWEEK` `1..7` UTC vs `day_of_week_index`, native `case:` buckets), single-table measures (`sum`, `average`, `count_distinct`, `percentile`, `median`, single-table filtered KPIs/ratios) whose `${...}` DAG stays within `:table` (except `${common_helpers.*}`), shared noun `group_label:` folders for `3+` sibling attribute dimensions (never under a date `dimension_group`'s `"<Name> Date"` label), country/domain guards on regional dimensions (e.g., gate US regions/ZIP zones with `${country} = 'United States'` and omit catch-all `else:` so international rows stay `NULL`), and structural/safety `tags:` on **newly authored or touched fields** (`tags: ["non_additive"]` on ratios/`average`/`min`/`max`/`count_distinct`/`APPROX_COUNT_DISTINCT`/`percentile`/`median`/`stddev`, `tags: ["foreign_key"]` on new join keys, and `tags: ["pii"]`/`"email"`/`"phone"` on sensitive columns—adding `tags: ["pii"]` on a newly created field is purely additive under `--allow-additions`, keeping `requires_review: false`; leave untouched fields as-is, and never duplicate `primary_key`, `hidden`, `suggestable`, `type`, or `value_format_name` in `tags:`).
- **Reusable Bronze helpers (`bronze/common_helpers.view.lkml` & `bronze/calendar_dates.view.lkml`):** Bare-join `common_helpers` (`join: common_helpers { sql: ;; relationship: one_to_one }`, exempted from `silver/*_fields.view.lkml` as a table-less Bronze helper) onto the base explore (and any explore joining the referencing view) for `common_helpers.no_group` (`primary_key: yes`, `hidden: yes`, `type: number`, `sql: 1 ;;`, paired with `cancel_grouping_fields: [common_helpers.no_group]`) or `common_helpers.current_timestamp_raw` (`dimension_group: current_timestamp { hidden: yes type: time timeframes: [raw, time, date, week, month, quarter, year] sql: CURRENT_TIMESTAMP() ;; }`). Model elapsed time (`TIMESTAMP_DIFF` / `DATE_DIFF`) via a `type: duration` `dimension_group` (`intervals: [day, ...]`, `sql_start: ${created_raw} ;;`, `sql_end: COALESCE(${sold_raw}, ${common_helpers.current_timestamp_raw}) ;;`) and reference `${days_<group>}` in downstream `case:` tiers—never repeat raw `TIMESTAMP_DIFF(..., CURRENT_TIMESTAMP(), ...)` inside a `CASE` dimension.
- **Bronze explores (`bronze/explores/`):**
  - Serve unjoined single-table queries directly from `bronze/explores/:table.explore.lkml` (`explore: :table`, `hidden: no`, `label: "..."`, `view_name: :table`) until a cross-table `join:`, `silver/*_fields.view.lkml`, or Silver NDT/SDT is needed.
  - Once a Silver join is needed, detach into `bronze/explores/:table_base.explore.lkml` (`explore: :table_base`, `hidden: yes`, `view_name: :table`, updating **only the `include:` path** in `tests/bronze/:table.test.lkml` to `../../silver/explores/:table.explore.lkml` so existing `explore_source: :table` blocks and `tests.snap.json.md` remain untouched) and extend in `silver/explores/:table.explore.lkml` (`explore: :table`, `extends: [:table_base]`, `hidden: no`, preserving the existing Explore `label: "..."` so `measures.snap.json.md` stays additive, `view_name: :table`), preserving `<model>.:table`.
  - Keep four physical intra-table mechanics in Bronze explores: (1) `LEFT JOIN UNNEST(${table.arr}) ... WITH OFFSET` (`one_to_many`), (2) bare joins (`sql: ;;`, `one_to_one`) for `bronze/:table__:json_col.view.lkml`, (3) wildcard `_TABLE_SUFFIX` shard pruning (`always_filter:` + Liquid `sql_always_where:` — the sole Liquid exception outside Gold), and (4) partition `always_filter:` on the real partition `dimension_group` (no `_PARTITIONDATE` pseudo-dimensions or `conditionally_filter:`).

### Silver layer (`silver/`)

- **Cross-view `*_fields` views (`silver/:view_a_:view_b[..._fields].view.lkml`):** Any dimension or measure whose dependency DAG touches `2+` views goes into a single view named by sorting all participating LookML view names alphabetically + `_fields` (e.g., `silver/order_items_products_users_fields.view.lkml`, co-locating `hidden: yes` helper dimensions used by those measures and treating NDTs like `user_cohort_facts` as their own view name), declares a hidden `dimension: pk { primary_key: yes hidden: yes ... }` (`type: number sql: ${base.id} ;;` when only bare-joined onto an `M:1` fact explore, or `CONCAT(...)` when also bare-joined onto a `1:M` parent explore), and is bare-joined (`sql: ;;`, `relationship: one_to_one`) onto Silver Explores joining those views. When the same `*_fields` file is bare-joined onto multiple Explores with different base grains (e.g., `explore: users` vs `explore: order_items`), keep all `(view_a, view_b)` fields in that single file and exclude grain-mismatched measures on each Explore via `explore: { fields: [ALL_FIELDS*, -order_items_users_fields.revenue_per_registered_user] }`.
- **Silver derived views (`silver/:name.view.lkml`):**
  1. Consolidated entity-grain NDTs (`explore_source:`, ephemeral by default; `derived_column:` for post-`GROUP BY` windows; never write `GROUP BY` SDTs with `{{ measure._sql }}`).
  2. Pre-`GROUP BY` row-window or single-table CDC `QUALIFY` SDTs (`extends: [base_view]` using `FROM (${EXTENDED}) AS {{ _table }}` or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`).
  3. `UNION ALL` SDTs (`extends: [base_view]`, `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` with `{{ field._sql }}`, `fields: [ALL_FIELDS*, -view.unneeded]`, and a compound PK).
- **Silver explores (`silver/explores/:name.explore.lkml`):**
  - Create **only** when cross-table `PK = FK` joins, `silver/*_fields.view.lkml`, or Silver NDT/SDT views are required (never create joinless pass-through Silver explores).
  - Preserve query grain: never route `FROM :entity` (`FROM users`) onto a fact explore (`FROM order_items LEFT JOIN users`) when `:entity`-grain measures or `LEFT JOIN` 0-activity entities are queried; conversely, when SQL writes `FROM :parent INNER JOIN :child` and aggregates **only `:child` columns** grouped by `:parent` dimensions (zero `:parent`-grain measures), anchor on `:child`'s Silver Explore (`many_to_one` to `:parent`, adding `:parent.id: "NOT NULL"` if `:child`'s FK is nullable) rather than creating a `one_to_many` parent explore.
  - Strict YAGNI on joins: join only tables referenced in `input.sql` or explicitly required by `metrics.md`. Default SQL `INNER JOIN` to `type: left_outer` (`many_to_one`, `one_to_one`, `one_to_many`) unless business semantics strictly require inner filtering; if `input.sql` tests both `LEFT JOIN` (all entities) and `INNER JOIN` (active/purchasing entities) on the same base entity, keep `type: left_outer` on the Explore and apply a non-null child filter (`child.id: "NOT NULL"` on `type: number` PKs, or `-NULL` on `type: string`) or filtered measure on the `INNER JOIN` query.
  - Always declare `view_name:` explicitly, ensure every joined view has `primary_key: yes` (verifying cardinality via [03-pk-fk-joins.md](references/03-pk-fk-joins.md) when unknown), place any `fields: [ALL_FIELDS*, -view.field]` exclusions on `explore:` (never inside `join:`, where `ALL_FIELDS*` is undefined), and include zero runtime Liquid, inequality joins, non-key joins, or OJOF in Silver.

### Gold layer (`gold/`)

- **Gold views (`gold/:name.view.lkml`) & explores (`gold/explores/:name.explore.lkml`):** Extend Silver explores (`extends: [silver_explore]`, explicit `view_name:`, `tags: ["gold"]` — never suffix explore names with `_gold`). Isolate `bind_all_filters: yes`, runtime Liquid (`{% condition %}`, `{% parameter %}`) paired with mandatory `always_filter:`, inequality/SCD2/`AS OF` joins, OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` view), Long Metrics, and `aggregate_table:` blocks.
- **DRY SDT substitution rule (Silver & Gold):** Every SQL Derived Table must reference tables via `${view_name.SQL_TABLE_NAME} AS {{ _table }}` or `(${EXTENDED}) AS {{ _table }}` (never raw `db.schema.table`) and columns via `{{ field._sql }}`, `${field}`, or `${TABLE}.col`. For a second table in an SDT join, bare-join an `_sdt_*` alias (`join: _sdt_other { from: other_view sql: ;; relationship: one_to_one fields: [] }`) and reference `AS {{ _sdt_other._name }}` + `{{ _sdt_other.field._sql }}`.

## Triage: Query Layer vs. LookML

| Calculation type | Keep in Query / Dashboard (`dynamic_fields`) when... | Promote to LookML (`bronze/*.refinement.lkml` or `silver/*_fields.view.lkml`) when... |
| :--- | :--- | :--- |
| Filtered measure (`SUM(CASE WHEN ...)` / `COUNTIF`) | Infrequent single-tile comparison (`us_orders` vs `uk_orders`): use a Custom Measure with [looker-filters](../looker-filters/SKILL.md) or `matches_filter` ([looker-expressions](../looker-expressions/SKILL.md)). | Canonical domain KPI reused across queries or defined in `metrics.md` (`filters: [...]`; use a shared `hidden: yes` positive `type: yesno` dimension for cross-column `OR` or when filtering on a `case:` bucket whose label contains commas `,`—otherwise `^,`-escape literal commas). |
| Row-level bucketing (`CASE WHEN ...`) | Campaign- or report-specific promo/cohort bucket: use a Custom Dimension ([looker-expressions](../looker-expressions/SKILL.md)). | Reusable domain tier/flag/regime (`age_tier`, `is_sold`, `shopping_regime`) or expression over unmodeled `${TABLE}.col`. |
| Named Business Term (`metrics.md` / `terms/*`) | Unnamed one-off `WHERE` slice (`age < 25` with no named domain term): filter directly on the base dimension ([looker-filters](../looker-filters/SKILL.md)). | Promote or reuse a LookML dimension matching the term's shape (sanitize playful/persona titles and SQL aliases into canonical identifiers while preserving the persona/business title in `label:` + `synonyms:`; never blanket-apply `is_`, add negated `yesno` twins, or invent speculative `<term>_count` measures unless requested): **relative/rolling calendar period** (*"New Customer: current calendar year"*, *"Recent Signup: last 30 days"*) $\rightarrow$ never bake `CURRENT_TIMESTAMP()`/`CURRENT_DATE()` or a literal year into `is_<term>`; reuse `<group>_year` / `<group>_date` (`"this year"`, `"30 days"`, or `${<fact>.created_year} = ${<entity>.created_year}` Custom Filter / `years_since_signup = 0`) and enrich `description:` + standalone-honest `synonyms:`; **1:1 synonym or `"no"`/`IS NULL` state of an existing positive `yesno`** (`sold_at IS NULL` on `is_sold`) $\rightarrow$ enrich `synonyms:`/`description:` and filter `"no"`; **new time-invariant binary flag** $\rightarrow$ positive `type: yesno` `is_<term>`/`has_<term>` + noun `label: "<Term>"`; **categorical/bucketing** $\rightarrow$ canonical noun `<term>` with native `case: { when: { sql: ... ;; label: "..." } else: "..." }` (or `type: tier`), stripping `'1. '`–`'9. '` prefixes (`pre_gate.py` aligns stripped prefixes) and ordering `when:` in `1..N` display order (`else:` sorts last unless `alpha_sort: yes`; never put `#1` in `else:`, **explicitly negate earlier SQL branches** like `NOT (cond_3) AND cond_2` whenever promoting `#2` above `#3` to preserve short-circuit counts, omit `else:` on country/subset-scoped buckets so out-of-scope rows stay `NULL`, and group `3+` sibling attributes under a noun `group_label:`); **derived scalar/duration** $\rightarrow$ canonical noun `<term>` (`string`/`number` or `type: duration` `dimension_group` with `${common_helpers.current_timestamp_raw}`); **entity-grain aggregate cohort** $\rightarrow$ Silver Rollup NDT ([07-measure-of-measures-reaggregation.md](references/07-measure-of-measures-reaggregation.md)). |
| Post-aggregation math (`SUM(a)/SUM(b)`, `% of total`, `LAG`) | Visual display math (`pct_of_total`, `running_total()`, `offset()`): use a Table Calculation ([looker-expressions](../looker-expressions/SKILL.md)). | Foundational business ratio (`average_order_value`, `per_capita_spend`) defined in `metrics.md` or reused across queries/NDTs (`type: number`, `1.0 * ${num} / NULLIF(${den}, 0)`). |

### Blast-radius autonomy tiers

1. **Tier 1 (Auto-Apply):** Missing/stale Bronze views (`generate-view-from-table`), additive single-table dimensions/measures in `bronze/:table.refinement.lkml`, JSON/`1:1` `UNNEST` extractions, unaffected `tests`.
2. **Tier 2 (Batch Confirm):** New `PK = FK` joins or `silver/*_fields.view.lkml` bare joins, Bronze physical-exception base explores (`UNNEST`, JSON, `_TABLE_SUFFIX`, partition `always_filter:`), consolidated Silver NDTs, or Query-layer vs LookML triage.
3. **Tier 3 (Architectural Escalation):** Gold specialty explores (`tags: ["gold"]`) or edits to dimensions/measures with downstream `via` dependents or `tests`.

## Standardized diagnostic contract & `./data/:id/summary.md`

When reporting `sql-lookml-compare` analysis, summarize: matched pattern IDs & AST triggers, matched views/fields (`via`) vs unmodeled columns, affected explores/tests, target Medallion layer, autonomy tier, and surgical LookML changes.

Record these six sections in `./data/:id/summary.md` for the GitHub PR:
1. **Generating base views** (`bronze/:table.view.lkml` created/refreshed or verified complete)
2. **Deconstructing query to canonical form** (`FROM`, `LEFT JOIN`, dims, measures, filters, sorts/limits, key modeling decisions, plus—whenever an NDT/SDT or Gold explore is used—the exact reason a flat Canonical Looker Query could not express it)
3. **Query patterns from original query** (matched playbook IDs from the 14 categories)
4. **Writing LookML (Bronze, Silver, and Gold)** (every file created/updated)
5. **Pre-test validation and parity gate** (`/sql/<sql_id>` and `/x/<query_id>` parity, plus any `Validation failed:` / `Updating LookML:` self-heals)
6. **Writing and evaluating tests** (`tests/bronze/` and `tests/silver/` slices, baseline assertions, and targeted `run_lookml_test` result)

## Opinionated LookML testing (`tests/`)

### Single-push pre-test gate
Author Bronze refinements, Bronze explores, and any Silver/Gold views and explores **together before the first push**, validate locally (`lkr parse lookml-to-api --validate`, batch `lkr schema validate --explore-file`), push once, and run [pre_gate.py](../agentic-lookml-workflow/scripts/pre_gate.py) (including `--var test_queries_json` for immutable test slices) in a single sandbox call before writing `.test.lkml` files.

### Incremental `test:` blocks & layer separation
- **Bronze (`tests/bronze/:table.test.lkml` or `:table_base.test.lkml`):** Test single-table refinement measures and dimensions/terms **only** in `tests/bronze/` (targeting `explore_source: :table` while unjoined; when detaching `:table` to Silver later, update **only** `include:` to `../../silver/explores/:table.explore.lkml` and never edit existing `explore_source: :table` blocks). When testing a newly authored or enriched **dimension / Business Term** with zero new measures, never invent throwaway measures just for the test: on a bounded historical date slice (`created_date: "2024-01-01"`, or bounded PK slice `id: "<=1000"` on timeless catalog tables), either filter `is_<term>: "yes"` (or `"no"` when reusing an existing positive `yesno`) or project `column: <term> { field: <view>.<term> }` (`sorts: [<view>.<term>: asc]`) alongside `column: count { field: <base_view>.count }` (for categorical/scalar terms, asserting per-row values via `index(${<view>.<term>}, 1) = "..." AND index(${<base_view>.count}, 1) = <N>` since `.test.lkml` `assert:` must return `yes` on every row)—or algebraic/structural invariants rather than `= <constant>` whenever the filter represents an open/mutable state (`sold_at IS NULL` / `is_sold: "no"`).
- **Silver (`tests/silver/:explore.test.lkml`):** Test **strictly** Silver joins, `silver/*_fields.view.lkml` dimensions/metrics, and Silver NDT/SDT views, grouped by join-path branch. **Skip `tests/silver/` entirely on single-table explores.**
- **Incremental across PRs, grouped within a PR:** Group sibling metrics *introduced in the current PR on the same filter slice* into **one** new `test: <table>_<slice>_metrics` block with multiple `column:` and `assert:` statements—**never modify, re-run, or copy numbers from already-committed `test:` blocks** from prior PRs (synthetic public datasets like `thelook_ecommerce` periodically regenerate historical row counts, and CI runs only newly added/edited `test:` blocks via `diff_lookml_tests.py`). Pass only the new `test_names` / `file_ids` to `validate_and_commit_branch.py`.
- **Explicit standalone `include:`s & model glob:** Every `.explore.lkml` and `.test.lkml` must explicitly `include:` its referenced `.view.lkml` / `.refinement.lkml` / `.explore.lkml` files, and `project.model.lkml` must include `/tests/**/*.test.lkml`.

### State-machine immutability & rounding in assertions
- **Terminal / append-only states** (e.g., `created_date: "2024-01-01"` on append-only events/items, `is_sold: "yes"` anchored on past `sold_date`, settled `Complete` orders): Assert deterministic rounded equality (`expression: round(${view.measure}, 2) = 4520.25 ;;`, `round(${view.measure}, 3) = ...` for `decimal_3`, or `round(${view.measure}, 4) = 0.3467 ;;` for unscaled `percent_2` `[0, 1]` ratios; see [looker-expressions](../looker-expressions/SKILL.md)) using raw unformatted values from `.test_query_results`.
- **Never write unfiltered whole-table `= <constant>` assertions:** Every equality `test:` MUST filter `explore_source:` on a bounded historical cohort/date (or timeless catalog PK) slice; unfiltered table-wide tests break whenever warehouse tables append or regenerate rows and may only assert structural invariants (`>= 0`, `between(0, 1)`).
- **Open / mutable states** (e.g., `is_sold: "no"` / `sold_at IS NULL`, 0-order dormant cohorts `orders.order_id IS NULL`, `Processing` orders, active carts, or cumulative lifetime entity NDT buckets like `user_spend_facts` / `product_sales_facts` even when sliced by `id: "<=1000"`): Filtering by historical `created_date` or entity `id` does **not** freeze open/lifetime states because rows can transition or accumulate future orders later. **Never** write frozen `= <constant>` assertions on open-state metrics; rely on `pre_gate.py` parity and, if a `test:` is needed, assert structural or algebraic invariants (`${inventory_items.sunk_dusty_shelf_cost} >= 0`, `${orders_users_fields.ghost_users} = ${users.count} - ${orders.distinct_users}`, `${user_spend_facts.avg_customer_ltv} >= 300`).

```lookml
# In tests/bronze/order_items.test.lkml (point include at ../../silver/explores/order_items.explore.lkml once detached)
include: "../../bronze/explores/order_items.explore.lkml"

test: order_items_2024_01_01_metrics {
  explore_source: order_items {
    column: total_sale_price { field: order_items.total_sale_price }
    column: order_item_count { field: order_items.count }
    filters: {
      field: order_items.created_date
      value: "2024-01-01"
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
