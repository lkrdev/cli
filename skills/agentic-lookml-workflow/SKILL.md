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

If the repository is missing `uv`, `lkr-dev-cli`, `.agents/skills/` (the sole instruction root—there is no repo-root `AGENTS.md`), an initial `.model.lkml`, or `.github/workflows/lookml-pr-checks.yml`, run [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md) and [scripts/setup_repo.sh](scripts/setup_repo.sh) first.

## Bundled scripts & `--var` I/O contracts (no need to read script source)

Shell helpers in `.agents/skills/agentic-lookml-workflow/scripts/`: [preflight.sh](scripts/preflight.sh) (fast-paths warm tool/auth check), [setup_repo.sh](scripts/setup_repo.sh) (syncs skills, CI workflow, `.gitignore`, and `$MODEL_NAME.model.lkml` recursive `**/*` includes; pass `--skip-preflight` / `LOOKML_DIR` after pull), and [create_github_pr.sh](scripts/create_github_pr.sh) (embeds `summary.md`, snapshot status, `/sql/:sql_id` & `/x/:query_id` parity table, and `jq -c` compacted JSON artifacts into the PR + diagnostic comment).

| Script | `--var` inputs | JSON return payload |
| :--- | :--- | :--- |
| `init_branch.py` | `project_id`, `ts_utc`, `parsed_sql_json` (optional `lkr parse sql` JSON) | `{run_id, user_id, project_id, branch_name, production_branch, production_ref, git_remote_url, model_name?, connection_name?, generated_bronze_files?}` |
| `configure_model.py` | `project_id`, `model_name` (defaults to `${project_id//-/_}`), `connection_name` | `{model_name, project_name, connection_name, action: "created"\|"updated"}` |
| `pre_gate.py` | `raw_sql`, `connection_name`, `data_json`, `base_url`, `validate` (`"true"`/`"false"`), `inline_queries_json` (`{"0": {"model": ..., "view": ..., "fields": [...], "filters"?: {...}, "sorts"?: [...], "limit"?: "500", "dynamic_fields"?: "[...]"}}` — each entry sets its own `"view": "<explore_name>"`; matches `fields` + `dynamic_fields` leaf names to SQL `SELECT` aliases before positional fallback, strips trailing `<base_view>.<pk>` / `common_helpers.no_group` grain keys plus shadowed/single `table_calculation` backing `${view.field}` inputs, pins `CURRENT_TIMESTAMP`/`CURRENT_DATE`/`CURRENT_DATETIME`/`CURRENT_TIME`/`NOW()`, and normalizes stripped `'1. '` `case:` prefixes, half-away-from-zero SQL `ROUND`, outer/CTE `* 100` `percent_*`, `ORDER BY` ties, and deterministic `LIMIT N` tie-breaking), `test_queries_json` (optional `{"slice_key": <WriteQuery dict>}`, executed once validation + parity pass) | Updated `data.json`: `{..., passed, all_queries_matched, validation_errors, queries: [{query_index, sql_query_id, sql_runner_url, query_id, query_slug, explore_url, inline_query, parity_status, mismatches, sql}], test_query_results?: {"slice_key": [<raw unformatted row dicts>]}}` |
| `validate_and_commit_branch.py` | `project_id`, `file_ids` (comma-separated LookML-relative `.test.lkml` paths, e.g. `"tests/bronze/orders.test.lkml"`), `test_names` (comma-separated; zipped 1:1 positionally with `file_ids` — repeat `file_id` when multiple tests live in one file, matching `diff_lookml_tests.py`), `commit_message` (optional; commits + pushes branch when non-empty), `branch_name` / `head_sha` / `skip_validate` / `skip_tests` (CI flags) | `{passed, committed, branch_name?, commit_sha?, errors, failed_tests}` |

## Workflow steps

