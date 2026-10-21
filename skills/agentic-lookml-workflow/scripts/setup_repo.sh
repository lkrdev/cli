#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. Run CLI preflight (uv, lkr-dev-cli[tools,code-mode,parse], gh auth) unless skipped
if [[ "${*:-}" != *"--skip-preflight"* && -z "${LOOKML_DIR:-}" ]]; then
  bash "$SCRIPT_DIR/preflight.sh"
fi

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
if [[ -s .gitignore ]] && [ "$(tail -c 1 .gitignore)" != $'\n' ]; then
  echo "" >> .gitignore
fi
for pattern in ".env" "data/" "tmp/"; do
  if ! grep -qxF "$pattern" .gitignore 2>/dev/null; then
    echo "$pattern" >> .gitignore
  fi
done

# 5. Create or update <model_name>.model.lkml if MODEL_NAME and CONNECTION_NAME are provided
TARGET_LOOKML_DIR="${LOOKML_DIR:-.}"
MODEL_NAME="${MODEL_NAME:-${PROJECT_ID:-}}"
MODEL_NAME="${MODEL_NAME//-/_}"
CONNECTION_NAME="${CONNECTION_NAME:-}"

if [[ -n "$MODEL_NAME" && -n "$CONNECTION_NAME" ]]; then
  MODEL_FILE="$TARGET_LOOKML_DIR/${MODEL_NAME}.model.lkml"
  mkdir -p "$TARGET_LOOKML_DIR"
  if [[ ! -f "$MODEL_FILE" ]]; then
    echo "connection: \"$CONNECTION_NAME\"" > "$MODEL_FILE"
    echo "Created LookML model file: $MODEL_FILE"
  fi
  for inc in \
    "bronze/*.view.lkml:/bronze/**/*.view.lkml" \
    "bronze/*.refinement.lkml:/bronze/**/*.refinement.lkml" \
    "bronze/explores/*.explore.lkml:/bronze/explores/**/*.explore.lkml" \
    "silver/*.view.lkml:/silver/**/*.view.lkml" \
    "silver/explores/*.explore.lkml:/silver/explores/**/*.explore.lkml" \
    "gold/*.view.lkml:/gold/**/*.view.lkml" \
    "gold/explores/*.explore.lkml:/gold/explores/**/*.explore.lkml" \
    "tests/*.test.lkml:/tests/**/*.test.lkml"; do
    inc_line="include: \"${inc#*:}\""
    if find "$TARGET_LOOKML_DIR" -path "$TARGET_LOOKML_DIR/${inc%%:*}" 2>/dev/null | grep -q .; then
      grep -qxF "$inc_line" "$MODEL_FILE" 2>/dev/null || echo "$inc_line" >> "$MODEL_FILE"
    fi
  done
fi

# 6. Sync required GitHub Actions secrets (LOOKERSDK_BASE_URL, LOOKERSDK_CLIENT_ID, LOOKERSDK_CLIENT_SECRET, LOOKER_PROJECT_NAME) if missing
EXISTING_SECRETS=$(gh secret list --json name --jq '.[].name' 2>/dev/null || true)
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
    printf '%s' "$v" | gh secret set "$k" 2>/dev/null \
      || printf '%s' "$v" | env -u GH_TOKEN -u GITHUB_TOKEN gh secret set "$k" 2>/dev/null \
      || true
  fi
done
