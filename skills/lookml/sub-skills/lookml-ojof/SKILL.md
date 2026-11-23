---
name: lookml-ojof
description: Design, build, refactor, and optimize multi-fact LookML Explores using the Outer Join On False (OJOF) pattern. Eliminates cartesian fanouts, chasm traps, and symmetric aggregate overhead across disparate data grains.
---

# LookML "Outer Join On False" (OJOF) Skill

## 1. Overview

### Problem

When querying multiple independent fact tables with different grains (e.g. Sales Orders, Line-Item Fulfillment, Inventory, Web Events) in a standard Looker explore, joins cause **cartesian fanouts**, **chasm traps**, or require heavy **symmetric aggregate calculations**.

### Solution

The OJOF Pattern solves this by treating fact tables as parallel peers connected to a 0-row dummy table, dynamically binding shared dimensions and co-dimensions via Liquid.

```
       [ none (0 rows) ]
       /       |       \
FULL OUTER  FULL OUTER  FULL OUTER
sql_on:FALSE sql_on:FALSE sql_on:FALSE
    /          |          \
[Fact A]   [Fact B]    [Fact C]
    \          |          /
     \         |         /
      LEFT OUTER (Liquid COALESCE)
               |
      [Shared Dimension / Co-dim]
```

### Caveats and Assumptions

The OJOF pattern works well when all dimensional joins are directly against fact tables, like a star schema, rather than indirect or multi-level (like a snowflake schema). This is because some dynamically written join conditions will be opaque to Looker's referential system and Looker will be unable to determine when intermediate dimension tables should participate in a query. A direct dimensional schema can normally be derived from a multi-level dimensional schema by pre-joining the foreign keys to distant dimensions directly onto the fact tables.


This pattern has been tested primarily in BigQuery. Other SQL engines/dialects may or may not support this query pattern.

---

## 2. How to Read and Apply These Examples

Always keep this in mind when reading the example LookML snippets in this guide:

- Examples may show related declarations side-by-side. For example, an explore and a view that it references. However, in practice, these are often maintained in separate files.
- Examples include **only the LookML paramaters being illustrated** in the given section, and should not be interpreted as being complete on their own.

## 3. Explore Structure

### Rule 1: The 0-Row Base (`from: none`)
The explore root MUST be a table-valued expression returning 0 rows:
```lookml
view: none {
  derived_table: {
    sql: SELECT NULL FROM UNNEST([]) ;;
  }
}
explore: multi_fact {
  from: none
}
```

### Rule 2: Fact/Measure Joins
Every fact table is joined with `type: full_outer`, `relationship: one_to_one`, and `sql_on: FALSE ;;`:
```lookml
join: orders {
  type: full_outer
  relationship: one_to_one
  sql_on: FALSE ;;
}

join: web_sessions {
  from: web_sessions
  type: full_outer
  relationship: one_to_one
  sql_on: FALSE ;;
}
```

- These joins are organized towards the top of the explore declaration.
- They are conventionally (but not necessarily) aliased as plural.
- Fact tables are often large and have partition columns to prune data. Fact/measure joins will often explicitly apply filters to these partition columns. See the section titled "Filter Push Downs" for examples.

### Rule 3: Composite Measure Joins
Whenever a measure field should be calculated as an expression across multiple fact tables, these measures should be organized into a field-only view and joined into the explore with a bare join.
```lookml
view: orders {}
view: web_sessions {}
view: orders__web_sessions {
  measure: session_to_order_conversion_rate {
    type: number
    sql: ${orders.count} / NULLIF(${sessions.count}, 0) ;;
  }
  measure: session_average_order_value {
    type: number
    sql: ${orders.total_value} / NULLIF(${sessions.count}, 0) ;;
    value_format_name: usd
  }
}
explore: multi_fact {
  # Composite measure joins
  join: orders__web_sessions {
    view_label: "Orders"
    relationship: one_to_one
    sql: ;; # Bare join results in no actual join change in the SQL
  }
}

```

