#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

sync_model_includes() {
  local target_dir="${LOOKML_DIR:-.}"
  local model_name="${MODEL_NAME:-${PROJECT_ID:-}}"
  model_name="${model_name//-/_}"
  local conn_name="${CONNECTION_NAME:-}"

  if [[ -z "$model_name" || -z "$conn_name" ]]; then
    return 0
  fi

  local model_file="$target_dir/${model_name}.model.lkml"
  mkdir -p "$target_dir"
  if [[ ! -f "$model_file" ]]; then
    echo "connection: \"$conn_name\"" > "$model_file"
    echo "Created LookML model file: $model_file"
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
    local glob_check="${inc%%:*}"
    local search_dir="$target_dir/${glob_check%/*}"
    local file_pattern="${glob_check##*/}"
    local glob_pat="${inc#*:}"
    local inc_line="include: \"$glob_pat\""
    grep -qxF "$inc_line" "$model_file" 2>/dev/null && continue
    if [[ -d "$search_dir" ]] && find "$search_dir" -name "$file_pattern" 2>/dev/null | grep -q .; then
      echo "$inc_line" >> "$model_file"
    fi
  done
  awk '
    /^[[:space:]]*include:[[:space:]]*["'\'']\/(bronze|silver|gold|tests)(\/explores)?\/\*\.(view|refinement|explore|test)\.lkml["'\''][[:space:]]*$/ {
      sub(/\/\*\./, "/**/*."); gsub(/'\''/, "\"")
    }
    /^[[:space:]]*include:/ {
      key = $0; gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (seen[key]++) next
    }
    { print }
  ' "$model_file" > "${model_file}.tmp" && mv "${model_file}.tmp" "$model_file"
}

# Fast-path model-include sync when LOOKML_DIR or --skip-preflight is used
if [[ " ${*:-} " == *" --skip-preflight "* || -n "${LOOKML_DIR:-}" ]]; then
  sync_model_includes
  exit 0
fi

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
    "looker-expressions"
    "looker-filters"
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
sync_model_includes

# 6. Opt-in: bootstrap GitHub Actions secrets only when --sync-secrets (or SYNC_GH_SECRETS=1) is explicitly passed
if [[ " ${*:-} " == *" --sync-secrets "* || "${SYNC_GH_SECRETS:-}" == "true" || "${SYNC_GH_SECRETS:-}" == "1" ]]; then
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
fi
