---
name: looker-expressions
description: >
  Looker expressions syntax, context boundaries, advanced Table Calculation patterns, and Excel-equivalent
  function reference (`looker-expressions`). Breaks out post-query in-memory expressions (Table Calculations
  and LookML Data Test `assert: { expression: ... ;; }`) versus SQL-pushdown expressions (Custom Dimensions,
  Filtered Custom Measures, Explore Custom Filters `filter_expression`, and LookML NDT `expression_custom_filter:`).
  Covers operators, `yes`/`no`/`null` constants, `matches_filter` backtick syntax, advanced `index`/`match`/`offset_list`
  windowing recipes, Looker SDK `run_inline_query` / `create_query` `dynamic_fields` payloads, and 1:1 Excel formula
  mappings. Use when writing, debugging, or reviewing Table Calculations, Custom Fields, Custom Filters, LookML
  `.test.lkml` assertions, or NDT `expression_custom_filter` blocks.
---

# Looker Expressions (`looker-expressions`)

## Context matrix: Table Calculations vs. Custom Fields vs. LookML Expressions

Looker expressions run in **two different execution engines**—either **pushed down into warehouse SQL** or **evaluated post-query in memory** over returned rows. Single-field shorthand strings (`"this year"`, `"-Cancelled"`, `">=30"`) are Filter Expressions, not Looker expressions; see [looker-filters](../looker-filters/SKILL.md).

| Context | Where authored | Execution engine | Allowed `${...}` references | `matches_filter()` | Positional, pivot, column-agg & `to_*` functions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Table Calculations** | `run_inline_query` / `create_query` `body["dynamic_fields"]`, Explore UI, `.dashboard.lookml` | **Post-query in-memory** (over displayed rows up to `limit`) | Dimensions, measures, other table calcs, `:total`, `:row_total` (all must be in query) | **No** | **Yes** (`offset`, `offset_list`, `index`, `match`, `running_total`, `sum`, `mean`, `pivot_*`, `to_number`, etc.) |
| **Custom Dimensions** | `run_inline_query` / `create_query` `body["dynamic_fields"]` (`"dimension"`), Explore UI, `.dashboard.lookml` | **SQL pushdown** (`SELECT` / `GROUP BY`) | Modeled dimensions (`${view.dim}`) | **Yes** (backticks) | **No** |
| **Custom Measures** | `run_inline_query` / `create_query` `body["dynamic_fields"]` (`"measure"`), Explore UI, `.dashboard.lookml` | **SQL pushdown** (`AGG(CASE WHEN ...)` via `filter_expression`) | `based_on` (`hidden: no` field) + dimensions in `filter_expression` | **Yes** (backticks) | **No** |
| **Custom Filters** | `run_inline_query` / `create_query` `body["filter_expression"]`, Explore UI | **SQL pushdown** (`WHERE`, must return `yes`/`no`) | **Dimensions only** (never measures, totals, or table calcs) | **Yes** (backticks) | **No** |
| **LookML Data Test `assert:`** | `tests/**/*.test.lkml` (`assert: { expression: ... ;; }`, run via `run_lookml_test`) | **Post-query in-memory** (must return `yes` on every row; 5,000-row cap) | Fully scoped `${view.field}` projected via `column:` in `explore_source:` | **No** | **Yes** (same engine & function set as Table Calculations) |
| **LookML NDT `expression_custom_filter:`** | `.view.lkml` (`explore_source: { expression_custom_filter: ... ;; }`) | **SQL pushdown** (`WHERE` inside NDT subquery) | **Dimensions only** from `explore_source` | **Yes** (backticks) | **No** *(NDT `derived_column: { sql: ... ;; }` uses warehouse SQL, not Looker expressions)* |

> **Quick Start boundary:** Looker's `explore: { query: {} }` Quick Start block ([agentic-lookml](../agentic-lookml/SKILL.md)) accepts **only** modeled `dimensions`, `measures`, `filters` ([looker-filters](../looker-filters/SKILL.md)), `pivots`, `subtotals`, `limit`, `sorts`, and `timezone`—never Table Calculations or Custom Fields.

