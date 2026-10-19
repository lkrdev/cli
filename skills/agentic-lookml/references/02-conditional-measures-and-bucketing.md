# Conditional measures, bucketing, and ratios (`conditional_measures_and_bucketing`)

This category (`conditional_measures_and_bucketing`) routes ad-hoc or single-query calculations to the Query Layer (Custom Measure, Custom Dimension, or Table Calculation), reusable single-table dimensions and measures to `bronze/:table.refinement.lkml`, and any dimension or measure whose dependency DAG spans multiple views to a dedicated `silver/:view_a_:view_b_fields.view.lkml` view that is bare-joined (`sql: ;;`) into the Explore. These changes use Tier 2 batch confirmation to decide between Query Layer placement and Bronze or Silver LookML promotion.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `conditional_measures_and_bucketing` when any projection (`col` in `parsed_query.columns`) contains one of the following structures:

- `col.is_agg == True` and `col.sql` wraps `CASE`, `IF`, or `COUNTIF` (for example, `SUM(CASE WHEN status = 'Complete' THEN amount END)` or `COUNTIF(...)`).
- `col.is_agg == False` and `col.sql` contains `CASE` or `IF` for row-level bucketing.
- `col.is_agg == True` and `col.sql` contains arithmetic (`/` or `SAFE_DIVIDE`, `-`, `+`, `*`) combining two or more aggregate expressions (for example, `SUM(rev) / NULLIF(COUNT(DISTINCT id), 0)`).

## Representative SQL

```sql
SELECT
  DATE(created_at) AS created_date,
  CASE
    WHEN age < 25 THEN 'Gen Z'
    WHEN age BETWEEN 25 AND 40 THEN 'Millennial'
    ELSE '40+'
  END AS age_bucket,
  COUNT(CASE WHEN country = 'US' THEN order_id END) AS us_orders,
  COUNT(CASE WHEN country = 'UK' THEN order_id END) AS uk_orders,
  SUM(CASE WHEN status = 'Complete' THEN sale_price ELSE 0 END) AS completed_revenue,
  SUM(sale_price) / NULLIF(COUNT(DISTINCT order_id), 0) AS aov
FROM `project.dataset.orders`
GROUP BY 1, 2
```

## Impact of naive translation

