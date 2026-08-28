---
name: lkr-code-mode
description: >
  Execute Python code, scripts, or Looker SDK operations against Looker instances using `lkr code-mode sandbox` and the Monty sandbox.
  Use when asked to run Python code against Looker, query explores, inspect LookML models/views, manage dashboards/folders, check user auth, or run Looker SDK recipes.
---

# Looker Code Mode Agent Skill (`lkr code-mode`)

This skill teaches AI agents how to execute Python code and Looker SDK operations against active Looker instances non-interactively using `lkr code-mode sandbox`.

## Mental Model

Instead of exposing hundreds of separate tool definitions (which bloats context windows), `lkr code-mode sandbox` runs Python code inside the **Monty sandbox** with direct access to all Looker SDK methods as global functions.

- **No SDK Instantiation**: All Looker SDK methods are pre-bound as globals (e.g. `me()`, `folder(id)`, `run_inline_query()`, `all_dashboards()`) or accessible via `sdk.<method>()` (e.g. `sdk.me()`).
- **No Imports Required**: Do not write `import looker_sdk`.
- **Primitive Return Values**: Returned Looker models are plain Python dictionaries and lists. Access properties with `dict["key"]` (e.g. `user["id"]`), not attribute dot notation (`user.id`).
- **Return Values Directly**: Always `return` the final result. Avoid `print()` statements so the output is cleanly structured JSON.

---

## Installation

Install into your agent workspace using `npx skills`:

```bash
npx skills add lkrdev/cli --skill lkr-code-mode
```

---

## Command Discovery & CLI Help

When inspecting CLI options, authentication subcommands, or sandbox parameters:

```bash
# General CLI help
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli --help
uv run lkr --help

# Authentication commands (login, logout, whoami, list)
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli auth --help
uv run lkr auth --help

# Code-mode subcommands (sandbox, run)
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode --help
uv run lkr code-mode --help

# Sandbox specific options (--code, --file, --var, --dev-mode)
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --help
uv run lkr code-mode sandbox --help
```

---

## Command Execution Syntax

### 1. Direct Inline Code Execution (`--code` / `-c`)

```bash
# In local repository workspace:
uv run lkr code-mode sandbox --code="return me()"

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --code="return me()"
```

### 2. Script File Execution (`--file` / `-f`)

You can run script files directly or execute the pre-built scripts located in `scripts/`:

```bash
# Execute pre-built helper scripts:
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/personal_folder_dashboards.py
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/order_items_query.py
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/traverse_folders.py

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --file=./path/to/script.py
```

### 3. Injected Variables (`--var` / `-v`)

Inject string variables into the sandbox as top-level Python identifiers:

```bash
uv run lkr code-mode sandbox --file=./script.py --var project=my_project --var folder_id=123
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --file=./script.py -v project=my_project -v folder_id=123
```

Inside `script.py`, `project` and `folder_id` are directly accessible as global strings:

```python
# script.py
p = project  # "my_project"
f = folder(folder_id)
return {"project": p, "folder_name": f.get("name")}
```

### 4. Development Mode (`--dev-mode`)

Run operations in Looker Development Mode (workspace context):

```bash
uv run lkr code-mode sandbox --dev-mode --code="return all_projects()"
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode --code="return all_projects()"
```

---

## Authentication Options

`lkr` / `lkr-dev-cli` supports multiple authentication mechanisms. Pass flags before the `code-mode` subcommand:

### 1. Named OAuth Profiles (`--oauth-account`)

Use a specific saved OAuth profile from the local credential store:

```bash
# Local workspace execution:
uv run lkr --oauth-account=abc code-mode sandbox --code="return me()"

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli --oauth-account=abc code-mode sandbox --code="return me()"
```

### 2. Custom Environment File (`--env-file`)

Load credentials and configuration from a specific `.env` file:

```bash
# Passed to uvx directly:
uvx --env-file .env --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --code="return me()"

# Passed to lkr CLI:
uv run lkr --env-file=.env code-mode sandbox --code="return me()"
```

### 3. Force OAuth Flow (`--force-oauth`)

Forces PKCE OAuth authentication flow even if API keys are configured:

```bash
uv run lkr --force-oauth code-mode sandbox --code="return me()"
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli --force-oauth code-mode sandbox --code="return me()"
```

### 4. Standard Environment Variables

Set standard Looker SDK environment variables in the execution environment:
- `LOOKERSDK_BASE_URL`: Looker instance API URL (e.g. `https://your-instance.looker.com:19999` or `https://your-instance.looker.com`)
- `LOOKERSDK_CLIENT_ID`: API3 client ID
- `LOOKERSDK_CLIENT_SECRET`: API3 client secret
- `LOOKERSDK_VERIFY_SSL`: `true` or `false` (default: `true`)

---

## SDK Discovery Builtins

When exploring available methods, schemas, and types in the Looker SDK, use these built-in sandbox functions:

| Function | Description | Example |
| :--- | :--- | :--- |
| `dir()` | Lists all available SDK methods | `return [m for m in dir() if 'dashboard' in m]` |
| `help(pattern)` | Search SDK methods matching pattern | `return help('dashboard')` |
| `lookup(method_name)` | Get full docstring and signature for a method | `return lookup('search_dashboards')` |
| `search_with_lookups(pattern)` | Get docstrings for all matching methods | `return search_with_lookups('board_item')` |
| `lookup_type(type_name)` | Inspect fields and types of a Looker model | `return lookup_type('Dashboard')` |
| `examples()` | Built-in SDK code recipes | `return examples()` |
| `readme()` | Full reference documentation | `return readme()` |

---

## Bundled Helper Scripts (`scripts/`)

Pre-packaged scripts are located in `scripts/`:

- **[`scripts/personal_folder_dashboards.py`](file:///usr/local/google/home/bryanweber/lkrdev/cli/skills/lkr-code-mode/scripts/personal_folder_dashboards.py)**: Inspects `me()`, extracts `personal_folder_id`, and returns personal folder dashboards.
- **[`scripts/order_items_query.py`](file:///usr/local/google/home/bryanweber/lkrdev/cli/skills/lkr-code-mode/scripts/order_items_query.py)**: Runs an inline query on `thelook` / `order_items` with `created_year` and `users.count` filtered by `status: Returned`.
- **[`scripts/traverse_folders.py`](file:///usr/local/google/home/bryanweber/lkrdev/cli/skills/lkr-code-mode/scripts/traverse_folders.py)**: Recursively collects dashboards and looks across all subfolders.
- **[`scripts/readme.py`](file:///usr/local/google/home/bryanweber/lkrdev/cli/skills/lkr-code-mode/scripts/readme.py)**: Reference documentation generator.
- **[`scripts/examples.py`](file:///usr/local/google/home/bryanweber/lkrdev/cli/skills/lkr-code-mode/scripts/examples.py)**: Built-in code examples collection.

---

## Common Looker SDK Recipes

### Recipe 1: Inspect User & Personal Folder Dashboards

Get the authenticated user, inspect their `personal_folder_id`, and retrieve all dashboards in their personal folder:

```python
user = me()
personal_folder_id = user["personal_folder_id"]

# Fetch folder content
personal_folder = folder(personal_folder_id)

# Return personal folder dashboards
return {
    "user_id": user.get("id"),
    "user_email": user.get("email"),
    "personal_folder_id": personal_folder_id,
    "dashboards": personal_folder.get("dashboards", [])
}
```

### Recipe 2: Recursively Traverse Folders for Dashboards & Looks

Traverse a personal folder and all nested subfolders to gather all dashboards and looks:

```python
def get_all_items(folder_id):
    f = folder(folder_id)
    items = {
        "dashboards": f.get("dashboards", []),
        "looks": f.get("looks", [])
    }
    for child in folder_children(folder_id):
        child_items = get_all_items(child["id"])
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items

user_data = me()
return get_all_items(user_data["personal_folder_id"])
```

### Recipe 3: Run an Inline Explore Query on `thelook` (`order_items`)

Execute an inline query on model `thelook`, explore `order_items`, with fields `order_items.created_year` and `users.count`, filtered by `order_items.status: Returned`:

```python
return run_inline_query(
    result_format="json",
    body={
        "model": "thelook",
        "view": "order_items",
        "fields": [
            "order_items.created_year",
            "users.count"
        ],
        "filters": {
            "order_items.status": "Returned"
        },
        "sorts": ["order_items.created_year desc"],
        "limit": "500"
    }
)
```

### Recipe 4: Inspect LookML Models and Explores

Inspect model configuration and extract available fields (dimensions and measures) from an explore:

```python
explore = lookml_model_explore("thelook", "order_items")

fields = explore.get("fields", {})
dimensions = [d["name"] for d in fields.get("dimensions", [])]
measures = [m["name"] for m in fields.get("measures", [])]

return {
    "model": "thelook",
    "explore": "order_items",
    "total_dimensions": len(dimensions),
    "total_measures": len(measures),
    "sample_dimensions": dimensions[:5],
    "sample_measures": measures[:5]
}
```

### Recipe 5: Manage LookML Projects & Git Branches

List all LookML projects and inspect git branch state:

```python
projects = all_projects(fields="id,name,git_remote_url")
project_name = projects[0]["id"] if projects else None

branches = git_branches(project_name) if project_name else []
return {
    "projects": projects,
    "selected_project": project_name,
    "branches": branches
}
```

### Recipe 6: Search Dashboards with Field Filtering

Always specify `fields` when querying collections on large instances to prevent timeouts:

```python
return search_dashboards(
    title="Marketing%",
    fields="id,title,folder,user_id,created_at",
    limit=20
)
```

---

## Agent Guidelines for Non-Interactive Execution

1. **Verify Auth First**: When starting a multi-step task, run `me()` first to verify connection and credentials before executing heavy operations.
2. **Use Dictionary Indexing**: Responses are JSON primitives. Write `dash["title"]` instead of `dash.title`.
3. **Prevent Timeouts with `fields`**: Large Looker instances contain thousands of folders and dashboards. Always filter returned attributes (e.g. `fields="id,title"`).
4. **Dev Mode Isolation**: When testing or making changes against LookML files or dev branches, pass `--dev-mode` on the CLI.
5. **No `print()` Output**: Always `return` structured objects (dicts/lists/strings). Avoid `print()` statements.
