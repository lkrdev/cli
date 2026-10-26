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

The easiest way to author a Custom Measure in the Query or Dashboard Layer is using [looker-filters](../../looker-filters/SKILL.md) (for single-field filter strings, `,` OR lists, `^` escaping, numeric intervals, and relative/absolute date bounds) or `matches_filter(${view.field}, \`filter_expression\`)` in [looker-expressions](../../looker-expressions/SKILL.md). Custom Fields (`custom_fields`) and Table Calculations (`table_calculations`) live in the Looker API query payload (`dynamic_fields`), Saved Looks, or LookML Dashboards (`.dashboard.lookml`), and cannot be placed inside an `explore: { query: {} }` Quick Start block.

| Sub-pattern | Condition | Resolution | Target location |
| :--- | :--- | :--- | :--- |
| Universal report slice (not an intrinsic KPI) | Every metric shares an ad-hoc `WHERE X` or `CASE WHEN X`, and `metrics.md` does not define a recurring predicate-specific KPI | Strip from measure; use strictly unfiltered measure names (`total_revenue`, never a predicate-named alias) + runtime filter on `X` ([measures-and-sql-functions.md](measures-and-sql-functions.md), [looker-filters](../../looker-filters/SKILL.md)) | Query / Dashboard Filter |
| Infrequent filtered metric | Side-by-side comparison for one report (`us_orders` vs. `uk_orders`) | Keep as Custom Measure (`custom_fields`) using [looker-filters](../../looker-filters/SKILL.md) or ``matches_filter(${orders.country}, `US`)`` ([looker-expressions](../../looker-expressions/SKILL.md)) | Query / Dashboard Layer |
| Canonical single-table filtered KPI | Core business definition on 1 table (`completed_revenue`, `sunk_dusty_shelf_cost`), whether written as `CASE WHEN` or `WHERE` + `metrics.md` | Declarative LookML Measure with `filters: [status: "Complete"]` (never `CASE WHEN` or `ROUND` in `sql:`; skip unrequested unfiltered base measures per YAGNI) | `bronze/:table.refinement.lkml` |
| Compound cross-column `OR` filtered KPI | Measure filters with `OR` across two columns (`status = 'Complete' OR is_override = TRUE`) | For ad-hoc or single-report use, keep as a Custom Measure (``matches_filter(${orders.status}, `Complete`) OR ${orders.is_override}``) or Custom Dimension ([looker-expressions](../../looker-expressions/SKILL.md)). For a canonical single-table KPI, define a hidden `type: yesno` helper dimension (`is_completed_or_override`) and filter the measure on `filters: [is_completed_or_override: "yes"]` | Query / Dashboard Layer or `bronze/:table.refinement.lkml` |
| Cross-view dimension or measure (`gross_margin`, `total_gross_margin`) | Dimension or measure whose dependency DAG references multiple joined views (`${order_items.sale_price} - ${inventory_items.cost}` or filtered metric across views) | Move all fields in that cross-view DAG into an alphabetically named Silver `_fields` view (`silver/inventory_items_order_items_fields.view.lkml`) and bare-join (`sql: ;;`, `relationship: one_to_one`) into the Explore | `silver/:view_a_:view_b_fields.view.lkml` + `silver/explores/` |
| One-off bucketing | Ad-hoc campaign/report `CASE WHEN` | Keep as Custom Dimension (`custom_fields`, [looker-expressions](../../looker-expressions/SKILL.md)) | Query / Dashboard Layer |
| Lifecycle date `NULL` / `NOT NULL` state (`sold_at IS NULL`, `returned_at IS NOT NULL`) | SQL `WHERE` or `CASE WHEN` checks nullability on a date/timestamp column | Define a positive-form `type: yesno` dimension on `${<group>_raw} IS NOT NULL` (`is_sold`, `is_returned`) and filter measures/queries on `is_sold: "no"` or `"yes"` | `bronze/:table.refinement.lkml` |
| Reusable simple dimension or Business Term | Named domain terms (`metrics.md`), standard tiers, flags, date-parts, or buckets (`is_young_customer`, `age_tier`, `shopping_regime`, `full_name`) | Match shape to term semantics (never blanket-apply `is_`; zero speculative `<term>_count` measures; group `3+` sibling dimensions around one attribute under a shared noun `group_label:` like `"Age"` or `"Location"`, and gate country-specific `case:`/`SUBSTR` dimensions on `${country} = '...'` with no catch-all `else:` so out-of-scope rows return `NULL`): **if relative/rolling calendar period** (*"New Customer: current calendar year"*) $\rightarrow$ reuse `<group>_year` / `<group>_date` (`"this year"`, enriching `description:`/`synonyms:` rather than baking `CURRENT_TIMESTAMP()` into `is_<term>`); **if boolean-like** $\rightarrow$ `type: yesno` (`is_<term>`/`has_<term>` + noun `label: "<Term>"`); **if categorical** $\rightarrow$ noun `<term>` via native `case:` (strip SQL `'1. '`–`'9. '` sort prefixes from `label:`/`else:`, order `when:` branches `1..N` since `__sort_` sorts `else:` last unless `alpha_sort: yes`; use raw `sql: CASE ... END ;;` only for dynamic labels) or `type: tier`; **if scalar/duration** $\rightarrow$ noun `<term>` via `string`/`number`, or `type: duration` `dimension_group` (`sql_end: COALESCE(${sold_raw}, ${common_helpers.current_timestamp_raw}) ;;`) | `bronze/:table.refinement.lkml` (1 table, incl. `common_helpers`) or `silver/:view_a_:view_b_fields.view.lkml` (2+ views) |
| One-off display ratio | Visual math between two columns on one chart (`us_orders / uk_orders`) | Keep as Table Calculation (`if(${uk_orders} = 0, null, ${us_orders} / ${uk_orders})` — never `nullif()`, which does not exist in [looker-expressions](../../looker-expressions/SKILL.md)) | Query / Dashboard Layer |
| Single-table ratio | Canonical ratio within 1 table (`aov = total_rev / order_cnt`) | LookML `measure` (`type: number`, `sql: 1.0 * ${num} / NULLIF(${den}, 0) ;;`) | `bronze/:table.refinement.lkml` |
| Cross-table ratio | Canonical ratio across joined tables (`rev_per_user = order_items.total_revenue / users.count`) | LookML `measure` in an alphabetically named Silver `_fields` view (`silver/order_items_users_fields.view.lkml`), bare-joined (`sql: ;;`) into the Explore | `silver/:view_a_:view_b_fields.view.lkml` + `silver/explores/` |

