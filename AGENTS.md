# AGENTS.md

## Pre-Commit & Testing Workflow

- **Do NOT run full test suites (`pytest` without target files, `make coverage`, `make test-rs`, `ruff check .`, `ty check`) manually.**
- If you need to verify a specific test while working, only run the single targeted test file (e.g. `uv run pytest tests/test_foo.py --no-cov`).
- Full linting, type-checking, Rust tests, and test coverage are configured in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) and run automatically at commit time.
