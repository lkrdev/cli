# Window functions and `QUALIFY` (`window_functions_and_qualify`)

This category (`window_functions_and_qualify`) routes window functions and `QUALIFY` clauses across three layers depending on when the window executes: the Query Layer (Table Calculations paired with Quick Start `query:` blocks), `silver/:name.view.lkml` (post-`GROUP BY` NDT `derived_column:`, pre-`GROUP BY` `extends: [base_view]` SDTs using `${EXTENDED}`, or single-table CDC `QUALIFY` SDTs), and `gold/:name.view.lkml` (`bind_all_filters: yes` NDTs or multi-table `AS OF` `QUALIFY` SDTs). Table Calculation versus Silver NDT routing uses Tier 2 batch confirmation, while Gold dynamic window NDTs require Tier 3 planning.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `window_functions_and_qualify` when the AST (`columns[].sql` or `ctes[].sql`) contains either construct:

- Any window expression (`OVER (PARTITION BY ... ORDER BY ...)`): `ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`, `LAG()`, `LEAD()`, `FIRST_VALUE()`, `LAST_VALUE()`, `SUM(...) OVER (...)`, or `AVG(...) OVER (...)`.
- A `QUALIFY` clause (`QUALIFY ROW_NUMBER() OVER (...) = 1`) or an outer `WHERE rn = 1` over a windowed CTE.

## Representative SQL

```sql
-- Archetype 8A: Post-Aggregation Share of Total & Period-over-Period
SELECT
  DATE_TRUNC(created_at, MONTH) AS order_month,
  SUM(sale_price) AS monthly_revenue,
  SUM(sale_price) / SUM(SUM(sale_price)) OVER () AS pct_of_total,
  LAG(SUM(sale_price)) OVER (ORDER BY DATE_TRUNC(created_at, MONTH)) AS prev_month_revenue
FROM `project.dataset.orders`
GROUP BY 1;

-- Archetype 8B: Entity-Grain Sequencing (Order Sequence Number & Days Since Prior Order)
SELECT
  order_id,
  user_id,
  ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at) AS user_order_sequence,
  DATE_DIFF(
    DATE(created_at),
    DATE(LAG(created_at) OVER (PARTITION BY user_id ORDER BY created_at)),
    DAY
  ) AS days_since_prior_order
FROM `project.dataset.orders`;
```

## Impact of naive translation

1. Putting `ROW_NUMBER() OVER (...)` or `LAG(...) OVER (...)` directly inside a LookML `dimension` or `measure` causes `GROUP BY` SQL errors as soon as a user selects different dimensions in the Explore.
2. Writing raw `derived_table: { sql: ... ;; }` for post-aggregation window functions duplicates SQL when LookML `explore_source:` natively supports `derived_column:` window functions.

## How to handle (window routing and execution timing)

### Determine when the window executes

In LookML Native Derived Tables (`explore_source:`), `derived_column:` runs after the query's `GROUP BY` clause. Use `derived_column:` when the window function operates on aggregated measures, such as ranking entities by total spend or computing percent of total across aggregated groups.

When a window function must execute on un-aggregated, row-level records before any grouping occurs (such as calculating the delta between consecutive raw event timestamps, event sessionization, or row-by-row sequencing), you have two options:

1. If you only need a subset of columns in an NDT (`explore_source:`) and want `derived_column:` to run over raw un-grouped rows without pulling a primary key into the projection, bare-join `bronze/common_helpers.view.lkml` (`join: common_helpers { sql: ;; relationship: one_to_one }`) into the Explore with `cancel_grouping_fields: [common_helpers.no_group]` and include `column: _no_group { field: common_helpers.no_group }` in the NDT. Looker omits the inner `GROUP BY` clause completely while projecting only `1 AS _no_group`.
2. If you want to retain all 50+ base columns and inherited dimensions/measures from a Bronze view, create a derived view using `extends: [base_view]` with a SQL derived table referencing `FROM (${EXTENDED}) AS {{ _table }}` (or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`) and `SELECT {{ _table }}.*, ...` with `{{ field._sql }}`. Never alias `FROM ${EXTENDED} AS base_view` when selecting `${EXTENDED}.*`, because aliasing the subquery invalidates the `${EXTENDED}.*` qualifier in BigQuery.

When running totals, percent of total, or period-over-period differences belong at the query layer (Table Calculations; see [looker-expressions](../../looker-expressions/SKILL.md)), pre-populate the underlying modeled dimensions, measures, filters, and sorts in a named `query:` Quick Start block on the Silver Explore (`silver/explores/:name.explore.lkml`), and define the Table Calculations (`running_total()`, `offset()`) in the Query or Dashboard Layer (`dynamic_fields` — never inside `explore: { query: {} }`).

### Routing decision tree

| Window archetype | Execution point | Target layer and LookML mechanism |
| :--- | :--- | :--- |
| Display window / running total (`SUM(x) / SUM(SUM(x)) OVER ()`, running totals, `LAG(SUM(x))`, or post-`GROUP BY` partitioned `RANK() OVER (PARTITION BY d ORDER BY m DESC)` when rows sort by `d asc, m desc` and `LIMIT` does not truncate prior window rows) | Post-aggregation display | Query Layer (Table Calculation in `WriteQuery` / dashboard, e.g. tie-safe partitioned `RANK()`: `match(concat(${v.d}, "|", to_string(${v.m})), concat(${v.d}, "|", to_string(${v.m}))) - match(${v.d}, ${v.d}) + 1`) + Quick Start `query:` on `silver/explores/:name.explore.lkml`. **Exceptions (route to post-`GROUP BY` Silver NDT `derived_column:`):** (1) any window (`UNBOUNDED PRECEDING`, `LAG`, `N PRECEDING`, or grand-total `SUM(m) OVER ()`) computed across all groups *before* `LIMIT K` truncates rows, and (2) partitioned aggregate windows (`SUM/AVG(m) OVER (PARTITION BY d)`, exposed via `type: max` measure on the NDT). |
| Aggregated entity ranking (`RANK() OVER (ORDER BY SUM(sale_price) DESC)`) | Post-`GROUP BY` | Silver NDT (`explore_source:`): `derived_column:` executes after `GROUP BY` (keep `column:`/`derived_column:` names 1:1 with exposed `dimension:` names). Join back on `PK = FK` (do **not** co-locate an unpartitioned `OVER (ORDER BY m)` `derived_column:` in an existing NDT that already defines `OVER (PARTITION BY dim ORDER BY ...)`, as `dim` sorting alters tie-breaking on tied `m`—use a sibling NDT; BigQuery also forbids referencing an analytic `derived_column:` like `MAX(x) OVER ()` inside another window's `ORDER BY`, so split into a 2-stage NDT with `cancel_grouping_fields: [common_helpers.no_group]` on Stage 2). |
| Raw event sequencing / timestamp deltas (`LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time)`) | Pre-`GROUP BY` (raw row grain) | Silver Derived View (`extends: [base_view]`): PDT-safe SDT using `SELECT {{ _table }}.*, LAG({{ event_raw._sql }}) OVER (...) FROM (${EXTENDED}) AS {{ _table }}` (or `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}`) keeping raw grain and all inherited fields. |
| Dynamic filter-dependent ranking ("Top 10 within selected dashboard date/region filters") | Runtime filter-dependent | Gold NDT (`gold/:name.view.lkml`): `explore_source:` + `derived_column:` + `bind_all_filters: yes`, exposed in Gold Explore (`extends: [silver]`, `view_name: :base`, `tags: ["gold"]`, `always_filter:`). |
| CDC ingestion deduplication (`QUALIFY ROW_NUMBER() ... = 1`) | Ingestion row level | Silver SDT (`extends: [bronze_view]`): `SELECT * FROM ${bronze_view.SQL_TABLE_NAME} AS {{ _table }} QUALIFY ROW_NUMBER() OVER (PARTITION BY {{ pk._sql }} ORDER BY {{ updated_raw._sql }} DESC) = 1`. (Multi-table `AS OF` inequality `QUALIFY` belongs in Gold per Category 04.) |

## LookML templates

### Quick Start Explore query paired with Query-Layer Table Calculations (`silver/explores/orders.explore.lkml`)

```lookml
# File: silver/explores/orders.explore.lkml
explore: orders {
  view_name: orders

  # Quick Start Query pre-populates modeled dimensions, measures, and sorts
  # (Table Calculations and Custom Fields live in the Looker query payload or dashboard, never inside explore: { query: {} })
  query: monthly_sales_running_total {
    description: "Monthly revenue base query for running total and prior month comparison"
    dimensions: [orders.created_month]
    measures: [orders.total_revenue]
    sorts: [orders.created_month: asc]
  }
}
```

### Silver NDT with `derived_column:` (post-`GROUP BY`)

```lookml
# File: silver/user_spending_rank.view.lkml
include: "/bronze/explores/orders_base.explore.lkml"

