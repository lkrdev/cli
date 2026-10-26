# Templated filters and parameters (`templated_filters_and_parameters`)

This category (`templated_filters_and_parameters`) isolates Liquid templated filters (`{% condition %}`) and parameters (`{% parameter %}`) to `gold/:name.view.lkml` and `gold/explores/:name.explore.lkml` (using `extends: [silver_explore]`, `tags: ["gold"]`, and mandatory `always_filter:`). These patterns require Tier 3 planning.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `templated_filters_and_parameters` when any of these conditions hold:

- A subquery or CTE (`parsed_query.ctes`) requires a runtime date or attribute filter to be pushed inside an inner aggregation, window function, or join `ON` condition before outer grouping (for example, "Cohort users who signed up in `<selected_window>` and compare their all-time spend").
- A query uses parameterized comparison windows, dynamic currency or unit multipliers, or dynamic dimension and metric switching that cannot be expressed via standard outer `WHERE` filters.
- Existing LookML (`parameter:`, `filter:`, `bind_all_filters: yes`, or raw `sql:` expressions) contains `{% condition %}`, `{% parameter %}`, `{% date_start %}`, or `{% date_end %}`.

## Representative SQL

```sql
-- Parameterized Point-in-Time Cohort / Inner Subquery Filter
WITH cohort_users AS (
  SELECT DISTINCT user_id
  FROM `project.dataset.events`
  WHERE event_name = 'checkout_started'
    AND event_date BETWEEN '2026-01-01' AND '2026-01-31' -- Must be dynamic at runtime
)
SELECT
  u.country,
  COUNT(DISTINCT u.id) AS total_users,
  COUNT(DISTINCT c.user_id) AS cohort_matching_users
FROM `project.dataset.users` AS u
LEFT JOIN cohort_users AS c
  ON u.id = c.user_id
GROUP BY 1
```

## Impact of naive translation

1. Adding `{% condition %}` or `{% parameter %}` into `bronze/` or `silver/` violates the Medallion architecture, because Silver Explores must remain pure `PK = FK` without Liquid.
2. Using `{% if filter._is_filtered %} ... {% else %} 1=1 {% endif %}` hides required filters from users and causes accidental full-table scans when the filter is left blank.
3. Using `{{ parameter_name._parameter_value }}` for string literals instead of `{% parameter parameter_name %}` or omitting `allowed_value:` constraints introduces unescaped SQL injection risks.

## How to handle

### Prefer `bind_all_filters: yes` or standard outer `WHERE` before writing Liquid

First check whether a Gold NDT with `bind_all_filters: yes` or a standard outer Explore filter achieves the same SQL behavior. When an inner derived table only needs the same filters as the outer dashboard (such as dynamic `RANK()` or `ROW_NUMBER()` over filtered rows), always prefer a Gold NDT with `bind_all_filters: yes` over raw Liquid SQL.

Reserve explicit `filter:` and `{% condition %}` blocks for Cohort A versus Overall Population comparisons (where the inner subquery is filtered by the user's cohort selection while the outer Explore remains unfiltered or filtered on a different window) or conditional measure expressions (`CASE WHEN {% condition filter_name %} ${dim} {% endcondition %} THEN 1 ELSE 0 END`).

### Isolate all Liquid to `gold/` and `gold/explores/`

Define `filter:` or `parameter:` fields in a Gold view or Gold refinement (`gold/:name.view.lkml`). The sole project-wide exception is `_TABLE_SUFFIX` wildcard pruning in `bronze/explores/:prefix_base.explore.lkml` (Category 12). Always use `{% condition filter_name %} ${view.dimension} {% endcondition %}` so Looker handles `NULL`, `IN (...)`, date ranges, and negation automatically. For grand total and conditional join safety, always use `_in_query` rather than `_is_selected`.

### Enforce `always_filter:` on the Gold Explore

Never rely on silent `1=1` Liquid fallbacks or `conditionally_filter:`. Every `filter:` or `parameter:` used in Gold SQL must be listed in `always_filter:` on `gold/explores/:name.explore.lkml` (`tags: ["gold"]`) with a safe default [looker-filters](../../looker-filters/SKILL.md) value.

## LookML template

```lookml
# File: gold/cohort_matching_users.view.lkml
include: "/bronze/events.view.lkml"
include: "/bronze/events.refinement.lkml"

view: cohort_matching_users {
  derived_table: {
    sql:
      SELECT DISTINCT
        ${events.user_id} AS user_id
      FROM ${events.SQL_TABLE_NAME} AS events
      WHERE {% condition target_event_filter %} ${events.event_name} {% endcondition %}
        AND {% condition cohort_date_filter %} ${events.event_partition_date} {% endcondition %} ;;
  }

  filter: target_event_filter {
    type: string
    suggest_explore: events
    suggest_dimension: events.event_name
  }

  filter: cohort_date_filter {
    type: date
  }

  dimension: user_id {
    primary_key: yes
    hidden: yes
    type: string
    sql: ${TABLE}.user_id ;;
  }

  measure: matching_user_count {
    type: count_distinct
    sql: ${user_id} ;;
  }
}
```

```lookml
# File: gold/explores/users_cohort_analysis.explore.lkml
include: "/silver/explores/orders.explore.lkml"
include: "/gold/cohort_matching_users.view.lkml"

explore: users_cohort_analysis {
  extends: [orders]
  view_name: orders
  tags: ["gold"]

  always_filter: {
    filters: [
      cohort_matching_users.target_event_filter: "checkout_started",
      cohort_matching_users.cohort_date_filter: "30 days"
    ]
  }

  join: cohort_matching_users {
    type: left_outer
    relationship: one_to_one
    sql_on: ${users.id} = ${cohort_matching_users.user_id} ;;
  }
}
```

## Architecture rules

When an inner derived table requires the exact same runtime filters as the outer dashboard, prefer a Gold NDT with `bind_all_filters: yes`. Reserve explicit `filter:` and `{% condition %}` blocks in Gold for asymmetric Cohort A versus Overall Population comparisons where the inner subquery filter differs from the outer query filter.
