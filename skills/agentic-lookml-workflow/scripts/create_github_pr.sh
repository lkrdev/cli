#!/usr/bin/env bash
set -euo pipefail

SESSION_DIR="${1:?Usage: create_github_pr.sh ./data/<run_id>}"
DATA_JSON="$SESSION_DIR/data.json"
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

RUN_ID=$(jq -r '.run_id' "$DATA_JSON")
REPO=$(jq -r '.git_remote_url' "$DATA_JSON")
HEAD_BRANCH=$(jq -r '.branch_name' "$DATA_JSON")
BASE_BRANCH=$(jq -r '.production_branch // "main"' "$DATA_JSON")
PROJECT_ID=$(jq -r '.project_id // empty' "$DATA_JSON")

EXISTING_SECRETS=$(gh secret list --repo "$REPO" --json name --jq '.[].name' 2>/dev/null || true)
S_BASE="${LOOKERSDK_BASE_URL:-${BASE_URL:-}}"
S_ID="${LOOKERSDK_CLIENT_ID:-}"
S_SECRET="${LOOKERSDK_CLIENT_SECRET:-}"
S_PROJ="${LOOKER_PROJECT_NAME:-${PROJECT_ID:-}}"
if [[ -f ".env" ]]; then
  [[ -z "$S_BASE" ]] && S_BASE=$(grep -E '^(export )?(LOOKERSDK_BASE_URL|BASE_URL)=' .env | head -n 1 | cut -d= -f2- | tr -d "\"'" || true)
  [[ -z "$S_ID" ]] && S_ID=$(grep -E '^(export )?LOOKERSDK_CLIENT_ID=' .env | head -n 1 | cut -d= -f2- | tr -d "\"'" || true)
  [[ -z "$S_SECRET" ]] && S_SECRET=$(grep -E '^(export )?LOOKERSDK_CLIENT_SECRET=' .env | head -n 1 | cut -d= -f2- | tr -d "\"'" || true)
  [[ -z "$S_PROJ" ]] && S_PROJ=$(grep -E '^(export )?(LOOKER_PROJECT_NAME|PROJECT_ID)=' .env | head -n 1 | cut -d= -f2- | tr -d "\"'" || true)
fi
for pair in "LOOKERSDK_BASE_URL:$S_BASE" "LOOKERSDK_CLIENT_ID:$S_ID" "LOOKERSDK_CLIENT_SECRET:$S_SECRET" "LOOKER_PROJECT_NAME:$S_PROJ"; do
  k="${pair%%:*}"
  v="${pair#*:}"
  if [[ -n "$v" ]] && ! echo "$EXISTING_SECRETS" | grep -qxF "$k"; then
    printf '%s' "$v" | gh secret set "$k" --repo "$REPO" 2>/dev/null \
      || printf '%s' "$v" | env -u GH_TOKEN -u GITHUB_TOKEN gh secret set "$k" --repo "$REPO" 2>/dev/null \
      || true
  fi
done

if [[ -d "$SESSION_DIR/lookml" && ! -f "$SESSION_DIR/snapshot_check.json" ]]; then
  lkr parse lookml snapshot --path "$SESSION_DIR/lookml" --allow-additions --format json --output "$SESSION_DIR/snapshot_check.json" || true
fi

SNAPSHOT_SECTION=""
PR_EXTRA_ARGS=()
if [[ -f "$SESSION_DIR/snapshot_check.json" ]]; then
  if jq -e '.requires_review == true' "$SESSION_DIR/snapshot_check.json" >/dev/null 2>&1; then
    MAT_LIST=$(jq -r '.material_changes[]? | "- `" + . + "`"' "$SESSION_DIR/snapshot_check.json")
    CODEOWNERS_REQ=$(jq -r '[.required_reviewers[]?, (env.LOOKML_REVIEWERS // "" | split(",")[] | select(length > 0))] | unique | join(",")' "$SESSION_DIR/snapshot_check.json")
    SNAPSHOT_SECTION=$'\n\n### Material Snapshot Changes (Human Review Required)\n'"$MAT_LIST"
    if [[ -n "$CODEOWNERS_REQ" ]]; then
      SNAPSHOT_SECTION+=$'\n\nRequired CODEOWNERS: `'"$CODEOWNERS_REQ"$'`'
      PR_EXTRA_ARGS+=(--reviewer "$CODEOWNERS_REQ")
    fi
  else
    SNAPSHOT_SECTION=$'\n\n### LookML Snapshot Status\nAdditive-only changes verified (`requires_review: false`).'
  fi
