# AGENTS.md

## Pre-Commit & Testing Workflow

- **Do NOT run full test suites (`pytest` without target files, `make coverage`, `make test-rs`, `ruff check .`, `ty check`) manually.**
- If you need to verify a specific test while working, only run the single targeted test file (e.g. `uv run pytest tests/test_foo.py --no-cov`).
- Full linting, type-checking, Rust tests, and test coverage are configured in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) and run automatically at commit time.

## ExtendedLooker40SDK & Monty Sandbox Rule

- Every public method added to `ExtendedLooker40SDK` (`lkr/extended_sdk_methods/main.py`) **must** be runnable inside the Monty sandbox (`pydantic_monty` and `lkr/codemode/wasm/`):
  1. **Single-endpoint HTTP wrappers** call `self.get` / `self.post` / `self.put` / `self.patch` / `self.delete` in `main.py` and register an `OperationMeta` in `lkr/codemode/wasm/build.rs`.
  2. **Multi-step / composite methods** must be implemented in pure Monty-compatible Python (no stdlib `import` statements, no `concurrent.futures` / `threading` / `re` / `copy` / `json` modules) after `# --- MONTY_KDA_PREAMBLE ---` in `lkr/extended_sdk_methods/_kda_monty.py`, registered in `lkr/codemode/wasm/build.rs`, and added to the preamble injection condition in `lkr/codemode/wasm/src/lib.rs`.
  3. Enforced by `test_extended_sdk_monty_sandbox_parity_and_execution` in `tests/test_extended_sdk_methods.py`.