- These joins (if any) should be declared within the explore following all fact/measure join declarations. 
- For best re-usability of composite measures, composite measure fields can be organized into views that are named after the set of referenced fact tables, as in the above example.
- To avoid creating excessive view names in the field picker, view_label should be used in the join to merge field labels into the most closely related fact view.
- The join's `type` is immaterial.


### Rule 4: Dimension Joins (`COALESCE` + Liquid)
Shared dimension tables (e.g. Customer, Product, Supplier, Geography) join conditionally to whichever fact table is currently active in the user query:
```lookml
join: customer {
  type: left_outer
  relationship: many_to_one
  sql_on: ${customer.id} = COALESCE(
    {% if orders._in_query %} orders.customer_id, {% endif %}
    {% if web_sessions._in_query %} web_sessions.customer_id, {% endif %}
    NULL
  ) ;;
}
```
- Dimension joins should be declared within the explore following all fact/measure and composite measure joins.
- Dimension joins are conventionally (but not necessarily) aliased as singular.
- Like any many_to_one join, the participating field(s) from the table being joined MUST be unique within that table, preferably the primary key or other field whose uniqueness is guaranteed by the table definition.
- Unlike standard Looker practice, the participating fields from the referenced fact/measure joins MUST NOT be referenced using Looker's `${}` substitution operator, as this would cause Looker to unconditionally include all referenced fact/measure joins. Instead, the reference must be conditional using a liquid `{% if join_name._in_query %}` expression and a raw SQL expression of join_name.column_name.
- A trailing NULL is included in the COALESCE to avoid a syntax error on the trailing commas.

### Rule 5: Co-Dimension Joins
Co-dimension joins are lateral joins that unify/coalesce dimension fields that are shared among multiple tables. Explores will often include a co-dimension join for date or timestamp fields, if there is not an explicit date dimension table.
```lookml
explore: multi_fact {
  join: date {
    type: cross
    relationship: one_to_one
    sql_table_name: UNNEST([COALESCE(
      {% if orders._in_query %} DATE(orders.order_timestamp), {% endif %}
      {% if web_sessions._in_query %} web_sessions.snapshot_date, {% endif %}
      CAST(NULL AS DATE)
    )]) ;;
    # In BigQuery, JOIN UNNEST([expression]) is effectively a lateral join
  }
}
view: date {
  label: "[Date]"
  dimension_group: _ {
    type: time
    datatype: date
    timeframes: [raw, date, week, month, quarter, year]
    sql: ${TABLE} ;; #This resolves to the join alias, which is the lateral join expression
  }

  # For use with partitioned columns, define a `date_filter` field from ONE of the two options below:
  # Option A (Standard): As a filter
  filter: date_filter {
    label: "Date Limit"
    hidden: yes # For use with always_filter
    type: date
    datatype: date
    # True if null, i.e. applied to a row with no date column
    sql: COALESCE({% condition %} ${TABLE} {% endcondition %}, TRUE) ;;
  }
  # Option B: As a dimension (ONLY if needed for aggregate awareness tables)
  # dimension: date_filter {
  #   label: "Date Limit"
  #   hidden: yes
  #   type: date
  #   datatype: date
  #   sql: ${TABLE} ;;
  # }
}
```

- Co-dimension joins should be the last joins declared in the explore.
- For re-usability, the co-dimension view usually does not declare its own sql_table_name. Instead, the explore join is responsible for binding the co-dimension view to the specific tables participating in the explore via the join's sql_table_name.
- The `date_filter` field can be defined one of two ways:
  - As a filter: `filter: date_filter {}` handles non-date related records in a way that is usually more intuitive for users
  - As a dimension: `dimension: date_filter {}` works inside aggregate awareness tables.

## 4. Additional Patterns 

### Filter Push-Down

