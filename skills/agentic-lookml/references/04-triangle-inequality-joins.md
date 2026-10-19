# Triangle and date-range inequality joins (`triangle_inequality_joins`)

This category (`triangle_inequality_joins`) isolates non-equality and time-bounded joins into `gold/explores/:name.explore.lkml` (using `extends: [silver_explore]` and `tags: ["gold"]`), paired with `gold/:name.view.lkml` when point-in-time `AS OF` deduplication is required. Standard Gold extension joins use Tier 2 batch confirmation, while `AS OF` deduplication views require Tier 3 planning.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `triangle_inequality_joins` when any `join` in `parsed_query.joins` (or joins inside `ctes[].sql`) satisfies either condition:

- `join.non_equi_conditions != []` containing inequality or range operators across two tables (`BETWEEN`, `<`, `<=`, `>`, `>=`, such as `o.created_at BETWEEN s.start_date AND COALESCE(s.end_date, CURRENT_DATE())` or `e.event_time >= c.sent_time`).
- `join.join_type == "CROSS"` or `ON 1=1` paired with date range comparisons in `join.on_sql` or `parsed_query.where`.

## Representative SQL

```sql
-- Archetype 4A: Type-2 SCD / Effective Date Range Join
SELECT
  s.plan_tier,
  COUNT(DISTINCT o.order_id) AS orders_under_plan,
  SUM(o.sale_price) AS revenue_under_plan
FROM `project.dataset.orders` AS o
LEFT JOIN `project.dataset.user_subscription_history` AS s
  ON o.user_id = s.user_id
  AND o.created_at >= s.effective_start_at
  AND (o.created_at < s.effective_end_at OR s.effective_end_at IS NULL)
GROUP BY 1;

-- Archetype 4B: Point-in-Time "AS OF" Attribution (Inequality + Latest Match)
WITH matched AS (
  SELECT
    o.order_id,
    o.sale_price,
    c.campaign_type,
    ROW_NUMBER() OVER (
      PARTITION BY o.order_id
      ORDER BY c.touch_at DESC
    ) AS rn
  FROM `project.dataset.orders` AS o
  LEFT JOIN `project.dataset.campaign_touches` AS c
    ON o.user_id = c.user_id
    AND c.touch_at <= o.created_at
)
SELECT campaign_type, SUM(sale_price) AS attributed_revenue
FROM matched WHERE rn = 1 GROUP BY 1;
```

## Impact of naive translation

1. Putting inequality or time-bounded joins into `silver/explores/` violates the Silver rule (`PK = FK` equality only) and risks massive Cartesian scans on standard queries.
2. If a user has overlapping intervals or multiple prior touches (`c.touch_at <= o.created_at`), joining directly with `relationship: many_to_one` duplicates `orders` rows and inflates `SUM(o.sale_price)`.

## How to handle

### Isolate triangle and inequality joins in Gold

Keep `silver/explores/orders.explore.lkml` strictly limited to `PK = FK` equality joins. Create `gold/explores/:name.explore.lkml` with `extends: [orders]`, `view_name: orders`, and `tags: ["gold"]`.

### Verify disjoint versus overlapping intervals

1. For disjoint intervals (clean SCD Type 2 tables where one order matches at most one interval), join directly in `gold/explores/` with `relationship: many_to_one`.
2. For overlapping intervals (where one order can match multiple intervals or campaigns), set `relationship: one_to_many` (or `many_to_many`) in `gold/explores/` so Looker activates symmetric aggregates on `orders` measures.
3. For point-in-time `AS OF` attribution (keeping only the single most recent prior match), create a Gold Derived Table (`gold/order_latest_touch_map.view.lkml` using `${view.SQL_TABLE_NAME}` and `${view.field}` for every table and column reference) that resolves the `1:1` mapping (`order_id` to `latest_touch_id` via `QUALIFY ROW_NUMBER() = 1`), then join it into `gold/explores/`.

### Calendar spine table (`bronze/calendar_dates.view.lkml`)

Maintain a standard `bronze/calendar_dates.view.lkml` physical or generated date-spine view. Standard `PK = FK` date-alignment joins (`${orders.created_date} = ${order_calendar.calendar_date}` using `from: calendar_dates` and `view_label:`) belong in Silver Explores, while active-subscription interval joins (`${calendar_dates.calendar_date} BETWEEN ${subscriptions.start_date} AND ${subscriptions.end_date}`) belong in Gold Explores (`tags: ["gold"]`).

## LookML template

```lookml
# File: gold/explores/orders_subscription_attribution.explore.lkml
include: "/silver/explores/orders.explore.lkml"
include: "/bronze/user_subscription_history.view.lkml"
include: "/bronze/user_subscription_history.refinement.lkml"

explore: orders_subscription_attribution {
  extends: [orders]
  view_name: orders
  tags: ["gold"]

  join: user_subscription_history {
    type: left_outer
    relationship: many_to_one # Use one_to_many if intervals can overlap per user
    sql_on: ${orders.user_id} = ${user_subscription_history.user_id}
      AND ${orders.created_raw} >= ${user_subscription_history.effective_start_raw}
      AND (
        ${orders.created_raw} < ${user_subscription_history.effective_end_raw}
        OR ${user_subscription_history.effective_end_raw} IS NULL
      ) ;;
  }
}
```

## Architecture rules

Gold is strictly a folder structure (`gold/` and `gold/explores/`) and a LookML tag (`tags: ["gold"]`), never an explore name suffix (use descriptive names like `explore: orders_subscription_attribution`, never `orders_gold`).

The canonical date spine lives in `bronze/calendar_dates.view.lkml`. Equality date joins (`fact_date = calendar_date`) are placed in `silver/explores/` with `from: calendar_dates` and `view_label:`, whereas inequality range joins (`calendar_date BETWEEN start_date AND end_date`) are isolated in `gold/explores/` with `tags: ["gold"]`.
