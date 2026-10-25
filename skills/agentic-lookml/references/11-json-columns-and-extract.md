# Working with JSON columns and extract functions (`json_columns_and_extract`)

This category (`json_columns_and_extract`) hides raw physical JSON columns and disables filter suggestions in `bronze/:table.refinement.lkml`, extracts queried JSON paths into a dedicated field-only companion view (`bronze/:table__:col.view.lkml`), and joins that view via a bare join (`sql: ;;`, `relationship: one_to_one`) in `bronze/explores/:table.explore.lkml` (`hidden: no` while single-table; detached to `:table_base` with `hidden: yes` + `silver/explores/:table.explore.lkml` only when cross-table Silver joins or NDTs are needed).

> **Synthetic `TO_JSON_STRING(STRUCT(...))` pass-through CTE exception:** If `input.sql` has **no** physical JSON column in the database table and only constructs a temporary JSON blob inside a CTE (`TO_JSON_STRING(STRUCT(browser, traffic_source)) AS payload`) to `JSON_VALUE`/`JSON_EXTRACT_SCALAR` those same columns back out, unwrap the synthetic CTE directly to a Canonical Looker Query on the underlying Bronze scalar dimensions (`events.browser`, `events.traffic_source`)—create **zero** `bronze/:table__:col.view.lkml` companion views and **zero** derived tables.

## `STRUCT` versus `JSON`: how they differ and how to standardize

| Attribute | `STRUCT` (schema-on-write) | `JSON` (schema-on-read / semi-structured) |
| :--- | :--- | :--- |
| Typing | Strict, declared data types (`STRUCT<id INT64, name STRING>`). | Weakly typed or untyped dynamic JSON objects. |
| Storage | Columnar, shredded physically in Capacitor or Parquet with zero parsing overhead. | Stored as a text blob or semi-structured JSON binary requiring runtime extraction. |
| Looker generator behavior | Looker detects fields at generation time and emits dot-notation dimensions (`${TABLE}.geo.city`) or child views (`table__items.view.lkml`). | Looker's generator emits only a single raw string dimension (`dimension: metadata_json { sql: ${TABLE}.metadata_json ;; }`). |
| How to standardize | Keep the generator's scalar dimensions or child views as-is in `bronze/`. | Hide the raw JSON blob in `bronze/:table.refinement.lkml`, turn off suggestions (`suggestable: no`), extract queried paths into `bronze/:table__:col.view.lkml`, and join via `sql: ;;` in `bronze/explores/:table.explore.lkml` (`hidden: no` until promoted to Silver). |

## Tool categorization rule (`lkr parse`)

The parser tags a query with `json_columns_and_extract` when AST inspection of `parsed_query.columns[].sql` or `parsed_query.where` contains either pattern:

- Any JSON extraction function (`JSON_VALUE`, `JSON_EXTRACT_SCALAR`, `JSON_QUERY`, `JSON_EXTRACT`, `JSON_QUERY_ARRAY`, `JSON_EXTRACT_ARRAY`, `PARSE_JSON`, `LAX_INT64`, `LAX_FLOAT64`, `LAX_STRING`, `LAX_BOOL`).
- Native JSON subscript or field access (`payload.user.tier`, `payload['utm_source']`, `col:field::STRING` in Snowflake, `col->>'field'` in Postgres).

## Representative SQL

```sql
SELECT
  JSON_VALUE(metadata_json, '$.utm.source') AS utm_source,
  SAFE_CAST(JSON_VALUE(metadata_json, '$.cart.item_count') AS INT64) AS cart_item_count,
  LAX_FLOAT64(metadata_json.cart.discount_amount) AS discount_amount,
  COUNT(DISTINCT order_id) AS order_count,
  SUM(SAFE_CAST(JSON_VALUE(metadata_json, '$.cart.shipping_fee') AS FLOAT64)) AS total_shipping_fee
FROM `project.dataset.orders`
WHERE JSON_VALUE(metadata_json, '$.utm.medium') = 'cpc'
GROUP BY 1, 2, 3
```

## Impact of naive translation

1. Leaving raw JSON columns enabled with default suggestions causes Looker to run `SELECT DISTINCT metadata_json ... LIMIT 1000`, scanning gigabytes of JSON text for filter suggestions.
2. Dumping dozens of nested JSON attributes into the base view clutters the Explore field picker. Organizing them into a dedicated field-only view (`orders__metadata`) joined via a bare join (`sql: ;;`) isolates the namespace just like a native `STRUCT` view.
3. Leaving `JSON_VALUE(metadata_json, '$.utm.source')` in ad-hoc SQL forces users to memorize JSON path strings (`$.utm.source` versus `$.utm_source`).
4. Extracting numeric JSON fields without `SAFE_CAST(... AS INT64/FLOAT64)` leaves them as strings, breaking `type: sum` measures and numeric sorting.