When partition columns are available, relevant filters should be pushed down in the query closer to the table:
```lookml
    sql_table_name: (
      SELECT * FROM table
      WHERE order_date >= {% date_start date.date_filter %}
        AND order_date <= {% date_end   date.date_filter %}
    );;
```

- For models that are clean and consistent in naming conventions, the push-down can be specified in the view, since the join alias for the field can be relied upon to be consistent across explores. For less consistent models, the push-down can be specified in the join.
- As is standard Looker practice, this is often combined with explore -> always_filter
- Looker will unnecessarily error if a join's sql_table_name attempts to refer to ${view_name.SQL_TABLE_NAME} and the join name and the view name are the same. Filter pushdowns may frequently run into this error. If this situation arises, change either the view name or the join alias to avoid this, or simply reference the raw SQL name of the table.


## Dual-Use Tables

A dimension table that applies to measures from other tables may also have measures that should be dimensioned by other tables in the explore.

In these cases, the table may be joined into the explore twice. The convention is to name the fact/measure join as a plural and the dimension join as singular. The join -> fields parameter should be used to expose measure fields from the fact/measure join and dimension fields from the dimension join. 

```lookml
view: users{
  set: dimensions { fields: [email,age,country] }
  set: measures { fields: [count,lifetime_order_value] }
}
explore: multi_fact {
  # Fact/measure joins
  join: orders {
    type: outer_join
    relationship: one_to_one
    sql_on: FALSE ;;
  }
  join: users {
    type: outer_join
    relationship: one_to_one
    fields: [measures*]
    sql_on: FALSE ;;
  }
  # Dimension joins
  join: user {
    type: left_outer
    relationship: many_to_one
    fields: [dimensions*]
    sql_on: ${user.id} = COALESCE(
      {% if orders._in_query %} orders.user_id, {% endif %}
      ${users.id}
      ) ;;
    # `user` always pulls `users` into the query base by reference
    # This requires a physical self-join, so avoid this pattern for large fact tables
  }
  join: account {
    type: left_outer
    relationship: many_to_one
    sql_on: ${account.id} = COALESCE(
      {% if orders._in_query %} orders.account_id, {% endif %}
      {% if users._in_query %} users.account_id, {% endif %}
      NULL
    )
  }
}
```

### Aggregate Awareness

Aggregate tables work naturally on top of OJOF explores. For example:

```lookml
explore: +multi_fact {
  aggregate_table: monthly_category_rollup {
    query: {
      dimensions: [product.category, date.date_month]
      measures: [orders.total_revenue, line_items.total_quantity, inventories.total_stock]
    }
    materialization: {
      datagroup_trigger: monthly_etl
    }
  }
}
```

- For explores that apply an always_filter, prioritize being able to place the always filtered field into the dimensions of the aggregate table.

### Multi-Date Entities 

When an entity's lifecycle contains multiple event dates or milestones (e.g. sales opportunities with `created_date` and `closed_date`), it is often unclear which field a date co-dimension should group by. Worse, users explicitly grouping by one milestone can break filtered measures on the other milestones. E.g. a query with dimension "Created Date" and measure "Opportunities Closed" would only count opportunities closed in the same timeframe they were created.

A flexible solution is to instantiate multiple fact/measure joins on the table, aliased by milestone, and independently aligned to the date co-dimension:

```lookml
explore: sales_pipeline {

  # Fact/measure joins
  join: opps_created {
    from: opportunities
    view_label: "Opportunities Created"
  }
  join: opps_closed {
    from: opportunities
    view_label: "Opportunities Closed"
  }

  # Co-dimension joins
  join: date {
    sql_table_name: UNNEST([COALESCE(
      {% if opps_created._in_query %} opps_created.created_date, {% endif %}
      {% if opps_closed._in_query  %} opps_closed.closed_date,  {% endif %}
      CAST(NULL AS DATE)
    )]) ;;
  }
}
```

This allows querying a single date dimension (e.g., `date.date_month`) alongside `opps_created.count` and `opps_closed.count` simultaneously without row fanout or cross-filtering interference.

