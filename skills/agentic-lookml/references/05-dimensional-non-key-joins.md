# Dimensional and multi-fact joins (`dimensional_non_key_joins`)

This category (`dimensional_non_key_joins`) handles non-key dimensional joins and multi-fact stitching across `gold/explores/:name.explore.lkml` (paired with `gold/:coalesce_view.view.lkml` for `FULL OUTER JOIN ON FALSE`), `silver/:name.view.lkml` (`UNION ALL` SDTs for overlapping schemas or entity-grain NDTs for sessionization), and `bronze/calendar_dates.view.lkml`. These patterns require Tier 3 architectural planning before implementation.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `dimensional_non_key_joins` when `parsed_query.joins` and `queries[].join_analysis` satisfy any of these conditions:

- A join's `equi_joins` equates non-unique dimensional attributes (`date = date`, `country = country`, `department = department`) where neither side is a `primary_key: yes` on that single table (`join_analysis[].inferred_relationship == "many_to_many"` or `join_analysis[].safety_warnings` flags a `fan_trap` or chasm trap).
- `join.join_type == "FULL"` (`join.side == "FULL"`, meaning a `FULL OUTER JOIN` stitching two fact tables or two aggregated CTEs).
- Two fact tables are joined directly on a shared non-unique dimension without a unique entity bridge.

## Representative SQL

```sql
-- Archetype 5A: Direct Dimensional Join (Orders joined to Daily Ad Spend on Date + Country)
SELECT
  DATE(o.created_at) AS report_date,
  o.country,
  COUNT(DISTINCT o.order_id) AS total_orders,
  SUM(a.spend_amount) AS ad_spend
FROM `project.dataset.orders` AS o
LEFT JOIN `project.dataset.ad_spend` AS a
  ON DATE(o.created_at) = a.spend_date
  AND o.country = a.country
GROUP BY 1, 2;

-- Archetype 5B: Multi-Fact FULL OUTER JOIN across Shared Dimensions
WITH daily_orders AS (
  SELECT DATE(created_at) AS d, country, SUM(sale_price) AS revenue
  FROM `project.dataset.orders` GROUP BY 1, 2
),
daily_targets AS (
  SELECT target_date AS d, country, SUM(target_amount) AS target_rev
  FROM `project.dataset.sales_targets` GROUP BY 1, 2
)
SELECT
  COALESCE(o.d, t.d) AS report_date,
  COALESCE(o.country, t.country) AS country,
  COALESCE(o.revenue, 0) AS revenue,
  COALESCE(t.target_rev, 0) AS target_rev
FROM daily_orders AS o
FULL OUTER JOIN daily_targets AS t
  ON o.d = t.d AND o.country = t.country;
```

## Impact of naive translation

1. Joining `orders` (1,000 rows for US on Jan 1) to `ad_spend` (50 campaign rows for US on Jan 1) produces a 50,000-row chasm trap ($M \times N$ row multiplication). Without `primary_key: yes` on both views and `relationship: many_to_many`, `SUM()` measures inflate by $50\times$ or $1000\times$.
2. Joining `sales_targets` via `LEFT JOIN` drops any date or country that had a target but zero orders.

## How to handle

### Decision framework: OJOF versus Silver `UNION ALL` versus Silver sessionization

| Scenario | Archetype | Preferred architecture | Why |
| :--- | :--- | :--- | :--- |
| Unrelated schemas with common joins | `orders` (sales) vs. `sales_targets` (budget) on `date + country` | Gold OJOF (`FULL OUTER JOIN ON FALSE` + `COALESCE` View) | Prevents chasm traps ($M \times N$ fanouts) and keeps unrelated table metrics clean while allowing shared filtering. |
| Same table twice / overlapping schemas | Net sales requiring `created_date` and `returned_date` filtered together | Silver `UNION ALL` SDT (with Compound PK) | Schemas are completely identical or overlapping; unioning is cleaner than self-joining with complex coalescing. |
| Windowing and grouping records | Calculating session bounds, visitor trails, or rolling activity windows | Silver Entity NDT (`silver/sessions.view.lkml`) | Windowing and grouping records into entities (like sessionization) is a Silver exercise. |
| Date alignment across facts | Aligning facts to an authoritative date dimension | Join `bronze/calendar_dates.view.lkml` | Join Bronze calendar view and properly re-label (`view_label: "Order Date"`, `view_label: "Return Date"`). |

