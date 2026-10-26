# Measure of measures and re-aggregation (`measure_of_measures_reaggregation`)

This category (`measure_of_measures_reaggregation`) models two-stage aggregations using `bronze/explores/:source.explore.lkml` (`hidden: yes`, when needed), consolidated entity-fact Native Derived Tables in `silver/:entity_facts.view.lkml` (`explore_source:`), and fact-anchored `silver/explores/:name.explore.lkml` files (or `gold/` when `bind_all_filters: yes` is required). These patterns require Tier 3 planning.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `measure_of_measures_reaggregation` when recursive AST inspection of `parsed_query.ctes` or inline subqueries finds a CTE or subquery containing `GROUP BY` and aggregate functions (`SUM`, `COUNT`, `MIN`, `MAX`, `AVG`), and an outer query or downstream CTE references that aggregated column inside any of the following constructs:

- Another aggregate function (`AVG(user_total_spend)`, `SUM(order_profit)`).
- A `GROUP BY` dimension or `CASE WHEN` tier (`CASE WHEN lifetime_orders >= 5 THEN 'VIP' ...`).
- A `WHERE` or `HAVING` filter combined with outer aggregations.

## Representative SQL

```sql
WITH user_order_stats AS (
  SELECT
    user_id,
    COUNT(DISTINCT order_id) AS lifetime_orders,
    SUM(sale_price) AS lifetime_spend,
    MIN(created_at) AS first_order_at
  FROM `project.dataset.orders`
  GROUP BY user_id
)
SELECT
  CASE
    WHEN lifetime_orders = 1 THEN '1. One-Time'
    WHEN lifetime_orders BETWEEN 2 AND 4 THEN '2. Repeat'
    ELSE '3. VIP (5+)'
  END AS customer_frequency_tier,
  COUNT(DISTINCT user_id) AS customer_count,
  AVG(lifetime_spend) AS avg_customer_ltv
FROM user_order_stats
GROUP BY 1
```

## Impact of naive translation

1. Putting `AVG(SUM(sale_price))` inside a single LookML measure fails in SQL (`Aggregate function calls cannot be nested`).
2. Writing a raw `derived_table: { sql: SELECT user_id, SUM(sale_price) ... ;; }` bypasses LookML measure definitions in `bronze/orders.refinement.lkml`.

## How to handle

### Run the Canonical Looker Query translation gate first

If the outer query only averages or totals rows that are already displayed at the inner `GROUP BY` grain in the visualization (for example, `AVG(daily_revenue)` on a daily chart), express the base dimensions and measures as a standard Silver Explore `query:` Quick Start and apply the Table Calculation (`mean(${orders.total_revenue})`, see [looker-expressions](../../looker-expressions/SKILL.md)) in the Query or Dashboard Layer (`run_inline_query` / `create_query` `body` or dashboard element, never inside the `explore: { query: {} }` block) with zero derived tables.

### Prefer a consolidated Silver Native Derived Table (`explore_source:`)

When the outer query groups by a bucketed tier of the Stage-1 metric (`customer_frequency_tier`) or aggregates across an entity grain not displayed in the chart, create `silver/:entity_facts.view.lkml` (such as `silver/user_order_facts.view.lkml`) using `explore_source:`. Detach the base explore to `bronze/explores/orders_base.explore.lkml` (`hidden: yes` — **never** `extension: required`, which Looker rejects in `explore_source:`) and point `explore_source: orders_base` at it so joining `user_order_facts` into `silver/explores/orders.explore.lkml` (`extends: [orders_base]`) stays strictly acyclic (zero circular `include:` cycles). Consolidate multiple `GROUP BY user_id` aggregations from different queries into a single, cohesive `silver/user_order_facts.view.lkml` rather than creating separate one-off NDT views.

### Keep Silver NDTs ephemeral by default

Silver NDTs remain ephemeral (inlined CTE or subquery at query runtime) by default so the warehouse optimizer can push outer predicates down. Do not add `datagroup_trigger:`, `publish_as_db_view:`, or table persistence up-front; save persistence optimization for a later tuning pass when query latency benchmarks prove it is needed.