---

## Universal syntax rules & SQL translation traps

1. **Function names are strictly lowercase:** `round(${x}, 2)`, `if(...)`, `is_null(...)` (`ROUND(...)` fails).
2. **Logical operators are strictly UPPERCASE:** `AND`, `OR`, `NOT` (`and`/`or`/`not` fail). `AND` binds tighter than `OR`; use parentheses to override.
3. **Logical constants are lowercase unquoted symbols:** `yes`, `no`, `null` (never `true`/`false`). Unquoted `yes`/`no` are booleans; quoted `"yes"`/`"no"` are strings. A `type: yesno` field (`${orders.is_returned}`) already evaluates to `yes`/`no`—write `${orders.is_returned}` or `NOT ${orders.is_returned}`, and write `${x} > 100` directly instead of `if(${x} > 100, yes, no)`.
4. **Decimals `< 1` require a leading zero:** `0.95` works; `.95` throws a syntax error.
5. **Strings & comments:** Wrap string literals in double quotes (`"Complete"`, never single quotes). Start line comments with `#`.

| SQL habit (fails or wrong) | Correct Looker expression | Trap details |
| :--- | :--- | :--- |
| `x / NULLIF(y, 0)` | `if(${y} = 0, null, ${x} / ${y})` | **`nullif()` does not exist** in Looker expressions. |
| `CASE WHEN c1 THEN v1 ELSE v2 END` | `case(when(c1, v1), when(c2, v2), v2)` or `if(c1, v1, v2)` | SQL `CASE WHEN ... END` syntax is invalid. |
| `a \|\| ' ' \|\| b` or `a + b` | `concat(${users.first_name}, " ", ${users.last_name})` | `+` is numeric addition only. |
| `POW(x, 2)` or `x ^ 2` | `power(${x}, 2)` | `^` is not a math operator (`+`, `-`, `*`, `/` only). |
| `CEIL(x)` | `ceiling(${x})` | Function name is `ceiling`, not `ceil`. |
| `DATE_ADD(d, INTERVAL 7 DAY)` | `add_days(7, ${orders.created_date})` | **Number argument comes first**, date second (`add_days(number, date)`). |
| `DATE_DIFF(end_d, start_d, DAY)` | `diff_days(${orders.created_date}, ${orders.delivered_date})` | **`start_date` comes first**, `end_date` second (`end - start`). |
| `SUBSTR(s, 1, 3)` | `substring(${products.sku}, 1, 3)` | `start_position` is **1-indexed** (`1` = first character). |
| `s ILIKE '%hoodie%'` | `contains(lower(${products.name}), "hoodie")` | `contains(string, search_string)` is **case-sensitive**. |

---

## 1. Table Calculations (post-query in-memory)

Table Calculations operate on the result table **after** the SQL query finishes ([02-conditional-measures-and-bucketing.md](../agentic-lookml/references/02-conditional-measures-and-bucketing.md), [07-measure-of-measures-reaggregation.md](../agentic-lookml/references/07-measure-of-measures-reaggregation.md), [08-window-functions-and-qualify.md](../agentic-lookml/references/08-window-functions-and-qualify.md)):

- **Field selection requirement:** Every `${view.field}` referenced in a Table Calculation **must** be selected in the query's `fields` (or `dynamic_fields`). Do **not** list the `table_calculation` name itself inside `body["fields"]` (unlike Custom Fields).
- **Row-limit boundary:** Column functions (`sum()`, `mean()`, `rank()`, `running_total()`) only see returned rows (e.g., top 500 if `"limit": "500"`). Use `${orders.total_revenue:total}` (with `"total": True` in `run_inline_query` / `create_query` `body`) when you need the true SQL grand total across truncated rows.
- **Sorting constraints:** Database sorts must come **before** Table Calculation sorts (`"sorts": ["orders.total_net_revenue desc", "pct_of_total desc"]`). Looker disables sorting on any Table Calculation if the formula uses `offset()` or if the query hit its row limit.
- **Post-query visual row filtering (`Hide "No"s from Visualization`):** A Table Calculation returning `yes`/`no` (e.g., `NOT is_null(${wow_growth})` or `${wow_growth} > 0`) can hide `No` rows from charts without re-running SQL.

