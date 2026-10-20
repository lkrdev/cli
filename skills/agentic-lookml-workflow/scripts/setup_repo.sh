#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. Run CLI preflight (uv, lkr-dev-cli[tools,code-mode,parse], gh auth)
bash "$SCRIPT_DIR/preflight.sh"

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: 'jq' is required on PATH." >&2
  exit 1
fi

# 2. Ensure companion skills are installed when running in an external LookML repository
if [[ ! -d "skills/agentic-lookml-workflow" ]]; then
  REQUIRED_SKILLS=(
    "agentic-lookml"
    "agentic-lookml-workflow"
    "generate-view-from-table"
    "lkr-code-mode"
    "lkr-project-helper"
    "lookml"
    "lookml-field-curation"
  )
  MISSING_SKILLS=()
  for s in "${REQUIRED_SKILLS[@]}"; do
    if [[ ! -f ".agents/skills/$s/SKILL.md" ]]; then
      MISSING_SKILLS+=("$s")
    fi
  done
  if [[ ${#MISSING_SKILLS[@]} -gt 0 ]] && command -v npx >/dev/null 2>&1; then
    for s in "${MISSING_SKILLS[@]}"; do
      npx skills add lkrdev/cli --skill "$s" -y
    done
  fi
fi

# 3. Ensure .github/workflows/lookml-pr-checks.yml is present
mkdir -p .github/workflows
WORKFLOW_SRC="$SKILL_DIR/examples/lookml-pr-checks.yml"
WORKFLOW_DST=".github/workflows/lookml-pr-checks.yml"
if [[ -f "$WORKFLOW_SRC" ]]; then
  cp "$WORKFLOW_SRC" "$WORKFLOW_DST"
  echo "Installed GitHub workflow: $WORKFLOW_DST"
fi

# 4. Ensure .gitignore protects local .env and scratch directories
touch .gitignore
for pattern in ".env" "data/" "tmp/"; do
  if ! grep -qxF "$pattern" .gitignore 2>/dev/null; then
    echo "$pattern" >> .gitignore
  fi
done

# 5. Create initial <model_name>.model.lkml if MODEL_NAME and CONNECTION_NAME are provided and no model file exists
TARGET_LOOKML_DIR="${LOOKML_DIR:-.}"
MODEL_NAME="${MODEL_NAME:-${PROJECT_ID:-}}"
MODEL_NAME="${MODEL_NAME//-/_}"
CONNECTION_NAME="${CONNECTION_NAME:-}"

if [[ -n "$MODEL_NAME" && -n "$CONNECTION_NAME" ]]; then
  MODEL_FILE="$TARGET_LOOKML_DIR/${MODEL_NAME}.model.lkml"
  if [[ ! -f "$MODEL_FILE" ]]; then
    mkdir -p "$TARGET_LOOKML_DIR"
    {
      echo "connection: \"$CONNECTION_NAME\""
      for inc in \
        "bronze/*.view.lkml:/bronze/**/*.view.lkml" \
        "bronze/*.refinement.lkml:/bronze/**/*.refinement.lkml" \
        "bronze/explores/*.explore.lkml:/bronze/explores/**/*.explore.lkml" \
        "silver/*.view.lkml:/silver/**/*.view.lkml" \
        "silver/explores/*.explore.lkml:/silver/explores/**/*.explore.lkml" \
        "gold/*.view.lkml:/gold/**/*.view.lkml" \
        "gold/explores/*.explore.lkml:/gold/explores/**/*.explore.lkml" \
        "tests/*.test.lkml:/tests/**/*.test.lkml"; do
        find "$TARGET_LOOKML_DIR" -path "$TARGET_LOOKML_DIR/${inc%%:*}" 2>/dev/null | grep -q . \
          && echo "include: \"${inc#*:}\"" || true
      done
    } > "$MODEL_FILE"
    echo "Created LookML model file: $MODEL_FILE"
  fi
fi