fi

QUERIES_TABLE=""
if jq -e '.queries and (.queries | length > 0)' "$DATA_JSON" >/dev/null 2>&1; then
  QUERIES_TABLE=$'\n\n### Query Verification & Parity\n| # | SQL Runner URL | Looker Explore URL | Parity Status |\n| :--- | :--- | :--- | :--- |'
  while IFS=$'\t' read -r q_idx sql_url exp_url status; do
    sql_link="[Open SQL Runner]($sql_url)"
    [[ -z "$sql_url" || "$sql_url" == "null" ]] && sql_link="-"
    exp_link="[Open Explore]($exp_url)"
    [[ -z "$exp_url" || "$exp_url" == "null" ]] && exp_link="-"
    QUERIES_TABLE+=$'\n'"| $q_idx | $sql_link | $exp_link | $status |"
  done < <(jq -r '.queries[] | "\(.query_index)\t\(.sql_runner_url // "")\t\(.explore_url // "")\t\(.parity_status // "pending")"' "$DATA_JSON")
fi

SUMMARY_BODY=""
if [[ -f "$SESSION_DIR/summary.md" ]]; then
  SUMMARY_BODY=$'\n\n'"$(cat "$SESSION_DIR/summary.md")"
fi

append_details_block() {
  local file_path="$1"
  local label="$2"
  local lang="$3"
  if [[ -f "$file_path" ]]; then
    printf '\n\n<details>\n<summary><code>%s</code></summary>\n\n```%s\n%s\n```\n</details>' \
      "$label" "$lang" "$(head -c 12000 "$file_path")"
  fi
}

ARTIFACTS_SECTION=$'\n\n### Session Artifacts'
ARTIFACTS_SECTION+="$(append_details_block "$SESSION_DIR/input.sql" "input.sql" "sql")"
ARTIFACTS_SECTION+="$(append_details_block "$SESSION_DIR/metrics.md" "metrics.md" "markdown")"
ARTIFACTS_SECTION+="$(append_details_block "$SESSION_DIR/snapshot_check.json" "snapshot_check.json" "json")"
ARTIFACTS_SECTION+="$(append_details_block "$DATA_JSON" "data.json" "json")"

PR_BODY="Automated SQL-to-LookML refactor (\`$RUN_ID\`).$SNAPSHOT_SECTION$QUERIES_TABLE$SUMMARY_BODY$ARTIFACTS_SECTION"

PR_URL=$(gh pr create --repo "$REPO" --head "$HEAD_BRANCH" --base "$BASE_BRANCH" \
  --title "feat(lookml): SQL-to-LookML refactor ($RUN_ID)" \
  --body "$PR_BODY" "${PR_EXTRA_ARGS[@]}")

jq --arg pr "$PR_URL" '. + {pr_url: $pr}' "$DATA_JSON" > "$DATA_JSON.tmp" \
  && mv "$DATA_JSON.tmp" "$DATA_JSON"

COMPARE_COMMENT=""
COMPARE_COMMENT+="$(append_details_block "$SESSION_DIR/compare_initial.json" "compare_initial.json" "json")"
COMPARE_COMMENT+="$(append_details_block "$SESSION_DIR/compare_post_refactor.json" "compare_post_refactor.json" "json")"
if [[ -n "$COMPARE_COMMENT" ]]; then
  gh pr comment "$PR_URL" --repo "$REPO" --body "### SQL-to-LookML Comparison Diagnostics (\`$RUN_ID\`)$COMPARE_COMMENT" >/dev/null || true
fi

echo "$PR_URL"
