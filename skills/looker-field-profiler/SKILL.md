---
name: looker-field-profiler
description: >
  Profile Looker Explore fields (`string`, `number`, `yesno`, `datetime`) using `profile_fields` in
  `lkr code-mode sandbox` or `ExtendedLooker40SDK`. Classifies root types and subtypes, computes
  `APPROX_COUNT_DISTINCT` and `APPROX_QUANTILES` totals (`limit=5000`, `total=True`), expands date/time
  fields into multi-grain subtotals (`year`/`month`/`day` or `date`/`hour`) to measure temporal
  spikiness, walks measure dependencies to profile underlying leaf dimensions, and emits `profile:*`
  `suggested_tags`, an explicit `decisions` trace, and ready-to-paste LookML refinement snippets.
  Use when profiling Explore data, auditing field distributions, diagnosing spiky time series,
  selecting chart types or filter grains, or curating LookML descriptions, `tags:`, `hidden:`, and `suggestable:`.
---

# Looker Field Value Profiler (`looker-field-profiler`)

`profile_fields` is a built-in Extended Looker SDK and Monty Code Mode sandbox function that profiles dimensions and measures on any Looker Explore (`model` + `view`) while respecting Looker's `5000` row limit (`limit="5000"`, `total=True`).

---

## 1. Invoking `profile_fields`

Inside `lkr code-mode sandbox`, `profile_fields` is pre-bound as a global function (no imports or `sdk.` prefix required):

```bash
# Fast metadata-only type bucketing (zero SQL queries):
uv run lkr code-mode sandbox --code='
return profile_fields(
    model="agentic_thelook",
    view="order_items",
    fields=["order_items.status", "order_items.sale_price", "order_items.is_delivered", "order_items.created_date"],
    types_only=True,
)
'

# Full value profiling (per-field queries, default group_fields=False):
uv run lkr code-mode sandbox --code='
return profile_fields(
    model="agentic_thelook",
    view="order_items",
    fields=[
        "order_items.status",
        "products.brand",
        "users.email",
        "order_items.days_to_deliver",
        "order_items.is_delivered",
        "order_items.created_date",
        "order_items.created_time",
        "order_items.total_sale_price",
    ],
    filters={"order_items.created_date": "7 years"},
)
'

# Multi-dimensional grouped profiling (1 combined query for all non-datetime fields):
uv run lkr code-mode sandbox --code='
return profile_fields(
    body={
        "model": "agentic_thelook",
        "view": "order_items",
        "fields": ["order_items.status", "order_items.is_delivered", "order_items.total_sale_price"],
        "group_fields": True,
        "limit": 5000,
    }
)
'
```

### Signature & Parameters

```python
profile_fields(
    body: dict[str, object] | WriteQuery | None = None,
    model: str | None = None,
    view: str | None = None,          # Explore name (matches WriteQuery.view)
    fields: list[str] | None = None,  # Defaults to visible dimensions on base_view when omitted
    filters: dict[str, str] | None = None,
    types_only: bool = False,         # Metadata-only classification (0 SQL queries)
    group_fields: bool = False,       # Group non-datetime fields into 1 query and return grouped_rows
    limit: int | str = 5000,          # Capped at 5000 to match Looker's standard inline query limit
) -> dict[str, object]
```

- **Measures in `fields`**: When a measure (such as `order_items.total_sale_price`) is included in `fields`, `profile_fields` evaluates its scalar aggregate in `"measures"` **and** recursively walks its `${...}` / `${TABLE}.col` dependencies to profile its underlying leaf dimensions (`order_items.sale_price`).
- **`dimension_group` names in `fields`**: Passing a bare `dimension_group` name (such as `order_items.created`) automatically resolves to its `_date` or `_time` timeframe.

---

## 2. Output Structure

`profile_fields` returns a dictionary with:

- **`type_buckets`**: `{"string": [...], "number": [...], "yesno": [...], "datetime": [...]}`
- **`profiles`**: Per-dimension profile objects keyed by qualified field name (`view.field`):
  - `root_type`: `"string"` | `"number"` | `"yesno"` | `"datetime"`
  - `subtype`: Specific data distribution subtype (see Section 3)
  - `total_rows`, `approx_count_distinct` (via BigQuery/warehouse `APPROX_COUNT_DISTINCT`), `null_count`, `null_pct`
  - `stats`: Type-specific distribution statistics, `top_values` (`value`, `count`, `pct`), and for `datetime` fields: `min_date`, `max_date`, `span_days`, `expanded_fields`, `spikiness`, and `subtotals_by_grain`
  - `suggested_tags`: List of `profile:*` semantic tags (such as `["profile:nullable", "profile:searchable_entity_label"]`)
  - `decisions`: Step-by-step audit strings explaining every threshold or rule that selected `root_type`, `subtype`, `suggested_tags`, `recommended_hidden`, and `recommended_suggestable`
  - `curation`: LookML refinement recommendations (`recommended_hidden`, `recommended_suggestable`, `recommended_description`, `suggested_tags`, and a ready-to-paste `lookml_snippet`)
