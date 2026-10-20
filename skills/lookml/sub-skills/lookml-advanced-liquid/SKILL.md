---
name: lookml-advanced-liquid
description: >
  Advanced LookML Liquid compiler patterns (`{{ _table }}`, `{{ _view._name }}`,
  `{{ view._name }}`, `{{ field._sql }}`, `{{ view.field._sql }}`, `(${EXTENDED})`,
  and `FieldDrop::COMPUTE_DEPENDENCY_EXCLUSIONS`) for DRY inheritance across
  Bronze, Silver, and Gold Medallion layers. Covers what works, compiler traps
  that fail (filtered measure `._sql` vs. NDTs with `cancel_grouping_fields` and
  `common_helpers`, `dimension_group` timeframe `._sql`, aliased `_sdt_*` bare
  joins, and joining views that use `{{ _table }}`).
license: Apache-2.0
metadata:
  publisher: google
  version: v1
---

# Advanced LookML Liquid and Medallion DRY inheritance (`lookml-advanced-liquid`)

## Compiler mechanics: why `{{ _table }}` and `{{ field._sql }}` work

Looker's `${view.SQL_TABLE_NAME}` substitution operator emits only the bare SQL table expression, PDT scratch table name, or CTE identifier. It never appends an `AS view_name` alias. At the same time, referencing `${view.field}` or `${field}` inside `derived_table: { sql: ... ;; }` triggers two compiler traps:

1. Referencing `${order_items.sale_price}` inside `derived_table.sql` fails LookML validation with `Inaccessible view "order_items"` unless `order_items` is joined in the active Explore.
2. Even with `extends: [order_items]`, unscoped `${clean_status}` inside `derived_table.sql` fails whenever the derived table is materialized as a PDT (`sql_trigger_value`, `datagroup_trigger`, `persist_for`) or compiled with `forTableName = true` (`FIELD_REF_IN_BAD_CONTEXT`). Looker rejects `${clean_status}` with `Field references are not allowed in this SQL context`, strips `${}`, and emits raw `clean_status`, breaking SQL compilation.

Pairing `extends: [base_view]` with `FROM ${base_view.SQL_TABLE_NAME} AS {{ _table }}` (or `AS {{ _view._name }}`) and `{{ field._sql }}` resolves each inherited or refined dimension's `sql:` expression in the Liquid runtime (`FieldDrop#_sql`), binding `${TABLE}` to `{{ _table }}` (the active `viewNameContext`). This compiles identically across both ephemeral CTEs and materialized PDTs.

## How aliasing with `{{ _table }}` works and how views can be joined

### Why two tables cannot both use `AS {{ _table }}` in a single `JOIN`

Inside a view's `derived_table.sql`, `{{ _table }}` (and `{{ _view._name }}`) evaluates to a single string: the active view's `viewNameContext` (such as `share_of_net_return`).

In a `UNION ALL`, each `SELECT` branch has its own independent `FROM` scope. A view with `extends: [inventory_items, order_items]` can alias `FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}` in Branch 1 and `FROM ${inventory_items.SQL_TABLE_NAME} AS {{ _table }}` in Branch 2 with zero Explore joins.

In a `JOIN` (`SELECT ... FROM table_a LEFT JOIN table_b`), both tables share the same `FROM` clause, so aliasing both `AS {{ _table }}` produces a duplicate table alias error in SQL. The primary table uses `AS {{ _table }}` (matching unscoped `{{ field._sql }}` from `extends: [table_a]`), while the joined table must use a distinct alias (`AS {{ _sdt_table_b._name }}` matching `{{ _sdt_table_b.field._sql }}`).

### Aliasing the cross-view bare join hack (`join: _sdt_<view> { from: <view> }`)

When an SDT joins a second Bronze table inside `derived_table.sql` and references `{{ other_view.field._sql }}`, `other_view` must be present in `explore.views`. Do not bare-join under the canonical view name (`join: inventory_items { sql: ;; fields: [] }`) if the Explore also needs to join `inventory_items` as a real outer Explore join, because doing so occupies the `inventory_items` join name on the Explore. Instead, alias the internal SDT bare join with `_sdt_` and `from:`:

```lookml
explore: silver_order_inventory_enriched {
  view_name: silver_order_inventory_enriched

  # Internal SDT Liquid dependency: aliased as `_sdt_inventory` so `inventory_items` stays free
  join: _sdt_inventory {
    from: inventory_items
    sql: ;;
    relationship: one_to_one
    fields: []
  }

  # Outer Explore remains free to join `inventory_items` normally
  join: inventory_items {
    type: left_outer
    relationship: many_to_one
    sql_on: ${silver_order_inventory_enriched.inventory_item_id} = ${inventory_items.id} ;;
  }
}

view: silver_order_inventory_enriched {
  extends: [order_items]
  derived_table: {
    sql:
      SELECT
        {{ id._sql }} AS id,
        {{ inventory_item_id._sql }} AS inventory_item_id,
        {{ sale_price._sql }} AS sale_price,
        {{ _sdt_inventory.cost._sql }} AS unit_cost,
        ({{ sale_price._sql }} - {{ _sdt_inventory.cost._sql }}) AS item_margin
      FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}
      LEFT JOIN ${inventory_items.SQL_TABLE_NAME} AS {{ _sdt_inventory._name }}
        ON {{ inventory_item_id._sql }} = {{ _sdt_inventory.id._sql }}
    ;;
  }
  dimension: item_margin { type: number sql: ${TABLE}.item_margin ;; }
}
```

### Joining SDT views that use `{{ _table }}` in an Explore

SDT views built with `AS {{ _table }}` and `{{ field._sql }}` can be joined into other Explores or joined to each other in two ways:

1. Joining directly by canonical view name (`join: dry_accounting_ledger`) works without extra configuration. Looker compiles `WITH dry_accounting_ledger AS (SELECT ... FROM order_items AS dry_accounting_ledger)` and joins `LEFT JOIN dry_accounting_ledger ON users.id = dry_accounting_ledger.user_id`:
   ```lookml
   explore: users {
     view_name: users
     join: dry_accounting_ledger {
       type: left_outer
       relationship: one_to_many
       sql_on: ${users.id} = ${dry_accounting_ledger.user_id} ;;
     }
   }
   ```
2. Joining under a role-playing alias via `from:` (`join: user_ledger { from: dry_accounting_ledger }`) sets `viewNameContext` to `user_ledger` (`{{ _table }}` inside the CTE evaluates to `user_ledger`). If the SDT also contains `${field}` references, Looker looks up `explore.views["dry_accounting_ledger"]` while rendering the CTE, so include a companion bare join for the canonical name (`join: dry_accounting_ledger { sql: ;; relationship: one_to_one fields: [] }`) whenever it is only joined via `from:`.

## Summary matrix: patterns that work vs. patterns that fail

| Pattern | Status | Behavior and rule |
| :--- | :--- | :--- |
| `extends: [base]` + `FROM ${base.SQL_TABLE_NAME} AS {{ _table }}` + `{{ dim._sql }}` | Works (CTEs and PDTs) | Binds `${TABLE}` in every inherited/refined dimension to `{{ _table }}`. Works in both ephemeral CTEs and materialized PDTs. |
| Multi-hop chained dimensions (`A -> B -> C`), `+view` refinements, `type: duration`, `type: tier`, `case:` | Works | `{{ field._sql }}` recursively expands arbitrarily deep `${...}` dimension chains, `TIMESTAMP_DIFF(...)`, and `CASE WHEN ... END` blocks. |
| Zero-redefinition Bronze to Silver `UNION ALL` (canonical column aliasing) | Works | Aliasing `UNION ALL` output columns back to Bronze physical column names (`AS created_at`, `AS sale_price`, `AS id`) lets Silver inherit all Bronze `dimension_group`s, dimensions, and measures with zero redefinition. |
| Silver to Bronze / child to parent late-binding template method | Works | Base SDT references hook dimensions (`{{ tax_multiplier._sql }}`, `WHERE {{ filter_predicate._sql }}`); child `extends:` views or `+view` refinements override the hook dimensions to specialize the parent `derived_table.sql`. |
| Multi-table `UNION ALL` via multiple inheritance (`extends: [view_a, view_b]`) | Works (0 joins) | Merges fields from both views; each `UNION ALL` branch aliases its physical table `AS {{ _table }}` with zero Explore joins. |
| Multi-table `JOIN` inside `derived_table.sql` via `_sdt_*` bare join | Works | Use `join: _sdt_other { from: other_view sql: ;; relationship: one_to_one fields: [] }` + `LEFT JOIN ${other_view.SQL_TABLE_NAME} AS {{ _sdt_other._name }}`. |
| Three-tier chaining (`Bronze -> Silver SDT -> Gold SDT`) | Works | Use `FROM (${EXTENDED}) AS {{ _table }}` (parentheses around `(${EXTENDED})` are mandatory) for zero-join inline expansion, or `FROM ${silver.SQL_TABLE_NAME} AS {{ _table }}` + bare join for chained CTEs. |
| True lazy join pruning in `sql_always_where` (`{{ view.field._sql }}` inside `{% if view._in_query %}`) | Works | `FieldDrop::COMPUTE_DEPENDENCY_EXCLUSIONS` includes `:_sql`, so `{{ users.country._sql }}` does not force `LEFT JOIN users` when no `users` field is queried (unlike `${users.country}`). |
| Filtered measures (`filters: [...]`) via `{{ measure._sql }}` in `GROUP BY` SDTs | Fails (use NDT + `cancel_grouping_fields`) | `{{ filtered_measure._sql }}` emits an unexpanded internal token `${view.field::filter}` that breaks SQL. Never use `{{ measure._sql }}` or manual `GROUP BY` in an SDT. Use a Native Derived Table (`explore_source:`) paired with `cancel_grouping_fields: [...]` on the Explore when grouping must be suppressed. |
| `dimension_group` timeframe `._sql` (`{{ created_date._sql }}`, `{{ created_month._sql }}`) | Does not truncate | Calling `._sql` on any timeframe (`_raw`, `_date`, `_month`) returns the raw `dimension_group.sql` (`view.created_at`) without `DATE(...)` or `FORMAT_TIMESTAMP(...)`. Use `{{ created_raw._sql }}` for raw timestamps, or wrap a truncated timeframe in a hidden dimension (`sql: ${created_month} ;;`) before calling `._sql`. |
| Two tables aliased `AS {{ _table }}` in the same `FROM ... JOIN ...` | Fails | `{{ _table }}` is a single string per view; use `AS {{ _table }}` only for the primary extended view and `AS {{ _sdt_join._name }}` for joined tables. |
| `{{ view._view._name }}` | Fails | `ViewDrop` has no nested `._view` property. Use `{{ _table }}` or `{{ _view._name }}` for the current view, and `{{ other_view._name }}` for another view. |

