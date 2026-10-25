---
name: agentic-lookml-workflow
description: >
  End-to-end agentic workflow for refactoring SQL queries and metrics/terms logic into a Looker LookML project.
  Verifies/installs `uv`, `lkr-dev-cli[tools,code-mode,parse]`, and `gh`, authenticates in `--dev` mode
  via `lkr auth add-access-token`, parses `input.sql` offline via `lkr parse sql` so `init_branch.py` resets
  the developer workspace to production, creates a timestamped Looker branch (`YYYYMMDD_HHMMSS_mmm_<looker_user_id>`),
  and pre-generates any missing `bronze/:table.view.lkml` files before the single `lookml pull` into `./data/:id/lookml`
  (regenerating post-pull only when `lkr parse sql-lookml-compare` shows `unmodeled_db_columns` or a brand-new model), tracks high-level
  operations in `./data/:id/summary.md`, applies `agentic-lookml` with opinionated LookML data
  tests (`tests/bronze/` and `tests/silver/`), runs `pre_gate.py` once to initialize SQL Runner queries
  (`/sql/:sql_id`), validate LookML, register explore queries (`/x/:query_id`), check SQL-to-LookML parity,
  and fetch immutable test-slice baselines (`test_queries_json`), targets every new or additional test with
  `lkr code-mode` (`run_lookml_test` filtered by `file_id`/`test`) before committing, and opens a GitHub pull
  request with `summary.md`, interactive query links, and attachments referenced in `data.json`.
---

# Agentic end-to-end SQL-to-LookML workflow (`agentic-lookml-workflow`)

## Prerequisite setup sub-skill

If the repository has not been configured yet (or is missing `uv`, `lkr-dev-cli`, companion skills in `.agents/skills/`, an initial `.model.lkml` file, or `.github/workflows/lookml-pr-checks.yml`), run the setup sub-skill [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md) and [scripts/setup_repo.sh](scripts/setup_repo.sh) first.

## Bundled scripts

All workflow helper scripts live in `.agents/skills/agentic-lookml-workflow/scripts/` (or `skills/agentic-lookml-workflow/scripts/` inside `lkrdev/cli`):