1. Turning every `COUNT(CASE WHEN country = 'US' ...)` into a permanent LookML measure causes an $N \times M$ measure explosion that bloats the Explore field picker.
2. Putting cross-view dimensions or measures in Bronze (or inside a single table's view refinement) breaks layer boundaries and view portability. Bronze can hold dimensions and measures only when their entire dependency DAG references that single table; any field whose DAG references multiple views belongs in `silver/:view_a_:view_b_fields.view.lkml` and is bare-joined into the Explore.
3. Writing `sql: SUM(CASE WHEN ${status} = 'Complete' THEN ${sale_price} END) ;;` with `type: number` breaks Looker symmetric aggregates when the view is joined.

## How to handle (triage matrix)

The easiest way to author a Custom Measure in the Query or Dashboard Layer is using [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) or Looker's [`matches_filter` syntax](https://docs.cloud.google.com/looker/docs/matches-filter) (`matches_filter(${view.field}, \`filter_expression\`)`). Note that Custom Fields (`custom_fields`) and Table Calculations (`table_calculations`) live in the Looker API query payload (`dynamic_fields`), Saved Looks, or LookML Dashboards (`.dashboard.lookml`), and cannot be placed inside an `explore: { query: {} }` Quick Start block.

| Sub-pattern | Condition | Resolution | Target location |
| :--- | :--- | :--- | :--- |
| Universal slice | Every metric in the query has the same `CASE WHEN X` | Strip from measure; use base measure (`total_revenue`) + runtime filter on `X` | Query / Dashboard Filter |
| Infrequent filtered metric | Side-by-side comparison for one report (`us_orders` vs. `uk_orders`) | Keep as Custom Measure (`custom_fields`) using [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) or [`matches_filter(${orders.country}, \`US\`)`](https://docs.cloud.google.com/looker/docs/matches-filter) | Query / Dashboard Layer |
| Canonical single-table filtered KPI | Core business definition on 1 table (`completed_revenue`, `billable_hours`) | Declarative LookML Measure with `filters: [status: "Complete"]` (never `CASE WHEN` in `sql:`) | `bronze/:table.refinement.lkml` |
| Compound cross-column `OR` filtered KPI | Measure filters with `OR` across two columns (`status = 'Complete' OR is_override = TRUE`) | For ad-hoc or single-report use, keep as a Custom Measure (`matches_filter(${orders.status}, \`Complete\`) OR ${orders.is_override}`) or Custom Dimension. For a canonical single-table KPI, define a hidden `type: yesno` helper dimension (`is_completed_or_override`) and filter the measure on `filters: [is_completed_or_override: "yes"]` | Query / Dashboard Layer or `bronze/:table.refinement.lkml` |
| Cross-view dimension or measure (`gross_margin`, `total_gross_margin`) | Dimension or measure whose dependency DAG references multiple joined views (`${order_items.sale_price} - ${inventory_items.cost}` or filtered metric across views) | Move all fields in that cross-view DAG into an alphabetically named Silver `_fields` view (`silver/inventory_items_order_items_fields.view.lkml`) and bare-join (`sql: ;;`, `relationship: one_to_one`) into the Explore | `silver/:view_a_:view_b_fields.view.lkml` + `silver/explores/` |
| One-off bucketing | Ad-hoc campaign/report `CASE WHEN` | Keep as Custom Dimension (`custom_fields`) | Query / Dashboard Layer |
| Reusable simple dimension | Standard tiers, flags, or durations (`age_tier`, `is_enterprise`, `fulfillment_days`) | Native LookML `type: tier`, `type: yesno`, `type: duration`, or `case:` | `bronze/:table.refinement.lkml` |
| One-off display ratio | Visual math between two columns on one chart (`us_orders / uk_orders`) | Keep as Table Calculation (`${us_orders} / nullif(${uk_orders}, 0)`) | Query / Dashboard Layer |
| Single-table ratio | Canonical ratio within 1 table (`aov = total_rev / order_cnt`) | LookML `measure` (`type: number`, `sql: 1.0 * ${num} / NULLIF(${den}, 0) ;;`) | `bronze/:table.refinement.lkml` |
| Cross-table ratio | Canonical ratio across joined tables (`rev_per_user = order_items.total_revenue / users.count`) | LookML `measure` in an alphabetically named Silver `_fields` view (`silver/order_items_users_fields.view.lkml`), bare-joined (`sql: ;;`) into the Explore | `silver/:view_a_:view_b_fields.view.lkml` + `silver/explores/` |

## LookML templates

### Single-table dimensions and measures in Bronze refinement

```lookml
# File: bronze/orders.refinement.lkml (Single-table dimensions & measures - entire DAG stays within orders)
include: "orders.view.lkml"

view: +orders {
  dimension: age_tier {
    type: tier
    tiers: [25, 41]
    style: integer
    sql: ${age} ;;
  }

  dimension: is_completed_or_override {
    type: yesno
    hidden: yes
    sql: ${status} = 'Complete' OR ${is_override} ;;
  }

  measure: order_count {
    type: count_distinct
    sql: ${order_id} ;;
    value_format_name: decimal_0
  }

  measure: total_revenue {
    type: sum
    sql: ${sale_price} ;;
    value_format_name: usd
  }

  measure: completed_revenue {
    type: sum
    sql: ${sale_price} ;;
    filters: [status: "Complete"]
    value_format_name: usd
  }

  measure: recognized_revenue {
    type: sum
    sql: ${sale_price} ;;
    filters: [is_completed_or_override: "yes"]
    value_format_name: usd
  }

  measure: average_order_value {
    type: number
    sql: 1.0 * ${total_revenue} / NULLIF(${order_count}, 0) ;;
    value_format_name: usd
  }
}
```

### Cross-view DAG dimensions and measures in Silver (`*_fields.view.lkml` + bare join)

```lookml
# File: silver/inventory_items_order_items_fields.view.lkml
# (Alphabetically concatenated view names + _fields for any dimension/measure whose DAG spans inventory_items and order_items)
view: inventory_items_order_items_fields {
  dimension: gross_margin {
    type: number
    sql: ${order_items.sale_price} - ${inventory_items.cost} ;;
    value_format_name: usd
  }

  measure: total_gross_margin {
    type: sum
    sql: ${gross_margin} ;;
    value_format_name: usd
  }
}
```

```lookml
# File: silver/explores/order_items.explore.lkml
include: "/bronze/order_items.refinement.lkml"
include: "/bronze/inventory_items.refinement.lkml"
include: "/silver/inventory_items_order_items_fields.view.lkml"

explore: order_items {
  view_name: order_items

  join: inventory_items {
    type: left_outer
    relationship: many_to_one
    sql_on: ${order_items.inventory_item_id} = ${inventory_items.id} ;;
  }

  join: inventory_items_order_items_fields {
    view_label: "Order Items"
    sql: ;;
    relationship: one_to_one
  }
}
```

## Architecture rules

Single-table dimensions and measures whose entire dependency DAG stays within a single table live in `bronze/:table.refinement.lkml`. Any dimension or measure that anywhere in its dependency DAG references different views belongs in its own Silver view named alphabetically with `_fields` (`silver/:view_a_:view_b_fields.view.lkml`) and is bare-joined (`sql: ;;`, `relationship: one_to_one`) into the Explore that joins those views.

For ad-hoc filtered measures or cross-column `OR` conditions in a single report, use Custom Measures (`custom_fields`) with [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions) and [`matches_filter`](https://docs.cloud.google.com/looker/docs/matches-filter) (`matches_filter(${orders.status}, \`Complete\`) OR ${orders.is_override}`) or Custom Dimensions. Because Looker's declarative `filters:` property on a LookML `measure:` combines multiple field filters with `AND`, canonical LookML measures requiring an `OR` condition across multiple columns must define a `hidden: yes`, `type: yesno` helper dimension and filter the measure via `filters: [helper_dim: "yes"]`.

When analyzing a batch of SQL queries via `lkr parse sql-lookml-compare`, conditional measures or `CASE WHEN` dimensions appearing in two or more queries (or marked as reusable domain KPIs) should be promoted to `bronze/:table.refinement.lkml` (single-table DAG) or `silver/:view_a_:view_b_fields.view.lkml` (multi-view DAG), while single-query ad-hoc slices remain in the Query or Dashboard Layer (`Table Calculation`, `Custom Measure`, or `Custom Dimension`).