- **`measures`**: Scalar values and `leaf_dimensions` for any measures passed in `fields`
- **`grouped_rows`**: Top 50 joint combinations when `group_fields=True`

---

## 3. Root Types, Subtypes, and Decision Rules

### Cross-Type Rules (Evaluated on Every Field)
| `suggested_tags` value | Trigger condition |
| :--- | :--- |
| `profile:foreign_key` | `primary_key` is `False` and short field name ends with `_id` or `_fk` |
| `profile:nullable` | `null_count > 0` (from `totals_data` filtered measure `is_null(${field})`) |
| `profile:unique_key_candidate` | `total_rows > 0`, `approx_count_distinct == total_rows`, and `null_count == 0` |

### A. `string` Subtypes & Tags (First Match Wins)
| Priority | `subtype` | `suggested_tags` added | Detection rule / threshold | `hidden` | `suggestable` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `tier` / `location` | `profile:tier` or `profile:location` | LookML `type` is `tier` or `location` | `no` | `yes` (`tier`), `no` (`location`) |
| 2 | `json` | `profile:json_payload` | `JSON_` in `sql`, name has `json`/`payload`/`raw_event`, or $\ge 50\%$ of top values start/end with `{...}` or `[...]` | `yes` | `no` |
| 3 | `id_or_code` | `profile:uuid_or_hash` | Name has `uuid`/`guid`/`hash`/`md5`/`sha256`, or $\ge 80\%$ of top values match 36-char UUID or 32–64 char hex | `yes` | `no` |
| 4 | `id_or_code` | `profile:foreign_key` (if `*_id`/`*_fk`) | `primary_key=True`, system prefix (`_fivetran_`, `_airbyte_`, `_sdc_`, `etl_`), helper dim, or `id`/`*_id` with `approx_count_distinct > 100` | `yes` | `no` |
| 5 | `empty_or_null` | `profile:empty_or_null_only` | `approx_count_distinct == 0` and `total_rows > 0` | `yes` | `no` |
| 6 | `free_text` | `profile:opaque_code_or_free_text` | `max_length > 120`, `avg_length > 60`, or name ends with `comment(s)`/`note(s)`/`description`/`message`/`body`/`transcript` | `no` | `no` |
| 7 | `id_or_code` | `profile:opaque_code_or_free_text` | `lookml_type == "zipcode"` or name ends with `sku`/`code`/`zip`/`postal`/`phone`/`email`/`url`/`uri`/`ip`/`token`/`tracking_number` | `no` | `no` |
| 8 | `enum` | `profile:low_cardinality_enum` | $1 \le \text{approx\_count\_distinct} \le 15$ | `no` | `yes` |
| 9 | `categorical` | `profile:medium_cardinality_categorical` | $16 \le \text{approx\_count\_distinct} \le 100$ | `no` | `yes` |
| 10 | `entity_label` | `profile:searchable_entity_label` | $\text{approx\_count\_distinct} > 100$ | `no` | `yes` |

- **Additional PII tags on strings**:
  - `profile:pii` + `profile:email`: `"email"` in field name or $\ge 50\%$ of sample values match `*@*.*`
  - `profile:pii` + `profile:phone`: `"phone"`, `"mobile"`, or `"telephone"` in field name
  - `profile:pii`: `"ssn"`, `"tax_id"`, `"passport"`, `"first_name"`, `"last_name"`, `"full_name"`, `"street_address"`, or `"ip_address"` in field name

### B. `number` Subtypes & Tags
| Priority | `subtype` | `suggested_tags` added | Detection rule / threshold |
| :--- | :--- | :--- | :--- |
| 1 | `empty_or_null` | `profile:empty_or_null_only` | `approx_count_distinct == 0` and `total_rows > 0` (`hidden: yes`) |
| 2 | `id_or_key` | `profile:foreign_key` (if `*_id`/`*_fk`) | `primary_key=True`, system column, or ends with `id`/`_id`/`_pk`/`_fk`/`_sk` (`hidden: yes`) |
| 3 | `constant` | `profile:constant_value` | `approx_count_distinct == 1` |
| 4 | `duration` | `profile:duration` | `lookml_type` starts with `duration` or name has `days_`/`hours_`/`minutes_`/`_duration`/`shelf_age` |
| 5 | `percentage_or_ratio` | `profile:percentage_or_ratio` | `%` in `value_format`, rate/pct/ratio/share token in name, or non-integer values in $[0.0, 1.0]$ |
| 6 | `currency_or_decimal` | `profile:currency_or_decimal` | `$`/`usd` in `value_format` or monetary token (`price`, `cost`, `revenue`, `amount`, `margin`, `profit`, `spend`, `fee`) |
| 7 | `discrete_integer` | `profile:discrete_integer` | All sampled numeric values are whole integers |
| 8 | `continuous_number` | `profile:continuous_number` | Non-integer continuous values |

