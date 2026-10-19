#!/usr/bin/env bash
set -euo pipefail

SESSION_DIR="${1:?Usage: create_github_pr.sh ./data/<run_id>}"
DATA_JSON="$SESSION_DIR/data.json"
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

RUN_ID=$(jq -r '.run_id' "$DATA_JSON")
REPO=$(jq -r '.git_remote_url' "$DATA_JSON")
HEAD_BRANCH=$(jq -r '.branch_name' "$DATA_JSON")
BASE_BRANCH=$(jq -r '.production_branch // "main"' "$DATA_JSON")

FILES=()
for f in input.sql metrics.md compare_initial.json compare_post_refactor.json; do
  [[ -f "$SESSION_DIR/$f" ]] && FILES+=("$SESSION_DIR/$f")
done

GIST_URL=$(gh gist create "${FILES[@]}" --desc "agentic-lookml attachments ($RUN_ID)")
GIST_ID="${GIST_URL##*/}"
ATTACHMENTS=$(gh api "/gists/$GIST_ID" --jq '.files | map_values(.raw_url)')

PR_BODY="Automated SQL-to-LookML refactor (\`$RUN_ID\`).

Attachments: $GIST_URL"

PR_URL=$(gh pr create --repo "$REPO" --head "$HEAD_BRANCH" --base "$BASE_BRANCH" \
  --title "feat(lookml): SQL-to-LookML refactor ($RUN_ID)" \
  --body "$PR_BODY")

jq --arg pr "$PR_URL" --arg gist "$GIST_URL" --argjson att "$ATTACHMENTS" \
  '. + {pr_url: $pr, gist_url: $gist, attachments: $att}' "$DATA_JSON" > "$DATA_JSON.tmp" \
  && mv "$DATA_JSON.tmp" "$DATA_JSON"

gh gist edit "$GIST_ID" --add "$DATA_JSON" >/dev/null
echo "$PR_URL"