view: user_spending_rank {
  derived_table: {
    explore_source: orders_base {
      column: user_id {}
      column: total_revenue { field: orders.total_revenue }
      # derived_column runs AFTER group by total_revenue
      derived_column: spending_rank {
        sql: DENSE_RANK() OVER (ORDER BY total_revenue DESC) ;;
      }
    }
  }

  dimension: user_id {
    primary_key: yes
    hidden: yes
    type: number
  }

  dimension: spending_rank {
    type: number
  }
}
```

### Pre-`GROUP BY` row window via `(${EXTENDED}) AS {{ _table }}` and `{{ field._sql }}`

Using `FROM (${EXTENDED}) AS {{ _table }}` (or `FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}`) paired with `{{ field._sql }}` works both when extending a physical table and when extending another derived table, and is 100% PDT-safe (`forTableName = true`) without requiring a bare join on the outer Explore (see [lookml-advanced-liquid](../../lookml/sub-skills/lookml-advanced-liquid/SKILL.md)):

```lookml
# File: silver/order_items_sequenced.view.lkml
include: "/bronze/order_items.view.lkml"
include: "/bronze/order_items.refinement.lkml"

view: order_items_sequenced {
  extends: [order_items]

  derived_table: {
    sql:
      SELECT
        {{ _table }}.*,
        LAG({{ created_raw._sql }}) OVER (
          PARTITION BY {{ user_id._sql }}
          ORDER BY {{ created_raw._sql }} ASC
        ) AS prior_order_timestamp
      FROM (${EXTENDED}) AS {{ _table }} ;;
  }

  dimension_group: prior_order {
    type: time
    timeframes: [raw, time, date]
    sql: ${TABLE}.prior_order_timestamp ;;
  }
}
```

When an active Silver Explore (`silver/explores/order_items.explore.lkml`) already exposes the base entity, join the row-window SDT (ordered `ROW_NUMBER`/`LAG` or partition-only `MIN/MAX/AVG(...) OVER (PARTITION BY ...)`) back `1:1` on the row PK and whitelist only `[id, <new_window_fields>]` via `fields:` so inherited base columns are not duplicated—because `fields:` excludes inherited base fields on the SDT, place any dimensions or measures combining base and window fields in `silver/:base_:sdt_fields.view.lkml` (and if an existing session/entity NDT on that Explore also needs measures from the row-window SDT, join the SDT onto a `hidden: yes` intermediate `silver/explores/:table_steps_base.explore.lkml` extending `:table_base`, point the NDT's `explore_source:` at `:table_steps_base`, and extend `:table_steps_base` in `silver/explores/:table.explore.lkml` to stay acyclic):

```lookml
join: order_items_sequenced {
  type: left_outer
  relationship: one_to_one
  sql_on: ${order_items.id} = ${order_items_sequenced.id} ;;
  fields: [order_items_sequenced.id, order_items_sequenced.prior_order_raw, order_items_sequenced.prior_order_time, order_items_sequenced.prior_order_date]
}
```

## Architecture rules

Default year-over-year and month-over-month `LAG()` window comparisons over displayed rows to Table Calculations (`offset()`) in the Query or Dashboard Layer, paired with a Quick Start `query:` on the Silver Explore that pre-populates the base dimensions, measures, and sorts (zero derived tables). Native Looker `period_over_period` measures can be used when the target Looker instance version and dialect support them natively.