## When to create a `type: yesno` dimension (positive polarity & no opposites)

Use judgment rather than wrapping every filter condition in a boolean field, and enforce **strict positive polarity** whenever a `type: yesno` field is created:

1. **Date and timestamp nullability (`NULL` / `-NULL`) — create ONE positive-polarity `type: yesno` dimension:** Whenever SQL tests `<timestamp_or_date> IS NULL` or `IS NOT NULL` (`sold_at IS NULL`, `returned_at IS NOT NULL`, `deleted_at IS NULL`), define a single **positive-form** `type: yesno` dimension (`is_sold`, `is_returned`, `is_deleted`) in `bronze/:table.refinement.lkml` against the `raw` timeframe (`sql: ${sold_raw} IS NOT NULL ;;`), then filter via `is_sold: "no"` (for unsold) or `is_sold: "yes"` (for sold) in measures and Explore queries. Using `${<group>_raw}` avoids Looker's `DATE()`/timezone cast on `${<group>_date}: "NULL"` and gives users and Conversational Analytics a clean `Yes / No` toggle.
2. **Never create the opposite / negated twin:** Before adding any `type: yesno` dimension or filtered measure, inspect existing `views[].fields` in `lkr parse sql-lookml-compare`. Never author negated boolean names (`is_unsold`, `is_not_sold`, `is_unreturned`, `is_inactive`, `has_not_churned`), never add an inverse `yesno` field (`${sold_raw} IS NULL` or `NOT ${is_sold}`) alongside an existing positive `yesno` field (`is_sold`), and never speculatively create the opposite filtered measure (`sold_inventory_cost` when only `sunk_dusty_shelf_cost` was requested). Flip the filter value (`"yes"` vs. `"no"`) on the single positive field instead.
3. **Compound `OR` helper for LookML measures — create a `hidden: yes` positive `type: yesno` dimension:** Because `measure: { filters: [...] }` combines multiple fields with `AND`, cross-column `OR` conditions (`${status} = 'Returned' OR ${is_returned}` — note `${yesno_dim}` expands directly as a parenthesized SQL boolean expression) require a hidden positive-form `type: yesno` helper dimension (`is_ever_returned`).
4. **Unnamed ad-hoc string equality/non-null or numeric intervals — skip `type: yesno`:** Do not create boolean flags for unnamed one-off query slices (`status = 'Complete'`, `uri_dept IS NOT NULL`, `seg != ''`, `EXTRACT(HOUR FROM created_at) BETWEEN 0 AND 5`, `amount >= 100`); filter directly via `filters: [status: "Complete"]`, `filters: [uri_dept: "-NULL"]` (`"-EMPTY"` for `!= ''`; never `"NOT NULL"` on `type: string`), or `filters: [created_hour_utc: "[0, 5]"]`. **Exception — Named boolean-like Business Terms:** When `metrics.md` defines a named binary segment, cohort, or flag (e.g., *"Young Customer: under age 25"*), promote a positive `type: yesno` dimension (`dimension: is_young_customer`, explicit noun `label: "Young Customer"` since Looker appends `(Yes / No)`, `synonyms: [...]`) without adding an unrequested `<term>_count` measure. (Non-boolean Business Terms—categorical `CASE`/tiers, derived scalars, durations—use a plain noun `<term>` identifier without `is_`.)

