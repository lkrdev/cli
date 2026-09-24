# AGENTS.md

## Pre-Commit & Testing Workflow

- **Do NOT run tests, coverage, `ty check`, or `ruff check` after every individual file edit or change.**
- Linting (`uv run ruff check .`), type-checking (`uv run ty check`), Rust unit tests/clippy (`make test-rs`), and Python/Rust test coverage (`make coverage`) are configured via [`.pre-commit-config.yaml`](.pre-commit-config.yaml) (powered by [`astral-sh/uv-pre-commit`](https://github.com/astral-sh/uv-pre-commit)) and run automatically at commit time.
- Focus on completing your logical unit of work first; let `pre-commit` (or a single verification pass right before committing) run the full check and coverage suite.
