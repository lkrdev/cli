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

When a window function must execute on un-aggregated, row-level records before any grouping occurs (such as calculating the delta between consecutive raw event timestamps, event sessionization, or row-by-row sequencing while retaining all 50+ base columns), an NDT grouping by columns can alter the grain or require enumerating every column. Instead, create a derived view using `extends: [base_view]` with a SQL derived table referencing `${EXTENDED}` (`SELECT ${EXTENDED}.*, ... FROM ${EXTENDED}`) to compute the row-level window expression over raw rows while inheriting all base dimensions and measures. Never alias `FROM ${EXTENDED} AS base_view` when selecting `${EXTENDED}.*`, because aliasing the subquery invalidates the `${EXTENDED}.*` qualifier in BigQuery.

When running totals, percent of total, or period-over-period differences belong at the query layer (Table Calculations), pre-populate the underlying modeled dimensions, measures, filters, and sorts in a named `query:` Quick Start block on the Silver Explore (`silver/explores/:name.explore.lkml`), and define the Table Calculations (`running_total()`, `offset()`) in the Query or Dashboard Layer (`dynamic_fields` on the Looker `WriteQuery` / `run_inline_query` payload, Saved Look, or `.dashboard.lookml` tile). Never place `table_calculations`, `custom_fields`, or `dynamic_fields` inside an `explore: { query: {} }` LookML block, because Looker's `explore: { query: {} }` syntax only accepts modeled `dimensions`, `measures`, `filters`, `pivots`, `subtotals`, `limit`, `sorts`, `timezone`, and `description`.

### Routing decision tree

| Window archetype | Execution point | Target layer and LookML mechanism |
| :--- | :--- | :--- |
| Display window / running total (`SUM(x) / SUM(SUM(x)) OVER ()`, running totals, `LAG(SUM(x))`) | Post-aggregation display | Query Layer (Table Calculation in `WriteQuery` / dashboard) + Quick Start `query:` for base fields on the Explore (`silver/explores/:name.explore.lkml`). Zero derived tables. |
| Aggregated entity ranking (`RANK() OVER (ORDER BY SUM(sale_price) DESC)`) | Post-`GROUP BY` | Silver NDT (`explore_source:`): `derived_column:` executes after `GROUP BY`. Join back on `PK = FK`. |
| Raw event sequencing / timestamp deltas (`LAG(event_time) OVER (PARTITION BY user_id ORDER BY event_time)`) | Pre-`GROUP BY` (raw row grain) | Silver Derived View (`extends: [base_view]`): SDT using `SELECT ${EXTENDED}.*, LAG(${base_view.event_raw}) OVER (...) FROM ${EXTENDED}` keeping raw grain and all inherited fields. |
| Dynamic filter-dependent ranking ("Top 10 within selected dashboard date/region filters") | Runtime filter-dependent | Gold NDT (`gold/:name.view.lkml`): `explore_source:` + `derived_column:` + `bind_all_filters: yes`, exposed in Gold Explore (`extends: [silver]`, `view_name: :base`, `tags: ["gold"]`, `always_filter:`). |
| CDC ingestion deduplication (`QUALIFY ROW_NUMBER() ... = 1`) | Ingestion row level | Silver SDT (`extends: [bronze_view]`): `SELECT * FROM ${bronze_view.SQL_TABLE_NAME} AS bronze_view QUALIFY ROW_NUMBER() OVER (PARTITION BY ${bronze_view.pk} ORDER BY ${bronze_view.updated_raw} DESC) = 1`. (Multi-table `AS OF` inequality `QUALIFY` belongs in Gold per Category 04.) |

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
include: "/silver/explores/orders.explore.lkml"

view: user_spending_rank {
  derived_table: {
    explore_source: orders {
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

### Pre-`GROUP BY` row window via `${EXTENDED}`

```lookml
# File: silver/order_items_sequenced.view.lkml
include: "/bronze/order_items.view.lkml"
include: "/bronze/order_items.refinement.lkml"

view: order_items_sequenced {
  extends: [order_items]

  derived_table: {
    sql:
      SELECT
        ${EXTENDED}.*,
        LAG(${order_items.created_raw}) OVER (
          PARTITION BY ${order_items.user_id}
          ORDER BY ${order_items.created_raw} ASC
        ) AS prior_order_timestamp
      FROM ${EXTENDED} ;;
  }

  dimension_group: prior_order {
    type: time
    timeframes: [raw, time, date]
    sql: ${TABLE}.prior_order_timestamp ;;
  }
}
```

## Architecture rules

Default year-over-year and month-over-month `LAG()` window comparisons over displayed rows to Table Calculations (`offset()`) in the Query or Dashboard Layer, paired with a Quick Start `query:` on the Silver Explore that pre-populates the base dimensions, measures, and sorts (zero derived tables). Native Looker `period_over_period` measures can be used when the target Looker instance version and dialect support them natively.