## LookML templates

### Single-table dimensions and measures in Bronze refinement

```lookml
# File: bronze/orders.refinement.lkml (Single-table dimensions & measures - entire DAG stays within orders + common_helpers)
include: "orders.view.lkml"

view: +orders {
  dimension_group: fulfillment_age {
    type: duration
    intervals: [day, month, year]
    sql_start: ${created_raw} ;;
    sql_end: COALESCE(${delivered_raw}, ${common_helpers.current_timestamp_raw}) ;;
  }

  dimension: fulfillment_aging_tier {
    case: {
      when: {
        sql: ${days_fulfillment_age} < 7 ;;
        label: "Fast (<7 Days)"
      }
      when: {
        sql: ${days_fulfillment_age} < 30 ;;
        label: "Standard (7-29 Days)"
      }
      else: "Backlogged (30+ Days)"
    }
  }

  dimension: age_tier {
    type: tier
    tiers: [25, 41]
    style: integer
    sql: ${age} ;;
  }

  dimension: is_returned {
    type: yesno
    sql: ${returned_raw} IS NOT NULL ;;
    description: "Whether the order has been returned (returned_at is populated)."
  }

  dimension: is_ever_returned {
    type: yesno
    hidden: yes
    sql: ${status} = 'Returned' OR ${is_returned} ;;
  }

  measure: count {
    label: "Orders Count"
    description: "Total number of orders."
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
    sql: 1.0 * ${total_revenue} / NULLIF(${count}, 0) ;;
    value_format_name: usd
  }
}
```

### Cross-view DAG dimensions and measures in Silver (`*_fields.view.lkml` + bare join)

Sort the direct LookML view names referenced via `${view.field}` alphabetically + `_fields` (e.g., `silver/inventory_items_order_items_fields.view.lkml`), include a hidden `dimension: pk { primary_key: yes hidden: yes ... }`, and bare-join (`sql: ;;`, `relationship: one_to_one`) onto the Silver Explore; see the full LookML template in [03-pk-fk-joins.md](03-pk-fk-joins.md#lookml-templates).
