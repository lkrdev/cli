# `scripts/schema` — History Validation & Schema Refinement Harness

## Purpose

This directory contains developer tooling for testing and refining `lkr schema generate` and `lkr schema validate` against **real completed Looker queries** stored in `system__activity::history`.

Instead of relying only on hand-crafted unit tests or over-generalizing from a single query, `scripts/schema/history.py` provides a repeatable pipeline that:

1. **Queries `system__activity::history`** (starting from the template query slug `vdAt9IRgn89vVzHSLxOczt` or custom filters):
   - Filters completed queries (`history.status = "complete"`) for a target `--model` (e.g. `thelook`) and `--explore` (e.g. `order_items`), or for specific `--query-id` integer values.
   - Resolves the internal database `query.id` integer (e.g. `142769`, `314`, `324`) to its API 4.0 `query.slug` (e.g. `"P2BfdfcRGtgx3QWn48RwnHFSsCPwWPKY"`), since Looker's `GET /queries/{query_id}` (`sdk.query`) requires the string slug.
2. **Fetches the Full `Query` via `sdk.query(slug)`**:
   - Retrieves the complete `Query` object (`fields`, `pivots`, `filters`, `sorts`, `dynamic_fields`, `subtotals`, `fill_fields`, `filter_expression`, `vis_config`, etc.).
   - Strips read-only metadata (`can`, `id`, `slug`, `share_url`, `expanded_share_url`, `url`, `has_table_calculations`, `filter_config`) via `sanitize_read_query_to_write_query`.
3. **Batch-Validates in Parallel via Rust (`RustExploreValidator`)**:
   - Generates (or loads) the strongly-typed JSON Schema for `<model>::<explore>`.
   - Runs all resolved queries through `validate_batch_queries` (powered by `lkr/schema/rust` + `rayon`), reporting `valid_queries`, `invalid_queries`, and the full list of validation errors per query without short-circuiting.

---

## How to Run

### 1. Validate Recent Completed Queries for an Explore
```bash
uv run python scripts/schema/history.py \
  --oauth-account=prod-demowest \
  --model=thelook \
  --explore=order_items \
  --explore-file=tmp/order_items.json \
  --limit=20
```

### 2. Validate Specific Completed `query.id`s from `system__activity::history`
```bash
uv run python scripts/schema/history.py \
  --oauth-account=prod-demowest \
  --model=thelook \
  --explore=order_items \
  --explore-file=tmp/order_items.json \
  --query-id=142769 \
  --query-id=314 \
  --query-id=324
```

### 3. Filter Only Queries Containing `dynamic_fields`
```bash
uv run python scripts/schema/history.py \
  --oauth-account=prod-demowest \
  --model=thelook \
  --explore=order_items \
  --explore-file=tmp/order_items.json \
  --require-dynamic-fields \
  --limit=25
```

### 4. Recompile the Rust Validator (`_schema_rs.so`)
If you modify the validation rules in `lkr/schema/rust/src/lib.rs`:
```bash
make schema-rs
```
