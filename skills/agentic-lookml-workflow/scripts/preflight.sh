#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

# Fast-path warm runs when uv, lkr, and gh are already on PATH (pass --upgrade to force reinstall/upgrade)
if [[ "${*:-}" != *"--upgrade"* ]] \
  && command -v uv >/dev/null 2>&1 \
  && command -v lkr >/dev/null 2>&1 \
  && command -v gh >/dev/null 2>&1; then
  gh auth token >/dev/null 2>&1 || gh auth status
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v lkr >/dev/null 2>&1 || [[ "${*:-}" == *"--upgrade"* ]]; then
  uv tool install --upgrade "lkr-dev-cli[tools,code-mode,parse]"
fi
if ! lkr parse lookml snapshot --help 2>&1 | grep -q -- "--allow-additions"; then
  uv tool install --force "lkr-dev-cli[tools,code-mode,parse] @ git+https://github.com/lkrdev/cli.git"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI ('gh') is required on PATH." >&2
  exit 1
fi

gh auth token >/dev/null 2>&1 || gh auth status