- **Additional distribution tags on numbers**:
  - `profile:has_zeros`: `zero_count > 0` (`${field} = 0`)
  - `profile:has_negatives`: `negative_count > 0` (`${field} < 0`)
  - `profile:skewed_distribution`: $\frac{|\text{average} - \text{median}|}{|\text{median}|} \ge 0.5$ (where `median` uses warehouse `APPROX_QUANTILES`)

### C. `yesno` Subtypes & Tags
| `subtype` | `suggested_tags` added | Detection rule / threshold |
| :--- | :--- | :--- |
| `empty_or_null` | `profile:empty_or_null_only` | `true_count == 0` and `false_count == 0` (`hidden: yes`) |
| `constant_boolean` | `profile:constant_boolean`, `profile:constant_value` | Only `Yes` or only `No` rows exist |
| `rare_or_skewed_boolean` | `profile:rare_or_skewed_boolean` | Minority class $\min(\text{true\_pct}, \text{false\_pct}) < 5.0\%$ |
| `balanced_boolean` | `profile:balanced_boolean` | Minority class $\min(\text{true\_pct}, \text{false\_pct}) \ge 5.0\%$ |

### D. `datetime` Subtypes, Grain Expansion & Spikiness Tags
- **Subtypes**:
  - `timestamp_or_raw` (`profile:timestamp_or_raw`): `date_time`, `date_raw`, `date_hour`, `date_minute`, `date_second`. Automatically expands to `[date, hour]` with `subtotals=[date]`.
  - `calendar_date` (`profile:calendar_date`): `date_date`. Automatically expands to `[year, month, date]` with `subtotals=[year, month]`.
  - `period_grain` (`profile:period_grain`): `date_year`, `date_quarter`, `date_month`, `date_week`, `date_fiscal_year`, `date_fiscal_quarter`. Automatically expands to `[year, month, date]` with `subtotals=[year, month]`.
  - `calendar_cycle` (`profile:calendar_cycle`): recurring cycle timeframes such as `date_day_of_week`, `date_hour_of_day`, `date_month_name`.
- **Spikiness metrics (`stats.spikiness[grain]`)**:
  - Computes `period_count`, `min_count`, `max_count`, `mean_count` ($\mu$), `stddev_count` ($\sigma$), `spikiness_ratio` ($\frac{\max}{\mu}$), `cv` ($\frac{\sigma}{\mu}$), `peak_period`, and `trough_period` across `year`, `month`, `day`, or `hour`.
  - Emits **`profile:spiky_<grain>`** (`profile:spiky_year`, `profile:spiky_month`, `profile:spiky_day`, `profile:spiky_hour`) when `spikiness_ratio >= 2.0` or `cv >= 0.5`.
  - Emits **`profile:steady_volume`** when `0 < cv < 0.25`.

---

## 4. What to Do with the Profile Information (Action Playbook)

### A. LookML Curation & Refinements (`bronze/:table.refinement.lkml`)
1. **Apply `curation.lookml_snippet` directly in refinement files**:
   - Never hand-edit autogenerated `bronze/:table.view.lkml` files; paste or merge `curation["lookml_snippet"]` into `bronze/:table.refinement.lkml` (`view: +:table { ... }`).
   - See [lookml-field-curation](../lookml-field-curation/SKILL.md) for Medallion refinement rules.
2. **Prune noisy fields (`recommended_hidden: True`)**:
   - Hide `profile:json_payload`, `profile:uuid_or_hash`, `profile:empty_or_null_only`, and surrogate `id_or_code` / `id_or_key` dimensions so they do not clutter the Explore picker or Conversational Analytics context window.
3. **Protect warehouse compute (`recommended_suggestable: False`)**:
   - Set `suggestable: no` on fields tagged `profile:opaque_code_or_free_text` (`users.email`, `sku`, `ip_address`, `free_text` notes) to prevent expensive `SELECT DISTINCT <col> ... LIMIT 1000` filter autocomplete scans while keeping the field visible for exact filtering and table reporting.
   - Keep `suggestable: yes` on `profile:low_cardinality_enum`, `profile:medium_cardinality_categorical`, and `profile:searchable_entity_label` (`products.brand`, `users.city`).