## Why NDTs (`explore_source:`), `cancel_grouping_fields`, and `common_helpers` replace `{{ measure._sql }}`

Although `{{ count._sql }}`, `{{ total_sale_price._sql }}`, and ratio measures expand to SQL aggregations when unfiltered, referencing any measure with LookML `filters: [...]` via `{{ measure._sql }}` emits the unexpanded internal compiler token `${view.field::filter}` and fails in the warehouse.

In the Medallion architecture:

1. Never write `GROUP BY` derived tables as SQL Derived Tables (`derived_table: { sql: ... ;; }`) and never replace declarative `measure` `filters: [...]` with `CASE WHEN` inside `sql:` just to use `{{ measure._sql }}`.
2. Always use a Native Derived Table (`explore_source:`) for aggregating derived tables. NDTs compile declarative `filters: [...]` measures, symmetric aggregates, and join paths natively.
3. Maintain a reusable table-less helper view in `bronze/common_helpers.view.lkml` and bare-join it (`join: common_helpers { sql: ;; relationship: one_to_one }`) into Explores with `cancel_grouping_fields: [common_helpers.no_group]`:
   ```lookml
   # File: bronze/common_helpers.view.lkml
   view: common_helpers {
     # Selecting common_helpers.no_group in a dimension-only query or NDT explore_source
     # cancels Looker's automatic GROUP BY across the query while projecting only `1`.
     dimension: no_group {
       hidden: yes
       type: number
       sql: 1 ;;
     }

     # Reusable CURRENT_TIMESTAMP() helper for type: duration dimensions across views
     dimension_group: current_timestamp {
       type: time
       timeframes: [raw, time, date, week, month, quarter, year]
       sql: CURRENT_TIMESTAMP() ;;
     }
   }
   ```
   When an NDT (`explore_source:`) includes `column: _no_group { field: common_helpers.no_group }`, Looker omits the inner `GROUP BY` clause completely, allowing NDT `derived_column:` window functions (`ROW_NUMBER() OVER (...)`, `LAG(...) OVER (...)`) to run over raw un-grouped rows without pulling a primary key into the projection.
4. Reserve `{{ field._sql }}` and `AS {{ _table }}` in SDTs strictly for row-level SQL constructs that NDTs cannot express (`UNION ALL`, single-table `QUALIFY`, or `SELECT *` row extensions).

## Canonical Medallion layer rules (Bronze, Silver, Gold)

### Bronze (`bronze/`)

