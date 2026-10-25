# Standard foreign key joins (`pk_fk_joins`)

This category (`pk_fk_joins`) maps primary-key-to-foreign-key equality joins to `silver/explores/:base_view.explore.lkml` and places `primary_key: yes` definitions in `bronze/:table.refinement.lkml`. Changes qualify for Tier 1 auto-application once primary key uniqueness is verified via the Join Cardinality Audit SQL.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `pk_fk_joins` when `parsed_query.joins` and `queries[].join_analysis` meet all of these conditions:

- `len(parsed_query.joins) >= 1`.
- Each `join` has `join.equi_joins != []` and `join.non_equi_conditions == []` (equality comparisons `t1.fk = t2.pk`, optionally combined with static literal filter predicates).
- `join.join_type in ("INNER", "LEFT")` (or `join.side in ("", "LEFT")`).
- At least one side of `join.equi_joins` is a candidate primary or entity key (`id`, `*_id`, `uuid`, `code`, or a declared `primary_key: yes`), with `join_analysis[].inferred_relationship in ("many_to_one", "one_to_one", "one_to_many")`.

## Representative SQL

```sql
SELECT
  u.country,
  p.category,
  COUNT(DISTINCT o.order_id) AS order_count,
  SUM(oi.sale_price) AS gross_revenue
FROM `project.dataset.order_items` AS oi
LEFT JOIN `project.dataset.orders` AS o
  ON oi.order_id = o.order_id
LEFT JOIN `project.dataset.users` AS u
  ON o.user_id = u.id
LEFT JOIN `project.dataset.products` AS p
  ON oi.product_id = p.id
GROUP BY 1, 2
```

## Impact of naive translation

1. Omitting `primary_key: yes` on a joined view or defaulting `relationship:` to `many_to_one` when the join is actually `one_to_many` causes `SUM()` measures on the base table to multiply silently.
2. Using raw table names like `orders.user_id = users.id` in `sql_on:` instead of `${orders.user_id} = ${users.id}` breaks view aliasing (`from:`).

## How to handle

### Choose the finest-grain fact table as the Silver Explore base

Anchor `silver/explores/:base.explore.lkml` on the finest-grain transaction table (`order_items`), joining parent entities (`orders`, `users`, `products`, `calendar_dates`) outward via `many_to_one`. Inspect `queries[].join_analysis` for `status`, `relationship`, `inferred_relationship`, `safety_warnings`, and `precedents`. Always explicitly declare `view_name:` on the Explore.

### Ensure primary keys on the "one" side of joins (cardinality audit SQL)

While primary keys are not required for raw Bronze views operating without joins, a verified primary key is essential on the "one" side of any join as soon as a Bronze view is extended or joined into Silver or Gold. If the joined view lacks a verified `primary_key: yes`, run the cardinality audit via `lkr code-mode` (including a partition filter if the table is partitioned):

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNT(DISTINCT join_key) AS distinct_keys,
  COUNT(*) - COUNT(DISTINCT join_key) AS duplicate_rows