- [setup_repo.sh](scripts/setup_repo.sh) runs [preflight.sh](scripts/preflight.sh), installs any missing companion skills into `.agents/skills/`, installs `.github/workflows/lookml-pr-checks.yml` from [examples/lookml-pr-checks.yml](examples/lookml-pr-checks.yml), ensures `.gitignore` excludes `.env`, `data/`, and `tmp/`, creates/upgrades/deduplicates `<model_name>.model.lkml` recursive `**/*` `include:` globs (fast-pathing straight to model-include sync when `LOOKML_DIR` or `--skip-preflight` is passed), and bootstraps missing GitHub Actions secrets only when `--sync-secrets` is explicitly passed.
- [preflight.sh](scripts/preflight.sh) fast-paths warm runs when `uv`, `lkr`, and `gh` are already on `PATH` (pass `--upgrade` to force `uv tool install --upgrade`), installs missing tools on cold runs, and verifies `gh` authentication locally via `gh auth token` (falling back to `gh auth status`).
- [init_branch.py](scripts/init_branch.py) runs in `lkr code-mode sandbox` to fetch `me()['id']` and `git_production_branch_name`, run `reset_project_to_production`, create branch `YYYYMMDD_HHMMSS_mmm_<looker_user_id>` from the production ref, resolve existing `model_name` + `connection_name`, pre-generate missing `bronze/:table.view.lkml` files before `lookml pull`, and return the base `data.json` payload.
- [configure_model.py](scripts/configure_model.py) runs in `lkr code-mode sandbox` to register or update the LookML model configuration on the Looker instance via `create_lookml_model` (or `update_lookml_model`) with `allowed_db_connection_names=[connection_name]`, defaulting `model_name` to `project_id` (with hyphens replaced by underscores) when the project does not have a model yet. Pair with [examples/template.model.lkml.tmpl](examples/template.model.lkml.tmpl) when creating `./data/:id/lookml/<model_name>.model.lkml`.
- [pre_gate.py](scripts/pre_gate.py) runs in `lkr code-mode sandbox` to unify the pre-modeling/pre-test verification gate into a single sandbox call: splits multi-statement SQL in `input.sql`, creates missing SQL Runner queries via `create_sql_query(body={"connection_name": connection_name, "sql": stmt})`, optionally validates the project (`validate_project`), registers explore queries via `create_query`, verifies row parity against SQL Runner (`run_sql_query` vs `run_inline_query`, ordering Looker columns deterministically by `inline_query.fields`), and optionally executes `test_queries_json` raw baseline slices (returning `.test_query_results` in `data.json`).
- [validate_and_commit_branch.py](scripts/validate_and_commit_branch.py) runs in `lkr code-mode sandbox` to validate the project (`validate_project`, or skipped via `skip_validate="true"`), execute targeted LookML data tests (`run_lookml_test` filtered by `test_names` / `file_ids`, or skipped via `skip_tests="true"`), block commits if any check fails, and optionally commit (`commit`) and push (`push_branch`) the branch via the Looker API when `commit_message` is provided. When `branch_name` is passed without `commit_message` in CI, it syncs the Looker `--dev` workspace to that branch (fast-pathing as a read-only check when `head_sha` already matches the active branch ref).
- [create_github_pr.sh](scripts/create_github_pr.sh) runs `lkr parse lookml snapshot --allow-additions` if `snapshot_check.json` is not yet generated, embeds `summary.md`, the snapshot review status, the interactive SQL Runner (`/sql/:sql_id`) and Looker Explore (`/x/:query_id`) link table, and collapsible `<details>` sections for `./data/:id/input.sql`, `./data/:id/metrics.md`, `./data/:id/snapshot_check.json` (with `.snapshots` stripped for compact output), and `./data/:id/data.json` directly in the PR description, opens the GitHub PR against `git_production_branch_name` via `gh pr create` (requesting reviewers when material snapshot changes are detected), posts `./data/:id/compare_initial.json` and `./data/:id/compare_post_refactor.json` in a collapsible `<details>` PR comment (`gh pr comment`), and writes the PR URL into `./data/:id/data.json`.

### Sandbox script `--var` I/O contracts (no need to read script source)

| Script | `--var` inputs | JSON return payload |
| :--- | :--- | :--- |
| `init_branch.py` | `project_id`, `ts_utc`, `parsed_sql_json` (optional `lkr parse sql` JSON) | `{run_id, user_id, project_id, branch_name, production_branch, production_ref, git_remote_url, model_name?, connection_name?, generated_bronze_files?}` |
| `configure_model.py` | `project_id`, `model_name` (defaults to `${project_id//-/_}`), `connection_name` | `{model_name, project_name, connection_name, action: "created"\|"updated"}` |
| `pre_gate.py` | `raw_sql`, `connection_name`, `data_json`, `base_url`, `validate` (`"true"`/`"false"`), `inline_queries_json` (`{"0": {"model": ..., "view": ..., "fields": [...], "filters"?: {...}, "sorts"?: [...], "limit"?: "500", "dynamic_fields"?: "[...]"}}` — each entry sets its own `"view": "<explore_name>"` so multi-explore `input.sql` runs in one call; list `fields` + `dynamic_fields` in exact SQL `SELECT` projection order so `compare_row_sets` pairs normalized LookML field names positionally when SQL aliases differ), `test_queries_json` (optional `{"slice_key": <WriteQuery dict>}`, also supporting multiple explores) | Updated `data.json`: `{..., passed, all_queries_matched, validation_errors, queries: [{query_index, sql_query_id, sql_runner_url, query_id, query_slug, explore_url, inline_query, parity_status, mismatches, sql}], test_query_results?: {"slice_key": [<raw unformatted row dicts>]}}` |
| `validate_and_commit_branch.py` | `project_id`, `file_ids` (comma-separated `.test.lkml` paths), `test_names` (comma-separated; zipped 1:1 positionally with `file_ids` when counts match, else Cartesian), `commit_message` (optional; commits + pushes branch when non-empty), `branch_name` / `head_sha` / `skip_validate` / `skip_tests` (CI flags) | `{passed, committed, branch_name?, commit_sha?, errors, failed_tests}` |

