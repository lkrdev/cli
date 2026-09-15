---
name: lkr-project-helper
description: >
  Create, configure, generate, synchronize, and deploy Looker LookML projects using `uvx lkr-dev-cli`,
  `lkr code-mode sandbox --dev-mode`, and `generate_lookml_with_new_files`. Supports interactive project
  instantiation from database schemas/tables, raw SQL queries (via `bq_view_lookml_generator.py`), or
  natural language semantic intent, plus bare Git setup, model connection configuration, validation,
  LookML push/pull, and pre-push developer workspace reset (`reset_project_to_production`).
  Use when asked "I need a new LookML project", "create a new Looker project", "generate LookML from tables or SQL",
  "configure LookML model and database connection", or "push/pull/deploy LookML files".
---

# Looker Project Helper (`lkr-project-helper`)

This skill guides AI agents through end-to-end Looker LookML project creation, database connection verification, automated LookML generation (`generate_lookml_with_new_files`), raw SQL view introspection (`bq_view_lookml_generator.py`), and bare Git repository synchronization using `uvx lkr-dev-cli` and companion `lkr-code-mode` sandbox scripts.

---

## Installation

Install into your agent workspace using `npx skills`:

```bash
npx skills add lkrdev/cli --skill lkr-project-helper
```

This skill works hand-in-hand with the [`lkr-code-mode`](../lkr-code-mode/SKILL.md) skill (`npx skills add lkrdev/cli --skill lkr-code-mode`), executing Python Looker SDK scripts inside the Monty sandbox via `uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox`.

---

## How `lkr tools lookml push` & Code-Mode Scripts Work Together

### Built-in `lkr tools lookml push` Capabilities:
- **Reset Before Push (`--reset` / `--no-reset`, default `True`)**:
  By default, `lookml push` logs and resets the developer workspace to production (`reset_project_to_production` with fallback to `create_developer_copy`) **at the beginning of the push** before uploading files so your dev branch starts clean from production. Pass `--no-reset` if you want to push incremental edits on top of uncommitted dev workspace changes without resetting first.