### Common Table Calculation patterns

```text
# Safe display ratio between two measures (02-conditional-measures-and-bucketing.md)
if(${uk_orders} = 0, null, ${us_orders} / ${uk_orders})

# Percent of displayed column vs. percent of SQL grand total
${orders.total_revenue} / sum(${orders.total_revenue})
${orders.total_revenue} / ${orders.total_revenue:total}

# Running total & average of displayed daily values (07 & 08 playbooks)
running_total(${orders.total_revenue})
mean(${orders.total_revenue})

# Period-over-period % change (when sorted DESC: previous period is row +1; when sorted ASC: row -1)
(${orders.total_revenue} / offset(${orders.total_revenue}, 1)) - 1
(${orders.total_revenue} - offset(${orders.total_revenue}, -1)) / if(offset(${orders.total_revenue}, -1) = 0, null, offset(${orders.total_revenue}, -1))

# 7-row trailing moving average (sorted ASC)
mean(offset_list(${orders.total_revenue}, -6, 7))

# Pivoted column-over-column % change & % of row
(${orders.total_revenue} / pivot_offset(${orders.total_revenue}, -1)) - 1
${orders.total_revenue} / sum(pivot_row(${orders.total_revenue}))
```

### Advanced `index()`, `match()`, and `offset_list()` patterns (live-verified)