## Workflow steps

- Ask the user directly for any missing inputs on the first prompt: SQL queries (inline or `.sql` files), metrics and terms logic (business definitions, common measures, and dimensions/filters used for common analysis), and the target Looker project (`PROJECT_ID`, plus `BASE_URL` if not already configured). Do not search the local workspace or query the Looker instance to guess or discover projects unless the user asks to see a list.
- Run [scripts/preflight.sh](scripts/preflight.sh) on warm runs (or [scripts/setup_repo.sh](scripts/setup_repo.sh) once if `.github/workflows/lookml-pr-checks.yml` or `.agents/skills/` is not set up yet; see [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md)), and authenticate in development mode (`--dev` is mandatory; never run in production):
  ```bash
  [[ -f .env ]] && { set -a; source .env; set +a; }
  export BASE_URL="${BASE_URL:-$LOOKERSDK_BASE_URL}"
  bash .agents/skills/agentic-lookml-workflow/scripts/preflight.sh
  lkr --client-id="$LOOKERSDK_CLIENT_ID" --client-secret="$LOOKERSDK_CLIENT_SECRET" --base-url="$BASE_URL" --dev auth add-access-token
  ```
- Parse `$SQL_FILE` offline (`lkr parse sql --file "$SQL_FILE"`), reset the developer workspace to production, create branch `YYYYMMDD_HHMMSS_mmm_<looker_user_id>`, resolve existing `model_name` + `connection_name`, and pre-generate any missing `bronze/:table.view.lkml` files via [scripts/init_branch.py](scripts/init_branch.py); then initialize `./data/$RUN_ID/`, pull LookML once, and—whenever `init_branch.py` returned an existing `model_name`—sync includes, baseline snapshots (`-u`), and `compare_initial.json` in the **same shell call** (inspect pulled LookML files directly under `./data/$RUN_ID/lookml/` after pull rather than reading repo-root LookML before pull, and read `compare_initial.json` via `read_file`):
  ```bash
  PARSED_SQL_JSON=$(lkr parse sql --file "$SQL_FILE")
  RAW_BRANCH=$(lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --file=.agents/skills/agentic-lookml-workflow/scripts/init_branch.py \
    --var project_id="$PROJECT_ID" \
    --var ts_utc="$(date -u +%Y%m%d_%H%M%S_%3N)" \
    --var parsed_sql_json="$PARSED_SQL_JSON")
  BRANCH_JSON=$(echo "$RAW_BRANCH" | sed -n '/^{/,$p')
  RUN_ID=$(echo "$BRANCH_JSON" | jq -er '.run_id')
  MODEL_NAME=$(echo "$BRANCH_JSON" | jq -r '.model_name // empty')
  CONNECTION_NAME=$(echo "$BRANCH_JSON" | jq -r '.connection_name // empty')
  mkdir -p "./data/$RUN_ID/lookml"
  echo "$BRANCH_JSON" > "./data/$RUN_ID/data.json"
  cp "$SQL_FILE" "./data/$RUN_ID/input.sql"
  cp "$METRICS_FILE" "./data/$RUN_ID/metrics.md"
  lkr --base-url="$BASE_URL" --dev tools lookml pull "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID"
  if [[ -n "$MODEL_NAME" ]]; then
    LOOKML_DIR="./data/$RUN_ID/lookml" MODEL_NAME="$MODEL_NAME" CONNECTION_NAME="$CONNECTION_NAME" \
      bash .agents/skills/agentic-lookml-workflow/scripts/setup_repo.sh --skip-preflight
    lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" -u
    lkr parse sql-lookml-compare --compact --sql-file "./data/$RUN_ID/input.sql" --path "./data/$RUN_ID/lookml" --output "./data/$RUN_ID/compare_initial.json"
  fi
  ```