### Implementation rules

1. When joining unrelated fact tables across shared dimensions, use the OJOF pattern in `gold/explores/:name.explore.lkml` (`tags: ["gold"]`):
   - **2-table OJOF (self-contained template below — do not open `lookml-ojof`):** Extend an existing Silver Explore (`extends: [orders]`, `view_name: orders`), join the peer table with `type: full_outer`, `relationship: many_to_many`, and `sql_on: FALSE ;;`, and bare-join (`sql: ;;`, `relationship: one_to_one`) a field-only `COALESCE` view (`gold/:shared_dims.view.lkml`).
   - **3+-fact `from: none` star-schema Explore (only open [lookml-ojof](../../lookml/sub-skills/lookml-ojof/SKILL.md) for this case):** Use a 0-row `SELECT 0 FROM UNNEST([])` base view, join every peer fact via `type: full_outer`, `relationship: one_to_one`, and `sql_on: FALSE ;;`, bind shared entity dimensions via `COALESCE({% if fact._in_query %} ${fact.fk}, {% endif %} NULL)`, and cross-join co-dimension views via `UNNEST([${codim_date.SQL_TABLE_NAME}])`.
2. When `UNION ALL` is selected for overlapping schemas, always generate a compound primary key so the unioned table can safely participate in secondary foreign key joins without missing PK errors:
   ```lookml
   dimension: compound_pk {
     primary_key: yes
     hidden: yes
     type: string
     sql: CONCAT(${source_event_type}, '_', CAST(${order_id} AS STRING)) ;;
   }
   ```
3. If the dimensional join was used to sessionize or window events, model it as a Silver view or NDT (`silver/sessions.view.lkml`) with `explore_source:` or window functions, exposed in `silver/explores/`.

## LookML template (`FULL OUTER JOIN ON FALSE` and `COALESCE` view)

```lookml
# File: gold/revenue_vs_targets_dims.view.lkml
view: revenue_vs_targets_dims {
  dimension_group: report {
    type: time
    timeframes: [raw, date, week, month, year]
    datatype: date
    sql: COALESCE(${orders.created_date}, ${sales_targets.target_date}) ;;
  }

  dimension: country {
    type: string
    sql: COALESCE(${orders.country}, ${sales_targets.country}) ;;
  }
}
```

```lookml
# File: gold/explores/revenue_vs_targets.explore.lkml
include: "/silver/explores/orders.explore.lkml"
include: "/bronze/sales_targets.view.lkml"
include: "/bronze/sales_targets.refinement.lkml"
include: "/gold/revenue_vs_targets_dims.view.lkml"

explore: revenue_vs_targets {
  extends: [orders]
  view_name: orders
  tags: ["gold"]

  join: sales_targets {
    type: full_outer
    relationship: many_to_many
    sql_on: FALSE ;;
  }

  join: revenue_vs_targets_dims {
    view_label: "Shared Dimensions"
    relationship: one_to_one
    sql: ;;
  }
}
```

## Architecture rules

Use Gold OJOF (`type: full_outer`, `relationship: many_to_many`, `sql_on: FALSE ;;`, plus a `COALESCE` view joined via `sql: ;;`) when stitching unrelated fact tables (`orders` vs. `sales_targets`) across shared dimensions so row-level drill-down and ad-hoc filtering remain intact without $M \times N$ chasm traps.

Use a Silver `UNION ALL` SDT (with `extends: [base_view]` and a `compound_pk`) when combining identical or overlapping schemas or two dates on the same table, and use Silver Entity NDTs (`explore_source:`) when rolling up a single entity or session grain before joining `many_to_one` in `silver/explores/`.