- Ask the user directly for any missing inputs on the first prompt: SQL queries (inline or `.sql` files), metrics and terms logic (business definitions, common measures, and dimensions/filters used for common analysis), and the target Looker project (`PROJECT_ID`, plus `BASE_URL` if not already configured). Do not search the local workspace or query the Looker instance to guess or discover projects unless the user asks to see a list.
- Run [scripts/preflight.sh](scripts/preflight.sh) on warm runs (or [scripts/setup_repo.sh](scripts/setup_repo.sh) once if `.github/workflows/lookml-pr-checks.yml` or `.agents/skills/` is not set up yet; see [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md)), and authenticate in development mode (`--dev` is mandatory; never run in production):
  ```bash
  [[ -f .env ]] && { set -a; source .env; set +a; }
  export BASE_URL="${BASE_URL:-$LOOKERSDK_BASE_URL}"
  bash .agents/skills/agentic-lookml-workflow/scripts/preflight.sh
  lkr --client-id="$LOOKERSDK_CLIENT_ID" --client-secret="$LOOKERSDK_CLIENT_SECRET" --base-url="$BASE_URL" --dev auth add-access-token
  ```
- Parse one or more SQL input files (`SQL_FILES=(...)`, `METRICS_FILES=(...)`) offline in memory via `lkr parse sql --sql "$SQL_TEXT"` (never write temporary files into `.git/`, which is a file in git worktrees, or the repo root before `$RUN_ID` exists), reset the developer workspace to production, create branch `YYYYMMDD_HHMMSS_mmm_<looker_user_id>`, resolve existing `model_name` + `connection_name`, and pre-generate any missing `bronze/:table.view.lkml` files via [scripts/init_branch.py](scripts/init_branch.py); then initialize `./data/$RUN_ID/`, pull LookML once, and—whenever `init_branch.py` returned an existing `model_name`—sync includes, baseline snapshots (`-u`), and print `compare_initial.json` (deduplicated across multi-query bundles) in the **same shell call** (inspect pulled LookML files directly under `./data/$RUN_ID/lookml/` after pull rather than reading repo-root LookML before pull):
  ```bash
  SQL_TEXT=$(awk 'FNR==1 && NR>1 && prev !~ /;[[:space:]]*$/ {print ";"} {print} {if ($0 !~ /^[[:space:]]*$/) prev=$0}' "${SQL_FILES[@]}")
  PARSED_SQL_JSON=$(lkr parse sql --sql "$SQL_TEXT")
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
  printf '%s\n' "$SQL_TEXT" > "./data/$RUN_ID/input.sql"
  awk 'FNR==1 && NR>1{print "\n---"} {print}' "${METRICS_FILES[@]}" > "./data/$RUN_ID/metrics.md"
  lkr --quiet --base-url="$BASE_URL" --dev tools lookml pull "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID"
  if [[ -n "$MODEL_NAME" ]]; then
    LOOKML_DIR="./data/$RUN_ID/lookml" MODEL_NAME="$MODEL_NAME" CONNECTION_NAME="$CONNECTION_NAME" \
      bash .agents/skills/agentic-lookml-workflow/scripts/setup_repo.sh --skip-preflight
    lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" -u >/dev/null
    lkr parse sql-lookml-compare --compact --sql-file "./data/$RUN_ID/input.sql" --path "./data/$RUN_ID/lookml" --output "./data/$RUN_ID/compare_initial.json" >/dev/null
    jq -c '
      ([.queries[].explores[]? | select((.file // "") | startswith("gold/")).explore_name] | unique) as $gold | {
        tests: ([.queries[].tests[]? | {file, explore_name}] | unique),
        explores: ([.queries[].explores[]? | select((.file // "") | startswith("gold/") | not)] | group_by([.explore_name, .file]) | map({explore_name: .[0].explore_name, file: .[0].file, extends: .[0].extends, joins: ([.[].join_name // empty] | unique)})),
        join_analysis: ([.queries[].join_analysis[]? | select(.explore_name as $e | ($gold | index($e)) == null) | "\(.explore_name):\((.sql_join.table? // .sql_join // "") | gsub("[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_]+\\."; "")):\(.status):\(.relationship // "")"] | unique),
        queries: [.queries[] | {tables: [.parsed_query.tables[]?.name], ctes: .parsed_query.ctes, joins: [.parsed_query.joins[]?.table]}],
        views: ([.queries[].views[]?] | group_by(.view_name) | map({
          view_name: .[0].view_name, file: .[0].file,
          unmodeled_db_columns: ([.[].unmodeled_db_columns[]?] | unique),
          fields: ([.[].fields[]? | "\(.field_name)\(if .primary_key then ":pk" elif .field_type == "measure" then ":m" elif ((.type // "") | startswith("duration")) then ":dur" else "" end)"] | unique | join(","))
        }))
      }
    ' "./data/$RUN_ID/compare_initial.json" | tee "./data/$RUN_ID/compare_summary.json" | head -c 24000 || true
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
- Follow [agentic-lookml](../agentic-lookml/SKILL.md) to author Bronze refinements, Bronze/Silver/Gold explores, and views **together before the first push**:
  - Wait for `compare_initial.json` before opening `references/` playbooks or [measures-and-sql-functions.md](../agentic-lookml/references/measures-and-sql-functions.md), and skip both when inline single-table/simple-aggregate rules already cover the query.
  - Read only `.refinement.lkml` files that need Bronze edits (skipping untouched refinements once `compare_summary.json` confirms their PKs/fields, and reading head/tail slices on `>150`-line refinements) and active `hidden: no` `.explore.lkml` headers (`StartLine=1, EndLine=140`, skipping historical `query:` blocks)—never read `hidden: yes` `*_base.explore.lkml` when a Silver explore is active (unless promoting a physical join/`UNNEST` into both `*_base` and Silver), unrelated tables, `bronze/:table.view.lkml`, `.model.lkml`, `*.snap.json.md`, raw `compare_initial.json`/`data.json` (re-read small `compare_summary.json` only if context compacts), or existing `.test.lkml` (`compare_summary.json` `.tests` already identifies existing `.test.lkml` files; append new `test:` blocks via `write_file` with `Append=True` and a leading newline after `pre_gate.py` without running `head`/`ls`).
  - Explicitly `include:` referenced files in standalone `.explore.lkml` / `.test.lkml` files, `rm -f` any obsolete `bronze/explores/:table.explore.lkml` when detaching to `:table_base.explore.lkml` (`lookml push --only-changed` removes deleted files on the remote branch), sync `$MODEL_NAME.model.lkml` globs via `LOOKML_DIR="./data/$RUN_ID/lookml" ... setup_repo.sh --skip-preflight` if needed, and prefer one `write_file` overwrite over 3+ `edit_file` calls on a short LookML file (on >120-line Explores, place new `query:` blocks right below `join:` blocks so `include:` + `join:` + `query:` fit in a single contiguous `edit_file`).
  - Chain per-explore offline `--validate` (across `INLINE_QUERIES_JSON` `.view`s plus any modified upstream `explore_source:` explores) + `schema validate --explore-file`, `lookml push`, and [scripts/pre_gate.py](scripts/pre_gate.py) (including `test_queries_json` across all target explores) in **one shell call**, printing the compact `jq` summary so `data.json` need not be re-read:
  ```bash
  BASE_URL="${BASE_URL:-$LOOKERSDK_BASE_URL}"
  for EXPLORE_NAME in $(jq -r '[.[].view] | unique[]' <<<"$INLINE_QUERIES_JSON"); do
    API_OUT=$(lkr parse lookml-to-api --path "./data/$RUN_ID/lookml" --base-path "." -m "$MODEL_NAME" -e "$EXPLORE_NAME" --validate -o "./data/$RUN_ID/explore_${EXPLORE_NAME}.json" 2>&1) || { echo "$API_OUT"; exit 1; }
    VAL_OUT=$(lkr schema validate -m "$MODEL_NAME" -e "$EXPLORE_NAME" --explore-file "./data/$RUN_ID/explore_${EXPLORE_NAME}.json" --query "$(jq -c --arg e "$EXPLORE_NAME" '[.[] | select(.view == $e)]' <<<"$INLINE_QUERIES_JSON")") || { echo "$VAL_OUT"; exit 1; }
  done
  lkr --quiet --base-url="$BASE_URL" --dev tools lookml push "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID" --no-reset --only-changed
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
  echo "$JSON_OUT" | jq -c '{passed, all_queries_matched, validation_errors, queries: [.queries[]? | {query_index, parity_status, sql_runner_url, explore_url, mismatches}], test_query_results: (.test_query_results // {} | map_values(if type == "array" then .[:10] else . end))}'
  ```
- Once validation and parity pass, author LookML data tests in `./data/$RUN_ID/lookml` following [agentic-lookml](../agentic-lookml/SKILL.md) (`tests/bronze/:table.test.lkml` for single-table measures and dimensions/terms, `tests/silver/:explore.test.lkml` strictly for joins/`*_fields`/NDTs, one new `test:` block per PR slice on a bounded historical slice) and write `./data/$RUN_ID/summary.md` alongside them (covering base views, canonical deconstruction & modeling decisions, matched pattern categories, LookML files authored, any `Validation failed:` / `Updating LookML:` self-heals plus final `/sql/:id` and `/x/:id` parity, and targeted LookML tests). Sync `$MODEL_NAME.model.lkml` includes if needed, run `sql-lookml-compare --offline --compact` for `compare_post_refactor.json`, update LookML snapshots, push, run [scripts/validate_and_commit_branch.py](scripts/validate_and_commit_branch.py) (re-running `pre_gate.py` and updating `summary.md` only if LookML view/explore logic had to change while self-healing a test), and open the GitHub PR via [scripts/create_github_pr.sh](scripts/create_github_pr.sh) in one chained call:
  ```bash
  lkr parse sql-lookml-compare --offline --compact --sql-file "./data/$RUN_ID/input.sql" --path "./data/$RUN_ID/lookml" --output "./data/$RUN_ID/compare_post_refactor.json" >/dev/null
  jq -c '[.queries[]?.explore_queries[0]? // empty]' "./data/$RUN_ID/compare_post_refactor.json"
  lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" --allow-additions --format json --output "./data/$RUN_ID/snapshot_check.json" || true
  jq -c 'del(.snapshots)' "./data/$RUN_ID/snapshot_check.json"
  lkr parse lookml snapshot --path "./data/$RUN_ID/lookml" -u >/dev/null
  lkr --quiet --base-url="$BASE_URL" --dev tools lookml push "./data/$RUN_ID/lookml" --project-id="$PROJECT_ID" --no-reset --only-changed
  RAW_COMMIT=$(lkr --base-url="$BASE_URL" --dev code-mode sandbox \
    --file=.agents/skills/agentic-lookml-workflow/scripts/validate_and_commit_branch.py \
    --var project_id="$PROJECT_ID" \
    --var file_ids="$NEW_TEST_FILE_IDS" \
    --var test_names="$NEW_TEST_NAMES" \
    --var commit_message="feat(lookml): refactor SQL queries ($RUN_ID)")
  echo "$RAW_COMMIT" | sed -n '/^{/,$p' | jq -e '.passed == true and .committed == true' >/dev/null
  bash .agents/skills/agentic-lookml-workflow/scripts/create_github_pr.sh "./data/$RUN_ID"
  ```

## Example GitHub PR checks workflow ([examples/lookml-pr-checks.yml](examples/lookml-pr-checks.yml))

Installed into `.github/workflows/lookml-pr-checks.yml` by [scripts/setup_repo.sh](scripts/setup_repo.sh) (see [sub-skills/setup/SKILL.md](sub-skills/setup/SKILL.md)). Serializes shared Looker `--dev` runs via `concurrency: group: looker-dev-...` across four jobs: `snapshots` (offline `lookml-to-api --base-path --validate` + `lookml snapshot --allow-additions` with `CODEOWNERS` gating), `validator` (`validate_project`), `data-tests` (runs [scripts/diff_lookml_tests.py](scripts/diff_lookml_tests.py) to target only newly added or modified `test:` blocks via `file_ids` + `test_names`), and `query-parity` (`pre_gate.py` against `data.json`).