- If the project has **no** existing `.model.lkml` (`MODEL_NAME` empty above) or you are creating a new model, set `MODEL_NAME="${MODEL_NAME:-${PROJECT_ID//-/_}}"`, ask the user for `CONNECTION_NAME` if not provided, register the model via [scripts/configure_model.py](scripts/configure_model.py), and run `setup_repo.sh --skip-preflight` + `snapshot -u` + `sql-lookml-compare --compact` (creating `./data/$RUN_ID/lookml/$MODEL_NAME.model.lkml` *after* any `generate_bronze_view.py` + `lookml pull` so `lookml pull` never deletes a local-only `.model.lkml` file):
  ```bash
  MODEL_NAME="${MODEL_NAME:-${PROJECT_ID//-/_}}"
  lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --file=.agents/skills/agentic-lookml-workflow/scripts/configure_model.py \
    --var project_id="$PROJECT_ID" \
    --var model_name="$MODEL_NAME" \
    --var connection_name="$CONNECTION_NAME"
  ```
- Invoke [generate-view-from-table](../generate-view-from-table/SKILL.md) ([generate_bronze_view.py](../generate-view-from-table/scripts/generate_bronze_view.py)) **only** when `compare_initial.json` shows a physical table missing from `views` or non-empty `views[].unmodeled_db_columns`:
  ```bash
  if [[ -n "${MISSING_OR_STALE_TABLE_NAMES:-}" ]]; then
    RAW_GEN=$(lkr --base-url="$BASE_URL" --dev code-mode sandbox \
      --file=.agents/skills/generate-view-from-table/scripts/generate_bronze_view.py \
      --var project_id="$PROJECT_ID" \
      --var model_name="$MODEL_NAME" \
      --var connection_name="$CONNECTION_NAME" \
      --var schema_name="$SCHEMA_NAME" \
      --var table_name="$MISSING_OR_STALE_TABLE_NAMES")
    for f in $(echo "$RAW_GEN" | sed -n '/^{/,$p' | jq -r '.new_files[]?'); do
      lkr --base-url="$BASE_URL" --dev tools lookml pull "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID" -f "$f"
    done
    LOOKML_DIR="./data/$RUN_ID/lookml" MODEL_NAME="$MODEL_NAME" CONNECTION_NAME="$CONNECTION_NAME" \
      bash .agents/skills/agentic-lookml-workflow/scripts/setup_repo.sh --skip-preflight
    lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" -u
    lkr parse sql-lookml-compare --compact --sql-file "./data/$RUN_ID/input.sql" --path "./data/$RUN_ID/lookml" --output "./data/$RUN_ID/compare_initial.json"
  fi
  ```
- Follow [agentic-lookml](../agentic-lookml/SKILL.md) and [measures-and-sql-functions.md](../agentic-lookml/references/measures-and-sql-functions.md) to author Bronze refinements, Bronze/Silver/Gold explores, and views **together before the first push** (ensuring every standalone `.explore.lkml` and `.test.lkml` explicitly `include:`s its referenced files, syncing `$MODEL_NAME.model.lkml` globs via `LOOKML_DIR="./data/$RUN_ID/lookml" ... setup_repo.sh --skip-preflight`). Validate offline with `lkr parse lookml-to-api --validate --base-path "."` (comparing against repo `HEAD` just like CI) and batch `lkr schema validate` once per distinct target explore (passing `[Q0, Q1, ...]` for that explore), then push once (`lookml push --no-reset --only-changed` automatically deletes any renamed/removed remote orphan files):
  ```bash
  lkr parse lookml-to-api --path "./data/$RUN_ID/lookml" --base-path "." -m "$MODEL_NAME" -e "$EXPLORE_NAME" --validate -o "./data/$RUN_ID/explore_${EXPLORE_NAME}.json"
  lkr schema generate -m "$MODEL_NAME" -e "$EXPLORE_NAME" --explore-file "./data/$RUN_ID/explore_${EXPLORE_NAME}.json" -o "./data/$RUN_ID/schema_${EXPLORE_NAME}.json"
  lkr schema validate --schema-file "./data/$RUN_ID/schema_${EXPLORE_NAME}.json" --query "$INLINE_QUERIES_ARRAY_JSON"
  lkr --base-url="$BASE_URL" --dev tools lookml push "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID" --no-reset --only-changed
  ```