- **Automatic Model & Connection Configuration**:
  When pushing any `.model.lkml` file, `lookml push` automatically inspects the `connection: "..."` declaration inside the file, checks `all_lookml_models()`, and calls `create_lookml_model` (if the model is new) or `update_lookml_model` (if the model's `connection` or `project_name` changed).


### What Requires Companion Code-Mode Scripts (All Use `--dev-mode`):
1. **Project & Bare Git Initialization (`ensure_project_and_model.py`)**:
   Before your first push or LookML generation on a brand-new project, use `ensure_project_and_model.py` with `--dev-mode` to create the project (`create_project`), configure `git_service_name: "bare"`, initialize the developer copy (`create_developer_copy`), and register the initial model configuration.
2. **Strict Pre-Commit Validation & Bare Repo Deployment (`deploy_and_reset_workspace.py`)**:
   To run LookML syntax validation (`validate_project`), halt on errors before committing/deploying, promote to production (`deploy_to_production`), and reset the dev workspace (`reset_project_to_production`), use `deploy_and_reset_workspace.py` with `--dev-mode`.


---

## Core Workflow: "I Need a New LookML Project"

When a user asks to create or set up a new LookML project, follow this structured interactive flow:

1. **Verify Authentication & Database Connections (`inspect_connections.py`)**:
   Check available database connections on the Looker instance, test connection health, and confirm the connection has write/scratch dataset (`tmp_db_name`) access if needed.
2. **Prompt for Instantiation Source**:
   **Always ask the user before generating files:**
   > *"What schema, tables, or SQL query should this project be instantiated with?"*
   - **Option A (Database Schema & Tables)**: User provides specific table names and schema/dataset.
   - **Option B (Raw SQL Query)**: User provides a SQL query (`SELECT ...`). Use `scripts/bq_view_lookml_generator.py` to materialize a temporary view in the scratch dataset (`tmp_db_name`), auto-generate typed LookML via `generate_lookml_with_new_files`, and clean up the temporary view.
   - **Option C (Semantic / Natural Language Intent)**: User describes their business domain or analytical questions.
3. **Ensure Project, Bare Git, Developer Copy & Model Configuration (`ensure_project_and_model.py`)**:
   Run with `--dev-mode` to verify/create the project, configure `git_service_name: "bare"`, initialize the developer workspace copy (`create_developer_copy`), and register the LookML model configuration with `allowed_db_connection_names`.
4. **Generate LookML Views & Explores**:
   Execute `generate_lookml_with_new_files` (or `bq_view_lookml_generator.py` for raw SQL) with `--dev-mode` and inspect the newly created file paths.
5. **Pull / Push Local Files (`lkr tools lookml pull` / `push`)**:
   Pull generated LookML files to a local directory using `uvx lkr-dev-cli tools lookml pull`, or push local edits with `uvx lkr-dev-cli tools lookml push` (`--reset` is enabled by default).
6. **Validate, Commit, Deploy & Reset Workspace (`deploy_and_reset_workspace.py`)**:
   Run `deploy_and_reset_workspace.py` with `--dev-mode` to validate, commit, deploy to production, and reset the dev workspace.

---

## Step-by-Step Instructions & CLI Commands

All sandbox commands use `uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli` (or `uv run lkr` inside the `lkrdev/cli` repository). Use `--dev-mode` for all development workspace scripts.

### Step 1: Discover & Verify Database Connections

Inspect available connections, verify connectivity, and list schemas/tables:

```bash
# List all connections on the instance
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox \
  --file=skills/lkr-project-helper/scripts/inspect_connections.py

# Test a specific connection and list its schemas and tables
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox \
  --file=skills/lkr-project-helper/scripts/inspect_connections.py \
  --var connection_name="looker-private-demo" \
  --var schema_name="thelook"
```

*Note*: If instantiating from raw SQL via `bq_view_lookml_generator.py`, ensure the selected connection has a configured `tmp_db_name` (scratch schema/dataset) where Looker has write permissions to create temporary views.

---

### Step 2: Ensure Project, Bare Git, Developer Copy & Model Config (`--dev-mode`)

Before pushing local LookML or running LookML generators on a new project, run `ensure_project_and_model.py` with `--dev-mode`:

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/ensure_project_and_model.py \
  --var project_name="my_new_project" \
  --var model_name="my_model" \
  --var connection_name="looker-private-demo"
```

*(You can also run [`init_project.py`](./scripts/init_project.py) and [`configure_model.py`](./scripts/configure_model.py) individually with `--dev-mode` if desired).*

---

### Step 3: Instantiate LookML Files (`--dev-mode`)

Depending on the user's answer to *"What schema, tables, or SQL should this be instantiated with?"*, choose the matching instantiation pattern:

#### Pattern A: Instantiate from Schema & Tables (`generate_lookml_with_new_files`)

Use `scripts/generate_lookml.py` with `--dev-mode` to invoke `generate_lookml_with_new_files`. This extended SDK method snapshots existing files before generation, runs Looker's LookML generator, and returns `new_files` containing every newly created `.view.lkml` and `.model.lkml` file:

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/generate_lookml.py \
  --var project_name="my_new_project" \
  --var model_name="my_model" \
  --var connection_name="looker-private-demo" \
  --var schema_name="ecomm" \
  --var table_names="orders,order_items,users" \
  --var folder_name="views" \
  --var file_type_for_explores="model"
```

**How `generate_lookml_with_new_files` works under the hood**:
- **Parameters**:
  - `project_id` (`str`): Target Looker project ID.
  - `connection` (`str`): Database connection name.
  - `model_name` (`str`): Name of model or explore file to generate.
  - `folder_name` (`str`): Target folder for generated views (e.g. `"views"`).
  - `file_type_for_explores` (`str`): `"model"` (creates `<model_name>.model.lkml` with explores), `"explore"`, or `"none"`.
  - `generate_descriptions` (`bool`): Pull column descriptions from BigQuery/DB metadata (defaults to `True`).
  - `body` (`dict`): Contains `tables` (list of `{"schema": "...", "table_name": "...", "base_view": True, "primary_key": "..."}`) and/or `semantic_generation_input` (`{"user_intention": "...", "questions": "...", "user_instructions": "..."}`).
- **Return Value**:
  Returns `{"generate_lookml": <api_response>, "new_files": [<list of newly created file objects/paths>]}`.

---

#### Pattern B: Instantiate from Raw SQL (`bq_view_lookml_generator.py`)

When the user provides a raw SQL query (including complex joins, CTEs, or BigQuery nested fields):

1. **Primary Approach (`bq_view_lookml_generator.py`)**:
   This script automatically:
   - Inspects `conn.get("tmp_db_name")` on the target connection.
   - Executes `CREATE OR REPLACE VIEW \`<tmp_db_name>.<view_name>\` AS <sql_content>` via `create_sql_query` and `run_sql_query`.
   - Calls `generate_lookml_with_new_files` against that temporary view so Looker introspects exact column types and generates complete LookML dimensions and measures.
   - Drops the temporary view (`DROP VIEW IF EXISTS ...`).
   - Returns direct URLs to the generated LookML files.

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/bq_view_lookml_generator.py \
  --var project="my_new_project" \
  --var connection="looker-private-demo" \
  --var model="my_model" \
  --var view_name="order_summary_view" \
  --var sql_content="SELECT status, COUNT(*) AS order_count FROM \`ecomm.orders\` GROUP BY 1"
```

2. **Fallback Approach (`create_custom_view.py`)**:
   If the connection does not have a `tmp_db_name` configured or the user prefers a pure LookML derived table (`derived_table: { sql: ... ;; }`), use `create_custom_view.py`:

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/create_custom_view.py \
  --var project_name="my_new_project" \
  --var view_name="order_summary_view" \
  --var folder_name="views" \
  --var sql_query="SELECT status, COUNT(*) AS order_count FROM ecomm.orders GROUP BY 1"
```

---

#### Pattern C: Instantiate from Natural Language / Semantic Intent

If the user describes what they want to analyze without naming specific tables:

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/generate_lookml.py \
  --var project_name="my_new_project" \
  --var model_name="my_model" \
  --var connection_name="looker-private-demo" \
  --var schema_name="ecomm" \
  --var user_intention="Analyze e-commerce order retention and customer lifetime value" \
  --var questions="What is the 30-day repeat purchase rate by acquisition channel?"
```

---

### Step 4: Pull / Push Local LookML Files via CLI

Once files are generated on the Looker instance, pull them into a local directory to inspect or refine them, or push local LookML folders directly to Looker:

```bash
# Pull all remote LookML files into a local directory
uvx lkr-dev-cli tools lookml pull ./my_new_project --project-id="my_new_project"

# Push local LookML folder to Looker (resets dev workspace to production first by default,
# auto-configures any new/changed .model.lkml connection, and with --deploy deploys & resets workspace)
uvx lkr-dev-cli tools lookml push ./my_new_project --project-id="my_new_project" --deploy

# Push without resetting developer workspace first (--no-reset)
uvx lkr-dev-cli tools lookml push ./my_new_project --project-id="my_new_project" --no-reset

# Push a single modified LookML file without removing remote orphans
uvx lkr-dev-cli tools lookml push ./my_new_project --project-id="my_new_project" --file=views/orders.view.lkml
```

---

### Step 5: Strict Validation, Bare Repo Deployment & Dev Workspace Reset (`--dev-mode`)

To validate LookML syntax (blocking on errors), commit, deploy to production, and reset the developer workspace cleanly in `--dev-mode`:

```bash
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode \
  --file=skills/lkr-project-helper/scripts/deploy_and_reset_workspace.py \
  --var project_name="my_new_project" \
  --var commit_message="Initial LookML project setup and deployment" \
  --var strict="true"
```

---

## Companion Recipes & Bundled Scripts

All automation scripts are located in `skills/lkr-project-helper/scripts/` and run with `--dev-mode`:

| Script | Mode Flag | Purpose | Key `--var` Parameters |
| :--- | :--- | :--- | :--- |
| [`ensure_project_and_model.py`](./scripts/ensure_project_and_model.py) | `--dev-mode` | **Pre-Push Complete Setup**: Ensure project, bare Git, developer copy (`create_developer_copy`), and LookML model config exist | `project_name`, `model_name`, `connection_name` |
| [`deploy_and_reset_workspace.py`](./scripts/deploy_and_reset_workspace.py) | `--dev-mode` | **Dev Deploy & Reset**: Validate LookML, commit, deploy to production, and reset dev workspace (`reset_project_to_production`) | `project_name`, `commit_message`, `strict` |
| [`inspect_connections.py`](./scripts/inspect_connections.py) | `--dev-mode` | List connections, test health, inspect schemas/tables | `connection_name`, `schema_name` |
| [`init_project.py`](./scripts/init_project.py) | `--dev-mode` | Create project in dev mode, configure bare Git repo & dev copy | `project_name` |
| [`configure_model.py`](./scripts/configure_model.py) | `--dev-mode` | Create/update LookML model & bind DB connection | `project_name`, `model_name`, `connection_name` |
| [`generate_lookml.py`](./scripts/generate_lookml.py) | `--dev-mode` | Run `generate_lookml_with_new_files` for tables/intent | `project_name`, `model_name`, `connection_name`, `schema_name`, `table_names` |
| [`bq_view_lookml_generator.py`](./scripts/bq_view_lookml_generator.py) | `--dev-mode` | Create temp BQ view from raw SQL, generate LookML, drop view | `project`, `connection`, `model`, `view_name`, `sql_content` |
| [`create_custom_view.py`](./scripts/create_custom_view.py) | `--dev-mode` | Create a direct LookML `derived_table` view from SQL | `project_name`, `view_name`, `sql_query`, `folder_name` |
| [`validate_and_commit.py`](./scripts/validate_and_commit.py) | `--dev-mode` | Validate LookML project, commit to Git, deploy, and reset dev workspace | `project_name`, `commit_message`, `deploy` |
| [`upload_assets.py`](./scripts/upload_assets.py) | `--dev-mode` | Upload non-LookML assets (`.js`, `.css`, `.json`) | `project_name`, `file_path`, `file_content` |
| [`migrate_dashboard_to_udd.py`](./scripts/migrate_dashboard_to_udd.py) | `--dev-mode` | Convert LookML dashboard (`model::dash`) to UDD | `dashboard_id`, `space_id` |