`index(col, row_num)` returns the value at 1-based `row_num`, while `match(val, col)` returns the 1-based row number of the **first** occurrence of `val` in `col` (or, when `col` is a column of lists from `offset_list()`, the 1-based position *inside* each row's list). Combining them with `row()`, `max(row())`, and `offset_list()` emulates complex Excel `INDEX/MATCH` lookups and SQL `OVER (PARTITION BY ...)` window functions purely in memory:

1. **Single-key & global peak (`ARGMAX`) `INDEX/MATCH`:**
   ```text
   # Benchmark every row against a named cohort row (survives re-sorting)
   ${order_items.count} / index(${order_items.count}, match("Jeans", ${products.category}))

   # Return the dimension label of the highest-volume row across the table
   index(${products.category}, match(max(${order_items.count}), ${order_items.count}))
   ```

2. **Multi-criteria composite `INDEX/MATCH` (`match(yes, cond_1 AND cond_2)`):**
   Passing a compound boolean expression as the second argument of `match()` evaluates a virtual `yes`/`no` column and returns the first row where all predicates hold (equivalent to Excel `INDEX(C:C, MATCH(1, (A:A="Women")*(B:B="Jeans"), 0))`):
   ```text
   index(${order_items.count}, match(yes, ${products.department} = "Women" AND ${products.category} = "Jeans"))
   ```

3. **Simulating `OVER (PARTITION BY dim)` subtotals, running totals, `LAST_VALUE`, and partitioned `ARGMAX`:**
   Sort the query primarily by the partition dimension (`"sorts": ["products.department asc", ...]`). Because `match()` only finds the *first* match, reversing the column via `offset(${dim}, max(row()) - row() * 2 + 1)` lets a second `match()` locate the *last* row of each partition (using `max(row())` rather than `count(${dim})` so `null` values never shift indices):
   ```text
   # Helper 1 — group_start: 1-based first row of current department partition
   match(${products.department}, ${products.department})

   # Helper 2 — group_len: exact row count in current department partition
   (max(row()) - match(${products.department}, offset(${products.department}, max(row()) - row() * 2 + 1)) + 2) - ${group_start}

   # Partitioned subtotal: SUM(count) OVER (PARTITION BY department)
   sum(offset_list(${order_items.count}, -(row() - ${group_start}), ${group_len}))

   # Partitioned running total: SUM(count) OVER (PARTITION BY department ORDER BY category ASC)
   sum(offset_list(${order_items.count}, -(row() - ${group_start}), row() - ${group_start} + 1))

   # Partitioned LAST_VALUE: last category in each department partition
   index(${products.category}, ${group_start} + ${group_len} - 1)

   # Partitioned ARGMAX under arbitrary sort: top-selling category inside each department
   # even when sorted alphabetically (match(val, offset_list(...)) returns 1-based index within each row's slice!)
   index(
     ${products.category},
     ${group_start} + match(
       max(offset_list(${order_items.count}, -(row() - ${group_start}), ${group_len})),
       offset_list(${order_items.count}, -(row() - ${group_start}), ${group_len})
     ) - 1
   )
   ```

4. **Conditional moving average over the last $N$ qualifying rows (skipping non-matching rows):**
   When standard `offset_list(..., -2, 3)` fails because intermediate rows fail a condition (`count < 50`), number qualifying rows with `running_total()` and use `match()` to jump back dynamically to the $(k - N + 1)$-th qualifying row (`mean()` ignores `null`s inside the spanned slice):
   ```text
   # Helper — qualifying_seq: running count of qualifying rows
   running_total(if(${order_items.count} >= 50, 1, 0))

   # Average of the most recent 3 rows where count >= 50 (regardless of how many <50 rows sit between them)
   if(
     ${qualifying_seq} < 3,
     null,
     mean(
       offset_list(
         if(${order_items.count} >= 50, ${order_items.count}, null),
         -(row() - match(${qualifying_seq} - 2, ${qualifying_seq})),
         row() - match(${qualifying_seq} - 2, ${qualifying_seq}) + 1
       )
     )
   )
   ```

### Running Table Calculations via Looker SDK (`run_inline_query` / `create_query`)

Pass `"dynamic_fields"` as a JSON-encoded string on `run_inline_query(result_format="json", body=...)` or `create_query(body=...)` ([lkr-code-mode](../lkr-code-mode/SKILL.md)):

```python
import json

body = {
    "model": "agentic_thelook",
    "view": "orders",
    "fields": ["orders.created_month", "orders.total_net_revenue"],
    "sorts": ["orders.created_month asc"],
    "limit": "500",
    "dynamic_fields": json.dumps([
        {
            "table_calculation": "running_revenue",
            "label": "Running Revenue",
            "expression": "running_total(${orders.total_net_revenue})",
            "value_format": None,
            "value_format_name": "usd",
        }
    ]),
}
rows = json.loads(run_inline_query(result_format="json", body=body))
```

---

## 2. Custom Fields & Custom Filters (SQL pushdown)

Custom Fields and Custom Filters compile directly into the warehouse SQL query (`SELECT`, `GROUP BY`, `WHERE`) without modifying LookML files. Promote them to `bronze/:table.refinement.lkml` (single-table DAG) or `silver/:view_a_:view_b_fields.view.lkml` (cross-view DAG) when reused across reports or defined as canonical metrics/terms ([agentic-lookml](../agentic-lookml/SKILL.md)).

### Custom Dimensions & Custom Measures (`body["dynamic_fields"]`)

- **Must appear in both `dynamic_fields` AND `fields`:** Every Custom Dimension (`"dimension"`) or Custom Measure (`"measure"`) defined in `body["dynamic_fields"]` on `run_inline_query` / `create_query` (or `create_dashboard_element` / `update_dashboard_element`) must also list its identifier in `body["fields"]` in projection order.
- **`based_on` visibility rule:** Custom Measures (`count_distinct`, `sum`, `average`, `min`, `max`, `median`, `list`, or filtered existing measures) require `"based_on"` pointing to a `hidden: no` LookML field.
- **`matches_filter` with backticks:** Embed [looker-filters](../looker-filters/SKILL.md) shorthand inside Custom Dimensions, Custom Measure `filter_expression`s, or Custom Filters using **backticks** (`` `...` ``):
  ```text
  matches_filter(${orders.status}, `Complete,Shipped`) AND matches_filter(${orders.created_date}, `this year`)
  ```
- *(Non-expression Custom Field shortcuts: Custom Groups and Custom Bins bucket dimension values or numeric tiers without writing `case()` formulas.)*

```python
import json

body = {
    "model": "agentic_thelook",
    "view": "orders",
    "fields": ["orders.created_date", "age_cohort", "us_completed_revenue"],
    "dynamic_fields": json.dumps([
        {
            "dimension": "age_cohort",
            "label": "Age Cohort",
            "expression": 'case(when(${users.age} < 25, "Gen Z"), when(${users.age} <= 40, "Millennial"), "40+")',
        },
        {
            "measure": "us_completed_revenue",
            "label": "US Completed Revenue",
            "based_on": "orders.sale_price",
            "type": "sum",
            "filter_expression": 'matches_filter(${users.country}, `US`) AND (${orders.status} = "Complete" OR ${orders.is_override})',
            "value_format_name": "usd",
        },
    ]),
    "sorts": ["orders.created_date desc"],
    "limit": "500",
}
rows = json.loads(run_inline_query(result_format="json", body=body))
```

### Explore Custom Filters (`body["filter_expression"]`)

Standard `body["filters"]` ([looker-filters](../looker-filters/SKILL.md)) compares one field at a time against constants and joins multiple fields with `AND`. Pass `body["filter_expression"]` on `run_inline_query` / `create_query` (a Looker expression returning `yes`/`no`, **dimensions only**) whenever SQL `WHERE` needs:
1. **Field-to-field comparisons across joined views** (e.g., filtering orders or events to "New Customers" where activity year matches signup year): `${orders.created_year} = ${users.created_year}`
2. **Cross-column `OR` conditions in `WHERE`**: `${orders.status} = "Complete" OR ${orders.is_override}`

---

## 3. LookML Expressions (`test:` `assert:` vs. NDT `expression_custom_filter:`)

LookML files embed Looker expressions (terminated by `;;`) in two distinct parameters with **different** engines:

### A. LookML Data Tests: `test: { assert: { expression: ... ;; } }` (in-memory)

Defined in `tests/bronze/*.test.lkml` and `tests/silver/*.test.lkml` and executed via Looker SDK `run_lookml_test(project_id=..., file_id=..., test=...)` ([lookml-tests](../lookml/sub-skills/lookml-tests/SKILL.md), [agentic-lookml](../agentic-lookml/SKILL.md)):
- Uses the **post-query Table Calculation engine** (all functions except `matches_filter()` are supported; `explore_source:` caps results at `5,000` rows).
- Every `${view.field}` in `expression:` **must** be fully scoped (`${orders.count}`, never `${count}`) and projected as a `column:` in `explore_source:`.
- Passes only if `expression:` evaluates to `yes` for **every row** returned by `explore_source:`.

```lookml
# Immutable historical slice equality + rounding (tests/bronze/order_items_base.test.lkml)
test: order_items_base_2024_01_01_metrics {
  explore_source: order_items_base {
    column: total_sale_price { field: order_items.total_sale_price }
    column: count { field: order_items.count }
    filters: [order_items.created_date: "2024-01-01"]
  }
  assert: total_sale_price_matches {
    expression: round(${order_items.total_sale_price}, 2) = 4520.25 ;;
  }
  assert: order_item_count_matches {
    expression: ${order_items.count} = 84 ;;
  }
}

# Open-state algebraic invariants (never assert frozen constants on open states like is_sold: "no")
test: inventory_open_state_invariants {
  explore_source: inventory_items {
    column: sunk_dusty_shelf_cost { field: inventory_items.sunk_dusty_shelf_cost }
    column: total_cost { field: inventory_items.total_cost }
    filters: [inventory_items.created_date: "2024-01-01"]
  }
  assert: sunk_cost_bounded_by_total {
    expression: NOT is_null(${inventory_items.sunk_dusty_shelf_cost})
      AND ${inventory_items.sunk_dusty_shelf_cost} >= 0
      AND ${inventory_items.sunk_dusty_shelf_cost} <= ${inventory_items.total_cost} ;;
  }
}
```

### B. Native Derived Table `expression_custom_filter:` (SQL pushdown)

Inside `derived_table: { explore_source: ... }` ([lookml-view derived_table](../lookml/sub-skills/lookml-view/references/derived_table.md)), use `filters:` ([looker-filters](../looker-filters/SKILL.md)) for single-field predicates and `expression_custom_filter:` (**dimensions only**, SQL pushdown) when the NDT `WHERE` clause compares two dimensions or combines dimensions with `OR`:

```lookml
explore_source: order_items {
  column: user_id { field: order_items.user_id }
  column: first_year_revenue { field: order_items.total_sale_price }
  expression_custom_filter: ${order_items.created_year} = ${users.created_year} ;;
}
```

*(By contrast, `derived_column: { sql: RANK() OVER (ORDER BY first_year_revenue DESC) ;; }` inside `explore_source:` uses **warehouse SQL** over inner column aliases—not Looker expressions.)*

---

## 4. Function and operator summary

- **All contexts (SQL pushdown & in-memory)**:
  - **Logical & branching**: `=`, `!=`, `<`, `<=`, `>`, `>=`, `AND`, `OR`, `NOT`, `yes`, `no`, `null`, `if(cond, if_yes, if_no)`, `case(when(c1, v1), when(c2, v2), else_v)`, `coalesce(v1, v2, ...)`, `is_null(x)`.
  - **Math & string**: `+`, `-`, `*`, `/` (guard `if(b = 0, null, a / b)`), `abs`, `ceiling`, `floor`, `round(x, digits)`, `sqrt`, `power(base, exp)`, `mod(x, div)`, `exp`, `ln`, `log`, `rand()`, `concat(s1, s2, ...)`, `contains(str, needle)` (case-sensitive), `position(str, needle)`, `length`, `lower`, `upper`, `replace(str, old, new)`, `substring(str, start_1based, len)`.
  - **Date & time**: `now()`, `date(y, m, d)`, `date_time(y, m, d, h, min, s)`, `add_days`/`add_months`/`add_years`/`add_hours`/`add_minutes`/`add_seconds(n, d)` (`n` first), `diff_days`/`diff_months`/`diff_years`/`diff_hours`/`diff_minutes`/`diff_seconds(start_d, end_d)` (`end - start`), `extract_*`, `trunc_*`.
- **SQL pushdown ONLY** (Custom Filters, Custom Fields, NDT `expression_custom_filter:`): ``matches_filter(${view.field}, `filter_expr`)``.
- **Post-query in-memory ONLY** (Table Calculations & `.test.lkml` `assert:`): `${field:total}`, `${field:row_total}`, `row()`, `offset(col, k)`, `offset_list(col, k, len)`, `index(col, n)`, `match(val, col)`, `lookup(val, lookup_col, result_col)`, `list(...)`, `pivot_column()`, `pivot_index`, `pivot_offset`, `pivot_offset_list`, `pivot_row`, `pivot_where`, `sum`, `running_total`, `mean`, `median`, `min`, `max`, `count`, `count_distinct`, `rank`, `percentile`, `to_number`, `to_string`, `to_date`, `split`.
- Full signature notes, statistical/distribution functions, and 1:1 Microsoft Excel equivalents: see [references/excel-equivalents.md](references/excel-equivalents.md).

## Public references

- [Create Looker expressions](https://docs.cloud.google.com/looker/docs/creating-looker-expressions)
- [Looker functions and operators](https://docs.cloud.google.com/looker/docs/functions-and-operators)
- [Using table calculations](https://docs.cloud.google.com/looker/docs/table-calculations)
- [Adding custom fields](https://docs.cloud.google.com/looker/docs/custom-fields)
- [`matches_filter` function](https://docs.cloud.google.com/looker/docs/matches-filter)
- [`test` parameter (LookML data tests)](https://docs.cloud.google.com/looker/docs/reference/param-model-test)
