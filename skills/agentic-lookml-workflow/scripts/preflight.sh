#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

if ! command -v lkr >/dev/null 2>&1; then
  uv tool install "lkr-dev-cli[tools,code-mode,parse]"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI ('gh') is required on PATH." >&2
  exit 1
fi

export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
gh auth status