Keep `bronze/:table.view.lkml` as the autogenerated 1:1 physical table definition and never hand-edit it. Define all single-table primary keys, reusable calculated dimensions (`clean_status`, `days_fulfillment`, `price_tier`, `lifecycle_stage`), and declarative `filters:` measures in `bronze/:table.refinement.lkml`. Because `{{ field._sql }}` resolves across `+view` refinements, every refined Bronze dimension is automatically available to downstream Silver and Gold SDTs via `extends: [table]`. Keep `bronze/common_helpers.view.lkml` in Bronze for bare-joined `no_group` (`cancel_grouping_fields`) and `current_timestamp` (`type: duration`) helpers.

### Silver (`silver/`)

In Silver `UNION ALL` SDTs (`silver/:name.view.lkml`), extend the Bronze view (`extends: [order_items]`), alias `FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}`, and project Bronze dimensions via `{{ field._sql }}`. When the `UNION ALL` represents a unified ledger over the same schema (such as orders and reversals), alias the output columns back to the Bronze physical column names (`AS created_at`, `AS sale_price`, `AS id`) so Silver inherits every Bronze `dimension_group`, dimension, and measure with zero redefinition. Always override the inherited single-column PK (`dimension: id { primary_key: no }`) and define a composite primary key (`dimension: compound_pk { primary_key: yes hidden: yes sql: CONCAT(...) ;; }`). Keep runtime-filter Liquid (`{% condition %}`, `{% parameter %}`) out of Silver, and use ephemeral NDTs (`explore_source:`) for Silver aggregations (`silver/:entity_facts.view.lkml`).

```lookml
# File: silver/share_of_net_return.view.lkml
include: "/bronze/order_items.view.lkml"
include: "/bronze/order_items.refinement.lkml"

view: share_of_net_return {
  extends: [order_items]
  derived_table: {
    sql:
      SELECT
        'orders' AS tbl,
        {{ id._sql }} AS id,
        {{ returned_raw._sql }} AS dt,
        {{ sale_price._sql }} AS amount
      FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}
      UNION ALL
      SELECT
        'reversals' AS tbl,
        {{ id._sql }} AS id,
        {{ created_raw._sql }} AS dt,
        {{ sale_price._sql }} * -1 AS amount
      FROM ${order_items.SQL_TABLE_NAME} AS {{ _table }}
      WHERE {{ status._sql }} IN ('Returned', 'Cancelled')
    ;;
  }

  dimension: compound_pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CONCAT(${tbl}, '_', CAST(${id} AS STRING)) ;;
  }
  dimension: id { primary_key: no hidden: yes }
  dimension: tbl { hidden: yes type: string sql: ${TABLE}.tbl ;; }

  dimension_group: dt {
    group_label: "Accounting"
    type: time
    datatype: date
    timeframes: [raw, date, week, month, quarter, year, day_of_week]
    sql: ${TABLE}.dt ;;
  }

  dimension: amount {
    label: "Accounting Amount"
    type: number
    sql: ${TABLE}.amount ;;
  }

  measure: daily_net_return {
    type: sum
    sql: ${amount} ;;
  }

  measure: daily_revenue {
    hidden: yes
    type: sum
    sql: ${amount} ;;
    filters: [tbl: "orders"]
  }

  measure: daily_net_return_rate {
    type: number
    sql: ${daily_net_return} / NULLIF(${daily_revenue}, 0) ;;
  }
}
```

### Gold (`gold/`, `tags: ["gold"]`)

In Gold views and Explores:

1. Combine `{% condition field %} {{ field._sql }} {% endcondition %}` inside Gold SDTs (`gold/:name.view.lkml`) and pair with mandatory `always_filter:` on the Gold Explore (`gold/explores/:name.explore.lkml`, `tags: ["gold"]`).
2. Inside `sql_always_where:` or `sql_where:` guarded by `{% if joined_view._in_query %}`, use `{{ joined_view.field._sql }}` instead of `${joined_view.field}` (`FieldDrop::COMPUTE_DEPENDENCY_EXCLUSIONS`) so Looker does not force `LEFT JOIN joined_view` when no field from `joined_view` is in the query:
   ```lookml
   sql_always_where:
     {% if users._in_query %}
       {{ users.country._sql }} IS NOT NULL
     {% else %}
       1=1
     {% endif %} ;;
   ```
3. When a Gold SDT extends a Silver SDT (`extends: [dry_accounting_ledger]`), use `FROM (${EXTENDED}) AS {{ _table }}` to inline-expand the Silver SDT with zero bare joins.