## How to handle

### Hide the raw JSON column and disable suggestions in the Bronze refinement

In `bronze/:table.refinement.lkml`, hide the raw JSON column and disable suggestions:

```lookml
dimension: metadata_json {
  hidden: yes
  suggestable: no
}
```

### Organize extracted JSON dimensions in a dedicated companion view (`bronze/:table__:col.view.lkml`)

Create a companion view with no `sql_table_name` (such as `bronze/orders__metadata.view.lkml`). Extract dimensions referencing the parent table's dimension (`${orders.metadata_json}`), never `${TABLE}.metadata_json`. Wrap numeric fields in `SAFE_CAST(JSON_VALUE(...) AS INT64)` or `FLOAT64`, and wrap booleans in `SAFE_CAST(... AS BOOL)`.

Define single-table measures on extracted JSON numbers inside `orders__metadata.view.lkml` wrapping the extracted dimension (`sql: ${shipping_fee} ;;`), rather than repeating `JSON_VALUE(...)` inside measure SQL.

### Join the companion view via a bare join (`sql: ;;`) in the Bronze Explore

Like `UNNEST` joins, a bare join (`sql: ;;`) for extracted JSON attributes is one of the four physical Bronze explore mechanics because it reflects the internal structure of a single table rather than a cross-table semantic join. Keep it directly in `bronze/explores/orders.explore.lkml` (`hidden: no`) while single-table; only detach to `bronze/explores/orders_base.explore.lkml` (`hidden: yes`) + `silver/explores/orders.explore.lkml` (`extends: [orders_base]`, `hidden: no`, preserving `label:`) when cross-table Silver joins or NDTs are needed (never create a joinless pass-through Silver explore):

```lookml
explore: orders {
  hidden: no
  label: "Orders"
  view_name: orders

  join: orders__metadata {
    relationship: one_to_one
    sql: ;;
  }
}
```

Generic dynamic key-value regex filtering (`key::value`, `*::value`, `key::*`) is deferred to Gold-layer parameter design to avoid mixing filters and parameters in Silver.

## LookML templates

### Base table refinement (`bronze/orders.refinement.lkml`)

```lookml
# File: bronze/orders.refinement.lkml
include: "orders.view.lkml"

view: +orders {
  # Hide raw JSON and disable expensive filter suggestions
  dimension: metadata_json {
    hidden: yes
    suggestable: no
  }
}
```

### Extracted dedicated JSON view (`bronze/orders__metadata.view.lkml`)

```lookml
# File: bronze/orders__metadata.view.lkml
view: orders__metadata {
  # Field-only view: no sql_table_name; inherits parent PK for symmetric aggregates
  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: ${orders.order_id} ;;
  }

  dimension: utm_source {
    type: string
    sql: JSON_VALUE(${orders.metadata_json}, '$.utm.source') ;;
  }

  dimension: utm_medium {
    type: string
    sql: JSON_VALUE(${orders.metadata_json}, '$.utm.medium') ;;
  }

  dimension: cart_item_count {
    type: number
    sql: SAFE_CAST(JSON_VALUE(${orders.metadata_json}, '$.cart.item_count') AS INT64) ;;
  }

  dimension: shipping_fee {
    type: number
    sql: SAFE_CAST(JSON_VALUE(${orders.metadata_json}, '$.cart.shipping_fee') AS FLOAT64) ;;
    value_format_name: usd
  }

  measure: total_shipping_fee {
    type: sum
    sql: ${shipping_fee} ;;
    value_format_name: usd
  }
}
```

### Bare join in Bronze Explore (`bronze/explores/orders.explore.lkml`)

```lookml
# File: bronze/explores/orders.explore.lkml
include: "/bronze/orders.view.lkml"
include: "/bronze/orders.refinement.lkml"
include: "/bronze/orders__metadata.view.lkml"

explore: orders {
  hidden: no
  label: "Orders"
  view_name: orders

  # Bare join (sql: ;;) belongs in Bronze because it reflects single-table physical structure
  join: orders__metadata {
    relationship: one_to_one
    sql: ;;
  }
}
```

## Architecture rules

In BigQuery, `JSON_VALUE(${parent_view.json_dim}, '$.path')` paired with `SAFE_CAST(... AS INT64/FLOAT64/BOOL)` works identically across both `STRING`-typed JSON columns and native `JSON`-typed columns and is the canonical extraction syntax.

When JSON paths are extracted from a physical JSON column, place them in a field-only companion view (`bronze/:table__:col.view.lkml`, no `sql_table_name`, inheriting parent `primary_key: yes`) and join via `sql: ;;` (`relationship: one_to_one`, never `sql_on:`) in `bronze/explores/:table.explore.lkml` (detaching to `:table_base` with `hidden: yes` only when promoted to Silver).