### Promote Stage-1 metrics to dimensions (or symmetric cohort measures) and join back on `PK = FK`

Inside `silver/user_order_facts.view.lkml`, `lifetime_orders` and `lifetime_spend` become dimensions (`primary_key: yes` on `user_id`, which automatically triggers Looker symmetric `COUNT(DISTINCT user_id)` and `average_distinct` across `many_to_one` joins). When Stage 1 aggregates a **coarser cohort/segment denominator** (`GROUP BY cohort_signup_year` joined `many_to_one` to finer `(cohort_signup_year, years_since_signup)` activity rows), declare `primary_key: yes` on the cohort key (`cohort_signup_year`), keep the Stage-1 count/sum dimension `hidden: yes` (`cohort_user_count`), and expose a symmetric `type: sum` measure (`initial_cohort_users { type: sum sql: ${cohort_user_count} ;; }`) so cross-view `type: number` ratios and `test:` blocks never hit SQL `GROUP BY` errors. For intra-group timestamp spans like `TIMESTAMP_DIFF(MAX(created_at), MIN(created_at), SECOND)`, define a `hidden: yes` Stage-1 `type: number` measure `TIMESTAMP_DIFF(MAX(${created_raw}), MIN(${created_raw}), SECOND)` on the base refinement (avoiding BigQuery `type: date_time` `FORMAT_TIMESTAMP` strings and `UNIX_SECONDS` sub-second drift). Define `customer_frequency_tier` (`type: tier`) and Stage-2 measures (`avg_customer_ltv { type: average sql: ${lifetime_spend} ;; }`) on `silver/user_order_facts.view.lkml`.

Join `user_order_facts` into `silver/explores/orders.explore.lkml` (`${orders.user_id} = ${user_order_facts.user_id}`, `relationship: many_to_one`, or `${users.id} = ${user_order_facts.user_id}`, `relationship: one_to_one`). Reuse an existing entity Silver Explore (`silver/explores/users.explore.lkml`) when queries combine all-entity registration/cohort denominators with child activity (`order_items`); never bare-join an entity-Explore `*_fields` view referencing `${entity.count}` onto a child fact Explore where `${entity.count}` drops 0-activity entities. When an NDT aggregates at a non-table-PK cohort/session grain with `HAVING` (`GROUP BY session_id HAVING COUNTIF(...) > 0`), filter the measure inside `explore_source: { filters: [events.purchase_count: ">0"] }`, declare `primary_key: yes` (without `hidden: yes` when outer queries filter `<ndt>.<pk>: "-NULL"` / `"NOT NULL"`) plus `measure: count { type: count }`, and join `many_to_one`.

### Distinguish static entity grain from dynamic dashboard-filtered grain

Static lifetime facts that do not depend on dashboard date filters belong in Silver (`silver/user_order_facts.view.lkml`, without `bind_all_filters`). Period-filtered facts that must recalculate `user_spend` within the user's selected dashboard date range belong in Gold (`gold/user_period_facts.view.lkml` with `bind_all_filters: yes`, joined into `gold/explores/` with `tags: ["gold"]` and `always_filter:`).

## LookML template

```lookml
# File: silver/user_order_facts.view.lkml
include: "/bronze/explores/orders_base.explore.lkml"

view: user_order_facts {
  derived_table: {
    explore_source: orders_base {
      column: user_id {}
      column: lifetime_orders { field: orders.count }
      column: lifetime_spend { field: orders.total_revenue }
      column: first_order_date { field: orders.min_created_date }
    }
  }

  dimension: user_id {
    primary_key: yes
    hidden: yes # Omit hidden: yes when outer queries filter <ndt>.<pk>: "-NULL" / "NOT NULL"
    type: number
  }

  measure: count {
    type: count
  }

  dimension: lifetime_orders {
    type: number
  }

  dimension: customer_frequency_tier {
    type: tier
    tiers: [1, 2, 5]
    style: integer
    sql: ${lifetime_orders} ;;
  }

  dimension: lifetime_spend {
    type: number
    value_format_name: usd
  }

  measure: avg_customer_ltv {
    type: average
    sql: ${lifetime_spend} ;;
    value_format_name: usd
  }
}
```
