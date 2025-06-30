# Testing Dependency Resolution

This project includes tests to ensure that all dependency combinations resolve to the same lock file, maintaining consistency in the dependency tree.

## What the tests verify

The tests ensure that these two commands produce identical lock files:

1. `uv sync --extra all`
2. `uv sync --extra [all individual extras]`

Where "all individual extras" are dynamically discovered from `pyproject.toml` (excluding the `all` extra itself).

This is important because the `all` extra should be equivalent to installing all individual extras together.

## Running the tests

### Option 1: Shell script (recommended for quick testing)

```bash
./tests/test_deps.sh
```

This script will:
- Dynamically discover all individual extras from `pyproject.toml`
- Create temporary directories
- Run both dependency resolution commands
- Compare the resulting lock files
- Clean up automatically

### Option 2: Python test (for CI/CD integration)

```bash
# Run directly
python tests/test_dependency_resolution.py

# Run with pytest
uv run pytest tests/test_dependency_resolution.py -v
```

### Option 3: Makefile target

```bash
make test-deps
```

## What the tests check

1. **Dynamic Extra Discovery**: Automatically discovers all individual extras from `pyproject.toml`
2. **Dependency Resolution Consistency**: Ensures that `--extra all` and `--extra [individual extras]` resolve to the same set of packages
3. **Configuration Validation**: Verifies that all required extras are properly defined in `pyproject.toml`
4. **Lock File Integrity**: Compares SHA256 hashes of generated lock files

## Expected output

When the tests pass, you should see:

```
🔍 Discovering individual extras...
📦 Found individual extras: mcp embed-observability user-attribute-updater
🎉 SUCCESS: All dependency combinations resolve to the same lock file!
✅ Dependency resolution is consistent
```

## Adding new extras

When you add a new extra to `pyproject.toml`, the tests will automatically:

1. Discover the new extra
2. Include it in the dependency resolution test
3. Verify that `--extra all` still includes all dependencies from the new extra

No manual test updates are required!

## Troubleshooting

If the tests fail, it usually means:

1. **Missing dependencies**: The `all` extra doesn't include all the dependencies from individual extras
2. **Version conflicts**: Different dependency combinations resolve to different versions
3. **Configuration issues**: The `pyproject.toml` file has inconsistencies

### Common fixes

1. **Update the `all` extra**: Make sure it includes all dependencies from individual extras
2. **Check for version conflicts**: Ensure that all extras use compatible versions
3. **Verify dependency definitions**: Make sure all extras are properly defined

## CI/CD Integration

The tests are automatically run in GitHub Actions on:
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches
- Manual workflow dispatch

See `.github/workflows/test-dependencies.yml` for the CI configuration. 