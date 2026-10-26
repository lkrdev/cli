---
name: looker-filters
description: >
  Looker Filter Expressions, Custom Filters, and LookML/SDK filtering guide (`looker-filters`).
  Covers single-field filter expression strings (strings, wildcards, `^` escaping, relative and absolute dates,
  numeric intervals, `"NULL"` vs `"-NULL"` vs `"NOT NULL"`, booleans, locations, and user attributes),
  Custom Filters (`filter_expression` and NDT `expression_custom_filter:`), where `filters:` maps work across LookML
  (`measure`, `explore` Quick Start `query:`, `always_filter:`, `aggregate_table:`, NDT and `.test.lkml` `explore_source:`,
  `.dashboard.lookml`), and Looker SDK query/dashboard filter methods (`run_inline_query`, `create_query`,
  `create_dashboard_filter`, `update_dashboard_filter`). Use when writing, debugging, or reviewing Looker filter strings,
  Custom Filters, filtered measures, Explore filters, NDT/test slice filters, or SDK query filter payloads.
---

# Looker Filters (`looker-filters`)

## Choosing the right Looker filter mechanism

Looker supports single-field **Filter Expressions**, multi-field **Custom Filters**, and LookML SQL/Liquid filter blocks. Pick the simplest mechanism that matches the predicate:

| Filtering need | Mechanism | Syntax | Where it lives |
| :--- | :--- | :--- | :--- |
| Single-field match, list (`OR`), range, wildcard, null check, or relative/absolute date | **Looker Filter Expression** ([docs](https://docs.cloud.google.com/looker/docs/filter-expressions)) | Quoted shorthand string per field (`"this year"`, `"-Cancelled"`, `"[0, 5]"`, `"-NULL"`); multiple fields combine with `AND` | `measure: { filters: [...] }`, `explore: { query: { filters: [...] } }`, `always_filter:`, `aggregate_table:`, NDT & `.test.lkml` `explore_source: { filters: [...] }`, `.dashboard.lookml`, `run_inline_query` / `create_query` `body["filters"]` |
| Cross-field comparison (`${orders.created_year} = ${users.created_year}`) or cross-column `OR` (`status = 'Complete' OR is_override`) at query/NDT time | **Custom Filter** ([looker-expressions](../looker-expressions/SKILL.md)) | Boolean Looker expression referencing dimensions only (`${orders.created_year} = ${users.created_year}`) | `run_inline_query` / `create_query` `body["filter_expression"]`, Explore Custom Filter UI, or NDT `explore_source: { expression_custom_filter: ... ;; }` |
| Reusable cross-column `OR` inside a LookML `measure` | **Hidden `type: yesno` helper + `filters:`** ([02-conditional-measures-and-bucketing.md](../agentic-lookml/references/02-conditional-measures-and-bucketing.md)) | `dimension: is_completed_or_override { type: yesno hidden: yes sql: ... ;; }` + `filters: [is_completed_or_override: "yes"]` | `bronze/:table.refinement.lkml` or `silver/:view_a_:view_b_fields.view.lkml` |
| Embed a Filter Expression inside a Custom Field or Custom Filter formula | **`matches_filter()` bridge** ([docs](https://docs.cloud.google.com/looker/docs/matches-filter), [looker-expressions](../looker-expressions/SKILL.md)) | ``matches_filter(${orders.created_date}, `30 days`)`` (backticks required) | Custom Dimensions, Custom Measure filters, Custom Filters |
| Mandatory row-level security by user attribute | **`access_filter:`** ([lookml-explore](../lookml/sub-skills/lookml-explore/references/advanced.md)) | `access_filter: { field: view.field user_attribute: attr_name }` (`access_grant:` takes literal `allowed_values`, never Filter Expressions) | `.explore.lkml` |
| Push Explore runtime filters into an inner derived table | **`bind_all_filters` / `bind_filters` or Gold Liquid `{% condition %}`** ([14-templated-filters-and-parameters.md](../agentic-lookml/references/14-templated-filters-and-parameters.md)) | `bind_all_filters: yes` on NDT (same filters as outer query) or `filter:` + `{% condition %}` + `always_filter:` in `gold/` (asymmetric cohort vs. population) | `gold/:name.view.lkml` + `gold/explores/:name.explore.lkml` ([lookml-liquid](../lookml/sub-skills/lookml-liquid/SKILL.md)) |

---

## Looker Filter Expression syntax by data type

In LookML (`filters: [...]`), **always wrap the entire filter expression in double quotes** (`"..."`)—especially `"NULL"`, `"-NULL"`, and `"NOT NULL"`. In the Explore UI (`matches (advanced)`) and SDK `body["filters"]` values, omit the outer LookML quotes.

### 1. Strings (`type: string`)

String matching honors the model's `case_sensitive` setting and database dialect sensitivity.

| Expression (in LookML quotes) | Meaning | Notes & traps |
| :--- | :--- | :--- |
| `"Complete"` | Exact match (`= 'Complete'`) | |
| `"Socks,Socks & Hosiery"` | Exact `OR` (`IN ('Socks', 'Socks & Hosiery')`) | Comma `,` means `OR`. Avoid unintended spaces after `,` unless matching a leading space. |
| `"%cancel%"` / `"FOO%"` / `"%FOO"` | Contains / starts with / ends with | `%` matches zero or more characters; `_` matches any single character (`"_UF"`). |
| `"-Cancelled"` | Not equal (`!= 'Cancelled'` or `IS NULL`) | Leading `-` negates the token. |
| `"-Cancelled,-Returned"` | Neither `'Cancelled'` nor `'Returned'` | Comma-separated negated terms become `AND NOT` exclusions. |
| `"FOO%,-FOOD"` | Starts with `'FOO'` and is not `'FOOD'` | Combines positive prefix with `-` exclusion. |
| `"-FOO%"` / `"-%FOO%"` | Does not start with / does not contain `'FOO'` | |
| `"NULL"` / `"-NULL"` | `IS NULL` / `IS NOT NULL` | **Always use `"-NULL"` on `type: string`**—writing `"NOT NULL"` on a string dimension matches the literal string `'NOT NULL'`. |
| `"EMPTY"` / `"-EMPTY"` | Empty string `''` or `NULL` / non-empty (`LENGTH >= 1`) | Use `"-EMPTY"` for SQL `col != '' AND col IS NOT NULL`. |

**Escaping special characters with `^`:**
- Escape literal `"`, `%`, `_`, `,`, or `^` in LookML filter expressions and `matches (advanced)` with `^`: `"^_items"`, `"100^%"`, `"Santa Cruz^, CA"`, `"^^"`, `"^""`.
- Escape a leading `-` (or leading space) only when it is the **first** character: `"^-100"` (hyphens inside `"e-commerce"` need no escape).
- *(Standard Explore UI dropdown filters escape literal commas with `\` as `Santa Cruz\, CA`; LookML `filters:` and `matches (advanced)` always use `^,`.)*

### 2. Dates and times (`dimension_group` timeframes & `type: date*`)

| Pattern | Example | Bound semantics & behavior |
| :--- | :--- | :--- |
| `today` / `yesterday` / `tomorrow` | `"today"` | Full calendar day (`00:00:00` through `23:59:59`). **Never write `"this day"`** (unsupported—use `"today"`). |
| `this {interval}` | `"this week"`, `"this month"`, `"this quarter"`, `"this year"` | Full current calendar period (Looker weeks start Monday unless `week_start_day` is set). |
| `last {interval}` / `{n} {interval} ago` | `"last month"`, `"1 week ago"`, `"2 years ago"` | Single complete prior period (`"2 years ago"` in 2026 = all of `2024`). |
| `{n} {interval}` / `last {n} days` | `"7 days"`, `"3 months"`, `"2 years"` | Rolling window **including the current partial period** (`"3 days"` = today + prior 2 days). |
| `{n} {interval} ago for {m} {interval}` | `"7 days ago for 7 days"` | **Complete prior periods only**, excluding today's partial period. |
| `this {interval} to {interval}` | `"this year to second"`, `"this week to day"` | Start of first interval to start of second interval (YTD / WTD). |
| `after {time}` | `"after 2024-01-01"` | **Inclusive lower bound (`>=`)**: includes `2024-01-01 00:00:00` and later. |
| `before {time}` / `before {n} {interval} ago` | `"before 2024-01-01"`, `"before 3 days ago"` | **Exclusive upper bound (`<`)**: strictly before `2024-01-01 00:00:00` (excludes `2024-01-01`). |
| `{time} to {time}` | `"2024-01-01 to 2024-07-01"` | **Half-open `[start, end)`**: includes start, **excludes** end (`2024-01-01 00:00:00` through `2024-06-30 23:59:59`). |
| `{time} for {n} {interval}` | `"2024-05-10 for 3 days"` | Inclusive of the full span (`2024-05-10 00:00:00` through `2024-05-12 23:59:59`). |
| `{YYYY}` / `{YYYY-MM}` / `{YYYY-MM-DD}` / `{YYYY-Q#}` | `"2024"`, `"2024-01"`, `"2024/05/29"`, `"2024-Q4"` | Matches the full year, month, day, or quarter. **Always zero-pad hyphenated months/days** (`"2024-01"`, never `"2024-1"`, which Looker parses as `2024 - 1 = 2023`). |
| Fiscal periods | `"FY2024"`, `"FY2024-Q1"`, `"last fiscal quarter"`, `"this fiscal year"` | Requires `fiscal_month_offset` on the model. |
| Future windows | `"next week"`, `"3 days from now"`, `"3 days from now for 2 weeks"` | `next` supports `week`, `month`, `quarter`, `fiscal quarter`, `year`, `fiscal year` only. |
| `{day_of_week}` | `"Monday"`, `"after Monday"` | On a `_date` field, matches the most recent Monday; on a `_day_of_week` field, matches every Monday. |

- **Combining date conditions:** Join with `,` inside one filter for `OR` (`"today, 7 days ago"`). For `AND` bounds that cannot be written as `{start} to {end}` or `{start} for {n}`, filter two timeframes of the same `dimension_group` (`created_date: "after 2024-01-01", created_time: "before 2 days ago"`).
- **Timestamp/date `NULL` checks:** Rather than filtering `${<group>_date}: "NULL"` (which applies `DATE()` / timezone casts), define one positive `type: yesno` dimension on the `raw` timeframe (`is_sold` -> `sql: ${sold_raw} IS NOT NULL ;;`) and filter `is_sold: "no"` or `"yes"` ([02-conditional-measures-and-bucketing.md](../agentic-lookml/references/02-conditional-measures-and-bucketing.md)).

### 3. Numbers (`type: number`, numeric `tier` / `duration`, and numeric `measure` `HAVING` filters)

| Expression | Meaning | Notes & traps |
| :--- | :--- | :--- |
| `"5"` / `"1, 3, 5, 7"` | `= 5` / `IN (1, 3, 5, 7)` | Comma `,` or `OR` joins alternatives (`"<25, >65"`). |
| `">100"` / `">=30"` / `"<=10"` / `"!=5"` / `"<>5"` / `"NOT 5"` | Relational comparisons | Works on both numeric dimensions (`WHERE`) and measures (`HAVING`, e.g. `orders.count: ">=30"`). |
| `">=18 AND <=25"` / `"5.5 to 10"` / `"1 to"` / `"to 10"` | Inclusive range (`18 <= x <= 25`, `>= 1`, `<= 10`) | Combine ranges with `OR`: `">=50 AND <=100 OR >=500 AND <=1000"`. |
| `"[0, 5]"` / `"(1, 7)"` / `"[12, 20)"` / `"(12, 20]"` | Algebraic interval notation | `[` / `]` = inclusive; `(` / `)` = exclusive (`"[0, 5]"` -> `0 <= x <= 5`). |
| `"(500,)"` / `"(500, inf)"` / `"(,10]"` / `"[0,9],[20,29]"` | Open-ended or union intervals | `inf` is always open `(` / `)`. |
| `"NULL"` / `"NOT NULL"` | `IS NULL` / `IS NOT NULL` | **On `type: number`, use `"NOT NULL"`** (e.g. `orders.id: "NOT NULL"` to enforce inner-join semantics on a `left_outer` Explore). |

- **Leading-`NOT` trap on numbers:** If the first comma-separated item has `NOT` and later items do not, Looker negates **every** item (`"NOT 66, 99, 4"` means `NOT IN (66, 99, 4)`, while `"NOT >1, <100"` negates both into `<=1 AND >=100`, which compiles to `IS NULL`). Put positive clauses first (`">1 AND <100, NOT 2"`).

### 4. Booleans (`type: yesno` vs. database booleans)

- **`type: yesno` fields:** Use `"yes"` or `"no"` (or `"Yes"` / `"No"` in `filters:` / `always_filter:`). Enforce positive polarity on field names (`is_sold: "no"`, never `is_unsold: "yes"`).
- **Raw boolean columns (non-`yesno`):** Use `"TRUE"` or `"FALSE"`.

### 5. Locations (`type: location`) & User Attributes

- **Locations:** `"36.97, -122.03"` (exact), `"40 miles from 36.97, -122.03"` (units must be plural: `meters`, `feet`, `kilometers`, `miles`—even `"within 1 miles of 36.97, -122.03"`), `"inside box from 72.33, -173.14 to 14.39, -61.70"`, `"NULL"`, `"-NULL"`, `"NOT NULL"`.
- **User attributes inside filter strings:** `"{{ _user_attributes['region'] }}"` or prefixed `"sf_{{ _user_attributes['salesforce_username'] }}"` in Explore `matches (advanced)` and `.dashboard.lookml` filters.

---

## Custom Filters (`filter_expression` & `expression_custom_filter:`)

Single-field `filters:` maps always join multiple fields with `AND` and cannot compare one column against another. Switch to a **Custom Filter** whenever SQL `WHERE` needs cross-field comparisons or cross-column `OR` logic:

- **Rules:** Custom Filters use [looker-expressions](../looker-expressions/SKILL.md) syntax, must evaluate to `yes` or `no`, compile into warehouse SQL `WHERE`, and can reference **dimensions only** (never measures, totals, positional/pivot functions, or table calculations).
- **Bridge single-field shorthand with `matches_filter`:** Wrap Filter Expressions in backticks inside a Custom Filter:
  ```text
  (${orders.created_year} = ${users.created_year})
    AND (matches_filter(${orders.status}, `Complete,Shipped`) OR ${orders.is_override})
  ```
- **Where authored:**
  1. **SDK query `body["filter_expression"]`** (`run_inline_query` / `create_query`): Passed alongside or instead of `body["filters"]` (when both are set, Looker combines them with `AND`).
  2. **LookML NDT `expression_custom_filter:`** inside `derived_table: { explore_source: ... }`:
     ```lookml
     explore_source: order_items {
       column: user_id { field: order_items.user_id }
       column: first_year_revenue { field: order_items.total_sale_price }
       filters: [order_items.status: "-Cancelled"]
       expression_custom_filter: ${order_items.created_year} = ${users.created_year} ;;
     }
     ```
  3. **Custom Measure `filter_expression`** inside `body["dynamic_fields"]` (filters a single ad-hoc measure without filtering the whole query).

---

## Using filters in LookML and Looker SDK methods

### 1. LookML Filtered Measures (`bronze/:table.refinement.lkml` & `silver/*_fields.view.lkml`)

`measure` `filters:` works **only** on aggregating measure types (`count`, `count_distinct`, `sum`, `average`). **Never place `filters:` on `type: number`**—filter the underlying `sum`/`count` component measures instead ([param-field-filters](https://docs.cloud.google.com/looker/docs/reference/param-field-filters)). Multiple `filters:` entries combine with `AND`; for cross-column `OR`, filter on a `hidden: yes` `type: yesno` dimension:

```lookml
# bronze/orders.refinement.lkml
include: "orders.view.lkml"

view: +orders {
  dimension: is_returned {
    type: yesno
    sql: ${returned_raw} IS NOT NULL ;;
  }

  dimension: is_ever_returned {
    type: yesno
    hidden: yes
    sql: ${status} = 'Returned' OR ${is_returned} ;;
  }

  measure: completed_revenue {
    type: sum
    sql: ${sale_price} ;;
    filters: [status: "Complete", created_date: "this year"]
    value_format_name: usd
  }

  measure: returned_order_count {
    type: count
    filters: [is_ever_returned: "yes"]
  }

  # Ratio over filtered data: filter atomic sum/count measures, NEVER type: number
  measure: completed_order_count {
    type: count
    filters: [status: "Complete"]
    hidden: yes
  }

  measure: completed_average_order_value {
    type: number
    sql: 1.0 * ${completed_revenue} / NULLIF(${completed_order_count}, 0) ;;
    value_format_name: usd
    tags: ["non_additive"]
  }
}
```

### 2. Explore Quick Start `query:`, `always_filter:`, NDTs, and Data Tests

- **Quick Start `query:` blocks** (`bronze/explores/` or `silver/explores/`): Accept `filters:` on both dimensions (`WHERE`) and measures (`HAVING`), e.g. `filters: [orders.status: "-Cancelled", orders.count: ">=30"]` or relative Business Term slices like `filters: [users.created_year: "this year"]` ([agentic-lookml](../agentic-lookml/SKILL.md)).
- **`always_filter:`** ([lookml-explore](../lookml/sub-skills/lookml-explore/SKILL.md)): Enforces an editable default filter on partitioned Bronze tables or parameterized Gold Explores (`always_filter: { filters: [events.created_date: "7 days"] }`).
- **NDT `explore_source:`** ([lookml-view derived_table](../lookml/sub-skills/lookml-view/references/derived_table.md)): Supports `filters:`, dev-only `dev_filters:`, `bind_all_filters: yes`, `bind_filters: { from_field: ... to_field: ... }`, and `expression_custom_filter:`.
- **Data Tests (`.test.lkml`)**: Bound equality assertions to a deterministic historical slice using `filters: [orders.created_date: "2024-01-01"]` (or block syntax `filters: { field: orders.created_date value: "2024-01-01" }`).

### 3. Looker SDK Query & Dashboard Filter Methods ([lkr-code-mode](../lkr-code-mode/SKILL.md))

When executing or saving queries via `run_inline_query(result_format="json", body=...)`, `create_query(body=...)` (+ `run_query(query_id=..., result_format="json")`), or `create_query_task(body=..., result_format="json")`, the query `body` dictionary controls filtering through four keys:

| Query `body` key | Type | Purpose & behavior |
| :--- | :--- | :--- |
| `"filters"` | `dict[str, str]` | Map of `"view.field": "filter_expression"` combined with `AND` (`WHERE` for dimensions/filter fields, `HAVING` for measures). Omit outer LookML quotes (`"-NULL"`, not `"\"-NULL\""`). |
| `"filter_expression"` | `str` | Custom Filter written as a boolean [looker-expressions](../looker-expressions/SKILL.md) formula over dimensions (`"${orders.created_year} = ${users.created_year}"`). Required when `OR` spans multiple fields or two fields are compared; `AND`ed with `"filters"` when both are set. |
| `"filter_config"` | `None` | Opaque Explore UI filter bar state. **Always omit or set `"filter_config": None` (`null` in JSON)** when creating or modifying queries via SDK—a non-null `filter_config` overrides `"filters"`. |
| `"dynamic_fields"` | `str` (JSON array) | Optional JSON-encoded list of Custom Fields; custom `"measure"` entries accept `"filter_expression"` (Looker expression) or `"filters"` to scope that single metric without filtering the whole query. |

```python
# Executed via `lkr --dev code-mode sandbox`
import json

body = {
    "model": "agentic_thelook",
    "view": "orders",
    "fields": ["users.country", "orders.count", "orders.total_revenue"],
    "filters": {
        "orders.status": "-Cancelled",
        "users.email": "-NULL",
        "orders.count": ">=30",
    },
    "filter_expression": "${orders.created_year} = ${users.created_year}",
    "filter_config": None,
    "sorts": ["orders.total_revenue desc"],
    "limit": "20",
}
rows = json.loads(run_inline_query(result_format="json", body=body))
```

- **Dashboard filter SDK methods & `.dashboard.lookml`:** Use `create_dashboard_filter(body=...)` / `update_dashboard_filter(dashboard_filter_id=..., body=...)` (`"default_value"` takes a Filter Expression string) and wire tiles via `listen` on `create_dashboard_element` / `update_dashboard_element` (or `filters:` + `listen:` in `.dashboard.lookml`).

## Public references

- [Looker filter expressions](https://docs.cloud.google.com/looker/docs/filter-expressions)
- [Create Looker expressions (Custom filters)](https://docs.cloud.google.com/looker/docs/creating-looker-expressions)
- [`filters` (measure parameter)](https://docs.cloud.google.com/looker/docs/reference/param-field-filters)
- [`explore_source` (NDT `filters`, `dev_filters`, `expression_custom_filter`, `bind_filters`, `bind_all_filters`)](https://docs.cloud.google.com/looker/docs/reference/param-view-explore-source)
- [`matches_filter` function](https://docs.cloud.google.com/looker/docs/matches-filter)