### User-Defined Period Over Period

Here, the user provides two explicit filter inputs to select arbitrary time ranges for comparison. Two separate co-dimension joins (`date` and `date_prior`) track the dates for each period.

```lookml
explore: multifact_pop {
  # Fact/measure joins
  join: orders {
    sql_table_name: (
      SELECT * FROM <table>
      WHERE order_date >= {% date_start date.date_filter %}
        AND order_date <= {% date_end   date.date_filter %}
    ) ;;
  }
  join: orders_prior {
    sql_table_name: (
      SELECT * FROM <table>
      WHERE order_date >= {% date_start date_prior.date_filter %}
        AND order_date <= {% date_end   date_prior.date_filter %}
    ) ;;
  }

  # Co-dimension joins
  join: date {
    sql_table_name: UNNEST([COALESCE(
      {% if orders._in_query %} DATE(orders.order_date), {% endif %}
      CAST(NULL AS DATE)
    )]) ;;
  }

  join: date_prior {
    from: date
    view_label: "[Date] (Prior)"
    sql_table_name: UNNEST([COALESCE(
      {% if orders_prior._in_query %} DATE(orders_prior.order_date), {% endif %}
      CAST(NULL AS DATE)
    )]) ;;
  }
}
```

### Pre-Defined Period Over Period

Here, the user provides a single date filter input and one or more prior period fact tables automatically shift their filter windows in SQL.

```lookml
explore: orders_pop {
  # Fact/measure joins
  join: orders {
    sql_table_name: (
      SELECT * FROM table
      WHERE order_date >= {% date_start date.date_filter %}
        AND order_date <= {% date_end   date.date_filter %}
    ) ;;
  }
  join: order_wow {
    from: orders
    view_label: "Orders (WoW)"
    sql_table_name: (
      SELECT * FROM table
      WHERE order_date >= DATE_SUB({% date_start date.date_filter %}, INTERVAL 1 WEEK)
        AND order_date <= DATE_SUB({% date_end   date.date_filter %}, INTERVAL 1 WEEK)
    ) ;;
  }
  join: orders_yoy {
    from: orders
    view_label: "Orders (YoY)"
    sql_table_name: (
      SELECT * FROM table
      WHERE order_date >= DATE_SUB({% date_start date.date_filter %}, INTERVAL 1 YEAR)
        AND order_date <= DATE_SUB({% date_end   date.date_filter %}, INTERVAL 1 YEAR)
    ) ;;
  }

  # Co-dimension joins
  join: date {
    sql_table_name: UNNEST([COALESCE(
      {% if orders._in_query %} DATE(orders.order_date), {% endif %}
      {% if order_wow._in_query %} DATE_ADD(DATE(order_wow.order_date), INTERVAL 1 WEEK), {% endif %}
      {% if orders_yoy._in_query %} DATE_ADD(DATE(orders_yoy.order_date), INTERVAL 1 YEAR), {% endif %}
      CAST(NULL AS DATE)
    )]) ;;
  }
}
```

## 6. Checklist for Agents

- [ ] `from: none` base view is 0 rows (`UNNEST([])` or `WHERE 1=0`).
- [ ] Every fact/measure join is `type: full_outer`, `relationship: one_to_one`, `sql_on: FALSE ;;`.
- [ ] Every composite measure join is `relationship: one_to_one`, `sql: ;;`.
- [ ] Every dimension join is `type: left_outer`, `relationship: many_to_one`, and `sql_on` uses `COALESCE` with `{% if <fact>._in_query %} join_alias.column_name {% endif %}`.
- [ ] Every co-dimension join is `relationship: one_to_one` with `sql_table_name` like `UNNEST([COALESCE(<liquid conditional fields>)])`.
- [ ] Ensure no join's sql_table_name attempts to refer to ${view_name.SQL_TABLE_NAME} where the join name and the view name are the same.