- Execute the unified validation, parity, and test-baseline gate **once** across all target explores using [scripts/pre_gate.py](scripts/pre_gate.py) (each query in `inline_queries_json` and `test_queries_json` specifies its own `"view": "<explore_name>"`, returning `.test_query_results` in the same sandbox call without a second round-trip):
  ```bash
  BASE_URL="${BASE_URL:-$LOOKERSDK_BASE_URL}"
  RAW_OUT=$(lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --file=.agents/skills/agentic-lookml-workflow/scripts/pre_gate.py \
    --var raw_sql="$(cat "./data/$RUN_ID/input.sql")" \
    --var connection_name="$CONNECTION_NAME" \
    --var data_json="$(cat "./data/$RUN_ID/data.json")" \
    --var base_url="$BASE_URL" \
    --var validate="true" \
    --var inline_queries_json="$INLINE_QUERIES_JSON" \
    --var test_queries_json="${TEST_QUERIES_JSON:-{}}")
  JSON_OUT=$(echo "$RAW_OUT" | sed -n '/^{/,$p')
  echo "$JSON_OUT" | jq -e . >/dev/null && echo "$JSON_OUT" > "./data/$RUN_ID/data.json"
  ```
- Once validation and parity pass, author LookML data tests in `./data/$RUN_ID/lookml` following [agentic-lookml](../agentic-lookml/SKILL.md) (`tests/bronze/:table.test.lkml` for single-table measures, `tests/silver/:explore.test.lkml` strictly for joins/`*_fields`/NDTs, one new `test: <table>_<slice>_metrics` block per PR slice on a bounded historical slice using `round(${view.measure}, 2|3|4) = ...`). Sync `$MODEL_NAME.model.lkml` includes if needed, run `sql-lookml-compare --offline --compact` for `compare_post_refactor.json`, update LookML snapshots, and push:
  ```bash
  lkr parse sql-lookml-compare --offline --compact --sql-file "./data/$RUN_ID/input.sql" --path "./data/$RUN_ID/lookml" --output "./data/$RUN_ID/compare_post_refactor.json"
  lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" --allow-additions --format json --output "./data/$RUN_ID/snapshot_check.json" || true
  lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" -u
  lkr --base-url="$BASE_URL" --dev tools lookml push "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID" --no-reset --only-changed
  ```
- Target every new test (`run_lookml_test` filtered by `file_ids` and `test_names`), validate syntax, commit, and push the branch to `origin` via [scripts/validate_and_commit_branch.py](scripts/validate_and_commit_branch.py) (re-running `pre_gate.py` only if LookML view/explore logic had to change while self-healing a test). Write `./data/$RUN_ID/summary.md` once cleanly (covering base views, canonical deconstruction & modeling decisions, matched pattern categories, LookML files authored, any `Validation failed:` / `Updating LookML:` self-heals plus final `/sql/:id` and `/x/:id` parity, and targeted LookML tests), then run [scripts/create_github_pr.sh](scripts/create_github_pr.sh) to open the GitHub PR:
  ```bash
  lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --file=.agents/skills/agentic-lookml-workflow/scripts/validate_and_commit_branch.py \
    --var project_id="$PROJECT_ID" \
    --var file_ids="$NEW_TEST_FILE_IDS" \
    --var test_names="$NEW_TEST_NAMES" \
    --var commit_message="feat(lookml): refactor SQL queries ($RUN_ID)"

  bash .agents/skills/agentic-lookml-workflow/scripts/create_github_pr.sh "./data/$RUN_ID"
  ```

## Example GitHub PR checks workflow ([examples/lookml-pr-checks.yml](examples/lookml-pr-checks.yml))

Installed into `.github/workflows/lookml-pr-checks.yml` by [scripts/setup_repo.sh](scripts/setup_repo.sh) (see [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md)). Serializes shared Looker `--dev` runs via `concurrency: group: looker-dev-...` across four jobs: `snapshots` (offline `lookml-to-api --base-path --validate` + `lookml snapshot --allow-additions` with `CODEOWNERS` gating), `validator` (`validate_project`), `data-tests` (runs [scripts/diff_lookml_tests.py](scripts/diff_lookml_tests.py) to target only newly added or modified `test:` blocks via `file_ids` + `test_names`), and `query-parity` (`pre_gate.py` against `data.json`).
