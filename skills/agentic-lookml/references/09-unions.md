# `UNION` and `UNION ALL` queries (`unions`)

This category (`unions`) routes entity or event stream concatenations to `silver/:name.view.lkml` and Long Metrics (unpivoting measures into rows) to `gold/:name.view.lkml`. These patterns require Tier 3 planning.

## Tool categorization rule (`lkr parse`)

The parser tags a query with `unions` when either condition holds:

- `parsed_query.statement_type == "UNION"` (top-level `UNION ALL` or `UNION DISTINCT`).
- Recursive AST inspection of `parsed_query.ctes` or inline subqueries finds a `UNION` expression.

## Representative SQL

```sql
-- Archetype 9A: Multi-Source Event Stream Concatenation (Silver)
SELECT
  event_id,
  user_id,
  created_at,
  'web' AS platform
FROM `project.dataset.web_events`
UNION ALL
SELECT
  event_id,
  user_id,
  created_at,
  'mobile' AS platform
FROM `project.dataset.mobile_events`;

-- Archetype 9B: Long Metrics / Unpivoting Metrics into Rows (Gold)
SELECT DATE(created_at) AS report_date, 'Orders' AS metric_name, COUNT(DISTINCT order_id) AS metric_value
FROM `project.dataset.orders` GROUP BY 1
UNION ALL
SELECT DATE(created_at) AS report_date, 'Revenue' AS metric_name, SUM(sale_price) AS metric_value
FROM `project.dataset.orders` GROUP BY 1;
```

## Impact of naive translation

1. Writing raw `FROM project.dataset.web_events` and raw column names inside a `derived_table: { sql: ... UNION ALL ... ;; }` breaks Looker's dependency graph (`${view.SQL_TABLE_NAME}`) and bypasses Bronze column definitions.
2. Without partition filter pushdown into every `UNION ALL` branch, BigQuery scans the full history of every unioned table.

## How to handle

### Follow the ironclad SDT rule (`${}` on everything)

Because LookML `explore_source:` (NDT) cannot express `UNION ALL`, a SQL Derived Table (`derived_table: { sql: ... ;; }`) is required. Every table in every `UNION ALL` branch must use `${bronze_view.SQL_TABLE_NAME}`, and every column selected or filtered inside the `UNION ALL` SQL must reference its Bronze dimension (`${bronze_view.dimension_name}`) or `${TABLE}.col` / `${field}` rather than raw SQL identifiers.

### Route `UNION ALL` between Silver and Gold

1. Overlapping schemas or the same table queried twice (`web_events UNION ALL mobile_events`, or Net Sales filtering `created_date` and `returned_date` together) belong in `silver/:name.view.lkml`, exposed in `silver/explores/:name.explore.lkml`.
2. Long Metrics and metric unpivoting (stacking `Orders`, `Revenue`, and `AOV` as rows under `metric_name` and `metric_value`) belong in `gold/:name.view.lkml`, exposed in `gold/explores/:name.explore.lkml` (`tags: ["gold"]`).
3. Same-table mutually exclusive `WHERE` branches should not use `UNION ALL` at all; collapse them into a single Bronze or Silver query with `IN (...)` or filtered measures.

### Extend the Bronze view (`extends: [base_view]`), alias `AS {{ _table }}` with `{{ field._sql }}`, and define a compound PK

For SDTs that union or window tables with overlapping schemas, extend the base Bronze view (`extends: [base_view]`, or `extends: [secondary_view, primary_view]` for multi-source unions where columns do not collide) so the derived view automatically inherits all existing dimensions, dimension groups, types, and labels from Bronze.

Alias each `UNION ALL` branch's `FROM` clause with `AS {{ _table }}` (`FROM ${web_events.SQL_TABLE_NAME} AS {{ _table }}`) and reference inherited fields via `{{ field_name._sql }}` (see [lookml-advanced-liquid](../../lookml/sub-skills/lookml-advanced-liquid/SKILL.md)). Unlike `${web_events.event_id}`, which requires `web_events` to be joined into the outer Explore and fails with `FIELD_REF_IN_BAD_CONTEXT` when materialized as a PDT (`forTableName = true`), `{{ field_name._sql }}` paired with `AS {{ _table }}` evaluates in the derived view's own context, requires zero bare joins on the Explore, and is 100% PDT-safe. Because each `SELECT` branch in a `UNION ALL` has its own independent `FROM` scope, every branch can safely use `AS {{ _table }}`.

Override the inherited single-column PK (`primary_key: no`) and define a mandatory composite primary key (`compound_pk` with `primary_key: yes`, such as `sql: CONCAT(${platform}, '_', CAST(${event_id} AS STRING)) ;;`). This guarantees the unioned view can safely participate in secondary foreign key joins in Silver and Gold Explores without fanout or missing PK errors. In the Silver Explore or join, use LookML's `fields: [ALL_FIELDS*, -view.field_not_needed]` to exclude any parent dimensions that are not present in the unioned projection.

## LookML template (Silver `UNION ALL` with `extends:`, `AS {{ _table }}`, and `{{ field._sql }}`)

```lookml
# File: silver/unified_events.view.lkml
include: "/bronze/web_events.view.lkml"
include: "/bronze/web_events.refinement.lkml"
include: "/bronze/mobile_events.view.lkml"
include: "/bronze/mobile_events.refinement.lkml"

view: unified_events {
  # Multiple inheritance: web_events is last so its definitions win on any shared field names
  extends: [mobile_events, web_events]

  derived_table: {
    sql:
      SELECT
        {{ event_id._sql }} AS event_id,
        {{ user_id._sql }} AS user_id,
        {{ created_raw._sql }} AS created_at,
        'web' AS platform
      FROM ${web_events.SQL_TABLE_NAME} AS {{ _table }}
      UNION ALL
      SELECT
        {{ event_id._sql }} AS event_id,
        {{ user_id._sql }} AS user_id,
        {{ created_raw._sql }} AS created_at,
        'mobile' AS platform
      FROM ${mobile_events.SQL_TABLE_NAME} AS {{ _table }} ;;
  }

  dimension: compound_pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CONCAT(${platform}, '_', CAST(${event_id} AS STRING)) ;;
  }

  # Override inherited single-column PK from web_events so only compound_pk is primary_key: yes
  dimension: event_id {
    primary_key: no
    type: string
    sql: ${TABLE}.event_id ;;
  }

  dimension: platform {
    type: string
    sql: ${TABLE}.platform ;;
  }
}
```

```lookml
# File: silver/explores/unified_events.explore.lkml
include: "/silver/unified_events.view.lkml"

explore: unified_events {
  view_name: unified_events
  # Exclude parent web_events fields that are not projected in the UNION ALL SQL
  fields: [ALL_FIELDS*, -unified_events.web_only_session_cookie]
}
```

## Architecture rules

Silver `UNION ALL` SDTs must use `${view.SQL_TABLE_NAME}` and `${view.field}` for every table and column reference, extend the primary Bronze view (`extends: [base_view]`), override the inherited single-column PK (`primary_key: no`) in favor of `compound_pk` (`primary_key: yes`), and exclude unprojected parent columns on the Explore via `fields: [ALL_FIELDS*, -view.unmapped_col]`.
