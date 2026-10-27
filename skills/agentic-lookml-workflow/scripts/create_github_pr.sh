#!/usr/bin/env bash
set -euo pipefail

SESSION_DIR="${1:?Usage: create_github_pr.sh ./data/<run_id>}"
DATA_JSON="$SESSION_DIR/data.json"
[[ -z "${GH_TOKEN:-${GITHUB_TOKEN:-}}" && -f .env ]] && { set -a; source .env; set +a; }
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

RUN_ID=$(jq -r '.run_id' "$DATA_JSON")
REPO=$(jq -r '.git_remote_url' "$DATA_JSON")
HEAD_BRANCH=$(jq -r '.branch_name' "$DATA_JSON")
BASE_BRANCH=$(jq -r '.production_branch // "main"' "$DATA_JSON")

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
  local limit="${4:-12000}"
  if [[ -f "$file_path" ]]; then
    local body
    body=$(if [[ "$label" == "snapshot_check.json" ]]; then jq 'del(.snapshots)' "$file_path" 2>/dev/null || cat "$file_path"; elif [[ "$lang" == "json" ]]; then jq -c . "$file_path" 2>/dev/null || cat "$file_path"; else cat "$file_path"; fi)
    printf '\n\n<details>\n<summary><code>%s</code></summary>\n\n```%s\n%s\n```\n</details>' \
      "$label" "$lang" "${body:0:limit}"
  fi
}

ARTIFACTS_SECTION=$'\n\n### Session Artifacts'
ARTIFACTS_SECTION+="$(append_details_block "$SESSION_DIR/metrics.md" "metrics.md" "markdown" 8000)"
if [[ -f "$DATA_JSON" ]]; then
  DATA_COMPACT=$(jq -c 'del(.test_query_results, .queries[]?.sql_rows)' "$DATA_JSON" 2>/dev/null || cat "$DATA_JSON")
  if (( ${#DATA_COMPACT} > 50000 )); then
    ARTIFACTS_SECTION+=$'\n\n*(data.json omitted from PR description as it exceeds 50,000 characters.)*'
  else
    ARTIFACTS_SECTION+="$(printf '\n\n<details>\n<summary><code>data.json</code></summary>\n\n```json\n%s\n```\n</details>' "$DATA_COMPACT")"
  fi
fi

PR_HEADER="Automated SQL-to-LookML refactor (\`$RUN_ID\`).$SNAPSHOT_SECTION$QUERIES_TABLE"
MAX_SUMMARY=$(( 62000 - ${#PR_HEADER} - ${#ARTIFACTS_SECTION} ))
(( MAX_SUMMARY < 0 )) && MAX_SUMMARY=0
if (( ${#SUMMARY_BODY} > MAX_SUMMARY )); then
  SUMMARY_BODY="${SUMMARY_BODY:0:MAX_SUMMARY}"$'\n\n*(Summary truncated to fit GitHub 65,536-character PR description limit.)*'
fi
PR_BODY="$PR_HEADER$SUMMARY_BODY$ARTIFACTS_SECTION"

PR_URL=$(gh pr create --repo "$REPO" --head "$HEAD_BRANCH" --base "$BASE_BRANCH" \
  --title "feat(lookml): SQL-to-LookML refactor ($RUN_ID)" \
  --body "$PR_BODY" "${PR_EXTRA_ARGS[@]}")

jq --arg pr "$PR_URL" '. + {pr_url: $pr}' "$DATA_JSON" > "$DATA_JSON.tmp" \
  && mv "$DATA_JSON.tmp" "$DATA_JSON"

COMPARE_COMMENT="$(append_details_block "$SESSION_DIR/input.sql" "input.sql" "sql")$(append_details_block "$SESSION_DIR/snapshot_check.json" "snapshot_check.json" "json")$(append_details_block "$SESSION_DIR/compare_initial.json" "compare_initial.json" "json")$(append_details_block "$SESSION_DIR/compare_post_refactor.json" "compare_post_refactor.json" "json")"
if [[ -n "$COMPARE_COMMENT" ]]; then
  gh pr comment "$PR_URL" --repo "$REPO" --body "### SQL-to-LookML Comparison Diagnostics (\`$RUN_ID\`)$COMPARE_COMMENT" >/dev/null || true
fi

echo "$PR_URL"