FROM `project.dataset.target_table`
WHERE _PARTITIONDATE >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) -- if partitioned
```

When `duplicate_rows == 0` on a single column, add `primary_key: yes` to the key dimension in `bronze/:target.refinement.lkml` (never hand-edit `bronze/:target.view.lkml`). When uniqueness requires multiple columns `(order_id, item_seq)`, add a hidden composite primary key to `bronze/:target.refinement.lkml`:

```lookml
dimension: pk {
  primary_key: yes
  hidden: yes
  type: string
  sql: CONCAT(CAST(${order_id} AS STRING), '_', CAST(${item_seq} AS STRING)) ;;
}
```

Map the audit results to the LookML `relationship:` parameter:

- When `duplicate_rows == 0` on the right table only, set `relationship: many_to_one`.
- When `duplicate_rows == 0` on both tables, set `relationship: one_to_one`.
- When `duplicate_rows > 0` on the right table and `0` on the left, set `relationship: one_to_many`.

### Default `INNER JOIN` to `LEFT JOIN` (`"NOT NULL"` and `"NULL"` on joined PKs)

Default SQL `INNER JOIN` to `type: left_outer` in Silver Explores unless dropping unmatched rows is an invariant across all queries on that Explore; when a specific query needs `INNER JOIN` semantics on a `left_outer` Explore, filter the joined view's PK (`joined_view.id: "NOT NULL"` for `type: number` PKs—never `"-NULL"`, which is valid only on `type: string`), and for `LEFT JOIN` anti-join / 0-activity counts (`WHERE joined_view.id IS NULL` or `CASE WHEN joined_view.id IS NULL`), filter `joined_view.id: "NULL"` (valid on both `type: number` and `type: string`).

### Role-playing joins & `1:M` fanout `AVG(parent.col)` parity

- **Role-playing joins:** When `users` is joined twice (`buyer_id = u1.id` and `seller_id = u2.id`), use `from: users` and `view_label: "Buyer"` / `view_label: "Seller"`.
- **`1:M` fanout `AVG(parent.col)` vs symmetric `parent.avg_<col>`:** Whenever `1 parent` maps to `M child` rows (`users` <-> `order_items`, whether `explore: parent` `1:M` or `explore: child` `M:1` to `parent`) and SQL writes `AVG(parent.col)` without deduplicating `parent`, raw SQL weights `parent.col` by `child` row count while Looker's `parent.avg_<col>` (`type: average` on `parent`) always promotes to entity-grain `average_distinct`. Keep `parent.avg_<col>` pure on `parent` for Quick Start `query:` blocks; when `pre_gate.py` SQL parity requires the activity-weighted value, define a hidden composite `primary_key: yes` (`CONCAT(CAST(${parent.id} AS STRING), '_', CAST(COALESCE(${child.id}, 0) AS STRING))`) plus `avg_activity_weighted_<col>` (`type: average`, `sql: ${parent.col} ;;`, `tags: ["non_additive"]`) in `silver/:child_:parent_fields.view.lkml`.

### Cross-view dimensions and measures (`*_fields.view.lkml` + bare join)

Any dimension or measure that anywhere in its dependency DAG references different views belongs in the single Silver view named by sorting the referenced view names alphabetically + `_fields` (`silver/inventory_items_order_items_fields.view.lkml`, `silver/order_items_users_fields.view.lkml`), bare-joined (`sql: ;;`, `relationship: one_to_one`) onto the Explore joining those views. When two Explores with different base grains (e.g., `explore: users` vs `explore: order_items`) bare-join the same `*_fields` view, keep one file and exclude grain-specific measures on the other Explore via `explore: { fields: [ALL_FIELDS*, -order_items_users_fields.revenue_per_registered_user] }`.

## LookML templates

```lookml
# File: silver/order_items_users_fields.view.lkml
view: order_items_users_fields {
  dimension: pk {
    primary_key: yes
    hidden: yes
    # Use type: number + sql: ${order_items.id} ;; when only bare-joined onto M:1 explore: order_items; use CONCAT when also joined onto 1:M explore: users
    sql: CONCAT(CAST(${users.id} AS STRING), '_', CAST(COALESCE(${order_items.id}, 0) AS STRING)) ;;
  }

  measure: revenue_per_user {
    type: number
    sql: 1.0 * ${order_items.gross_revenue} / NULLIF(${users.count}, 0) ;;
    value_format_name: usd
    description: "Cross-join metric: Gross revenue divided by distinct users."
  }
}
```

```lookml
# File: silver/explores/order_items.explore.lkml
include: "/bronze/order_items.view.lkml"
include: "/bronze/order_items.refinement.lkml"
include: "/bronze/orders.view.lkml"
include: "/bronze/orders.refinement.lkml"
include: "/bronze/users.view.lkml"
include: "/bronze/users.refinement.lkml"
include: "/silver/order_items_users_fields.view.lkml"

explore: order_items {
  view_name: order_items

  join: orders {
    type: left_outer
    relationship: many_to_one
    sql_on: ${order_items.order_id} = ${orders.order_id} ;;
  }

  join: users {
    type: left_outer
    relationship: many_to_one
    sql_on: ${orders.user_id} = ${users.id} ;;
  }

  join: order_items_users_fields {
    view_label: "Order Items"
    sql: ;;
    relationship: one_to_one
  }
}
```

## Architecture rules

Because `bronze/:table.view.lkml` is never hand-edited, single-column `primary_key: yes` overrides and composite `CONCAT(...)` primary keys (`type: string`, `hidden: yes`) are always declared in `bronze/:table.refinement.lkml`.

Silver Explores default SQL `INNER JOIN` clauses to `type: left_outer` so ad-hoc exploration on joined dimensions does not silently drop unmatched fact rows. Set `type: inner` only when dropping unmatched rows is an invariant across all queries on that Explore. Any dimension or measure whose dependency DAG spans multiple joined views lives in `silver/:view_a_:view_b_fields.view.lkml` and is bare-joined (`sql: ;;`) into the Explore.
