# Nested CTEs and pass-through subqueries (`nested_ctes_and_subqueries`)

This category (`nested_ctes_and_subqueries`) flattens pass-through CTEs and subqueries into `bronze/:table.refinement.lkml` and `silver/explores/:name.explore.lkml`, eliminating unnecessary derived tables. Changes use Tier 2 batch confirmation.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `nested_ctes_and_subqueries` when `parsed_query.ctes` and `queries[].explore_queries` satisfy both conditions:

- `len(parsed_query.ctes) >= 1` or the query contains a subquery in `FROM`, `JOIN`, or `WHERE`.
- At least one CTE (`ctes[].sql`) performs row-level filtering (`WHERE`), column renaming, scalar math or expressions, or standard `PK = FK` joins without changing the grain required by a second-stage aggregation or window function. Single-table CTE references resolve into `parsed_query.tables` and `parsed_query.joins`, allowing `queries[].explore_queries` to match flattened queries against existing Explore `query:` Quick Start blocks.

## Representative SQL

```sql
WITH active_users AS (
  SELECT id AS user_id, country, created_at
  FROM `project.dataset.users`
  WHERE is_deleted = FALSE
),
clean_orders AS (
  SELECT
    order_id,
    user_id,
    sale_price * (1 - COALESCE(discount_pct, 0)) AS net_price,
    created_at
  FROM `project.dataset.orders`
  WHERE status != 'Cancelled'
),
joined_data AS (
  SELECT
    o.order_id,
    o.net_price,
    u.country
  FROM clean_orders AS o
  INNER JOIN active_users AS u ON o.user_id = u.user_id
)
SELECT
  country,
  COUNT(DISTINCT order_id) AS order_count,
  SUM(net_price) AS total_net_revenue
FROM joined_data
GROUP BY 1
```

## Impact of naive translation

1. Wrapping a 3-CTE query into a SQL Derived Table duplicates base-table column logic (`net_price`, `is_deleted = FALSE`) inside raw SQL instead of reusing Bronze views.
2. Every time a base column changes, hardcoded CTE SQL breaks silently and bypasses Looker's lineage graph.

## How to handle (Canonical Looker Query translation gate)

Before writing any derived table (NDT or SDT), run the Canonical Looker Query translation gate ([How Looker Generates SQL](https://docs.cloud.google.com/looker/docs/how-looker-generates-sql)). Deconstruct CTEs from bottom to top. If all CTEs perform pass-through column projections, row filtering, scalar expressions, or standard `PK = FK` joins without changing grain, the query translates directly into a Canonical Looker Explore Query (`SELECT <dims>, <agg_measures> FROM <base> LEFT JOIN <joins> WHERE <filters> GROUP BY <dims> HAVING <measure_filters> ORDER BY ... LIMIT ...`).

| CTE type | AST signature | Resolution |
| :--- | :--- | :--- |
| Pass-through projection, rename, or row filter CTE (`active_users`, `clean_orders`) | No `GROUP BY`, no window function, no `UNION` | Delete the CTE. Move single-table scalar expressions (`net_price`) to `bronze/:table.refinement.lkml` as dimensions (or cross-view expressions to `silver/:view_a_:view_b_fields.view.lkml` bare-joined into the Explore), and apply `WHERE` conditions as Explore or measure filters. |
| Pass-through join CTE (`joined_data`) | Joins tables or CTEs without aggregating or changing grain | Delete the CTE. Express the `PK = FK` joins directly in `silver/explores/:name.explore.lkml`. |
| Semi-join or anti-join filter (`WHERE id IN (SELECT ...)` or `EXISTS`) | Subquery in `WHERE` filtering by existence in another table | Express as a join in `silver/explores/` and filter on `${joined_view.pk} IS NOT NULL` (for `EXISTS` or `IN`) or `IS NULL` (for `NOT EXISTS`). |
| Grain-changing aggregation CTE | Has `GROUP BY` and its aggregated output is grouped or filtered again downstream | Delegate to `measure_of_measures_reaggregation` and build a Silver NDT. |
| Window function CTE | Has `OVER (...)` or `QUALIFY` | Delegate to `window_functions_and_qualify`. |

## LookML template (Canonical Looker Query with zero derived tables)

By refining `bronze/orders.refinement.lkml` with `net_price` and `total_net_revenue`, the entire 3-CTE query translates into a standard Looker Explore `query:` Quick Start (matched by `queries[].explore_queries`) and a Looker `WriteQuery` or `run_inline_query` payload with zero derived tables:

### LookML refinement and Silver Explore Quick Start

```lookml
# File: bronze/orders.refinement.lkml (Single-table dimensions & measures - no joins required)
include: "orders.view.lkml"

view: +orders {
  dimension: net_price {
    type: number
    sql: ${sale_price} * (1 - COALESCE(${discount_pct}, 0)) ;;
    value_format_name: usd
  }

  measure: total_net_revenue {
    type: sum
    sql: ${net_price} ;;
    filters: [status: "-Cancelled"]
    value_format_name: usd
  }
}
```

```lookml
# File: silver/explores/orders.explore.lkml
include: "/bronze/orders.refinement.lkml"
include: "/bronze/users.refinement.lkml"

explore: orders {
  view_name: orders

  join: users {
    type: left_outer
    relationship: many_to_one
    sql_on: ${orders.user_id} = ${users.id} ;;
  }

  query: net_revenue_by_country {
    description: "Flattened 3-CTE query rendered as a zero-derived-table Explore Quick Start"
    dimensions: [users.country]
    measures: [orders.order_count, orders.total_net_revenue]
    filters: [
      orders.status: "-Cancelled",
      users.is_deleted: "no"
    ]
    sorts: [orders.total_net_revenue: desc]
    limit: 500
  }
}
```

### Canonical Looker `WriteQuery` / MCP `run_inline_query` payload

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
  "limit": "500"
}
```

## Architecture rules

Before creating any Silver NDT or Gold SDT, test every multi-CTE query against the Canonical Looker Query shape. Pass-through projection, filter, and `PK = FK` join CTEs are always deleted and expressed as Bronze refinements, Silver `_fields` views (for cross-view expressions), Silver Explore joins, and `query:` Quick Starts. Looker's `explore: { query: {} }` Quick Start syntax only supports modeled `dimensions`, `measures`, `filters`, `pivots`, `subtotals`, `limit`, `sorts`, `timezone`, and `description`; Table Calculations and Custom Fields cannot be placed inside an `explore: { query: {} }` block.