### B. Query Authoring, Visualization & Dashboard Design
| Tag / Subtype | Action to Take in Queries & Dashboards |
| :--- | :--- |
| `profile:low_cardinality_enum` ($\le 15$) | Safe for **`pivots:`**, stacked bar/column series, donut charts, and dashboard dropdown filters. Use exact values from `stats.top_values` when writing Looker filter expressions. |
| `profile:medium_cardinality_categorical` ($16\text{–}100$) | Safe for **`GROUP BY`** in bar charts and grids with `limit: "20"` or `limit: "50"`. Do **not** pivot on this dimension (causes wide-table column explosion). |
| `profile:searchable_entity_label` ($> 100$) | Use only in top-$N$ ranked leaderboards (`sorts: ["measure desc"]`, `limit: "25"`) or filter via substring/exact match. Never pivot or render in unfiltered pie/bar charts. |
| `profile:skewed_distribution` | Mean (`average`) diverges from `median` by $\ge 50\%$ due to outliers or power-law tails. Always pair `type: average` measures with a `type: median` (`APPROX_QUANTILES`) measure or custom measure in executive scorecards. |
| `profile:has_zeros` | Guard any custom division or ratio expression where this field is in the denominator using `nullif(${field}, 0)`. |
| `profile:has_negatives` | Inspect whether negative values represent refunds, credits, reversals, or clock-skew bugs (`duration < 0`). Add filtered measures (e.g. `filters: [amount: ">0"]`) when gross vs net semantics differ. |
| `profile:nullable` (`null_pct` high) | When `null_pct` is significant (e.g. `order_items.days_to_deliver` at `64.83%` null for unshipped/in-transit orders), document the null semantics in `description:` and filter cohorts (`NOT NULL`) when charting completion metrics. |
| `profile:rare_or_skewed_boolean` ($< 5\%$) | Avoid side-by-side 50/50 split charts where the minority slice is barely visible; create a filtered measure (`filters: [flag: "Yes"]`) or percentage-of-total anomaly rate KPI instead. |
| `profile:spiky_year` / `profile:spiky_month` / `profile:spiky_day` / `profile:spiky_hour` | Inspect `stats.spikiness[grain]["peak_period"]` and `"trough_period"`:<br>1. Check if `trough_period` is an incomplete trailing month/day and exclude partial periods in dashboard filters (e.g. `complete months`).<br>2. Avoid static alert thresholds on spiky grains; use rolling averages or YoY/DoW baselines.<br>3. Run `decompile_kda_target` + `run_key_driver_analysis` comparing `peak_period` (`breach_filters`) against normal periods (`baseline_filters`) to explain what drove the spike. |
| `profile:steady_volume` ($\text{cv} < 0.25$) | Ideal baseline grain for anomaly detection and fixed-threshold SLA monitoring. |

### C. Security, Governance & LookML Data Tests (`.test.lkml`)
- **`profile:pii`, `profile:email`, `profile:phone`**:
  - Apply `required_access_grants:` or BigQuery policy-tag / Dynamic Data Masking security refinements (`lkr tools lookml create --bq-security`).
  - Run `lkr parse lookml snapshot` so PII-tagged fields are tracked in `access.snap.json.md` for `CODEOWNERS` review.
- **`profile:unique_key_candidate`**:
  - Candidate for `primary_key: yes` on the view and a `.test.lkml` uniqueness assertion (`assert: id_is_unique { expression: count(${view.field}) = count_distinct(${view.field}) ;; }`).
- **`profile:empty_or_null_only` & `profile:constant_value`**:
  - Flag potential upstream ETL breakage or unpopulated columns before building downstream Silver/Gold models on top of them.

---

## 5. Sub-Skills & Scripts

- **[Scratch Schema Value Search (`sub-skills/scratch-search/SKILL.md`)](sub-skills/scratch-search/SKILL.md)**:
  - Profiles string dimensions across a model (offline via `--path` or online via `lookml_model_explore`), compiles each searchable `(explore_name, field_name)` SQL branch via `run_inline_query(result_format="sql")`, and generates a `UNION ALL` PDT (`view: _field_value_search` with `sql_trigger_value: SELECT CURRENT_DATE ;;` and `create_process` search index DDL) plus a `hidden: yes` LookML Explore (`explore: _field_value_search`) across 5 dialects ([`bigquery.py`](scripts/dialects/bigquery.py), [`snowflake.py`](scripts/dialects/snowflake.py), [`postgres.py`](scripts/dialects/postgres.py), [`databricks.py`](scripts/dialects/databricks.py), [`duckdb.py`](scripts/dialects/duckdb.py)) via [`scripts/scratch_search.py`](scripts/scratch_search.py).
