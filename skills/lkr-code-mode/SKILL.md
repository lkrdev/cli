---
name: lkr-code-mode
description: >
  Execute Python code, scripts, or Looker SDK operations against Looker instances using `lkr code-mode sandbox` and the Monty sandbox.
  Use when asked to run Python code against Looker, query explores, inspect LookML models/views, manage dashboards/folders, check user auth, or run Looker SDK recipes.
---

# Looker Code Mode Agent Skill (`lkr code-mode`)

This skill teaches AI agents how to execute Python code and Looker SDK operations against active Looker instances non-interactively using `lkr code-mode sandbox`.

## Mental Model

Instead of exposing hundreds of separate tool definitions (which bloats context windows), `lkr code-mode sandbox` runs Python code inside the Monty sandbox with direct access to all Looker SDK methods as global functions.

- No SDK instantiation needed. Looker SDK methods are pre-bound as globals (such as `me()`, `folder(id)`, `run_inline_query()`, `all_dashboards()`) or accessible via `sdk.<method>()` (such as `sdk.me()`).
- No imports required. Do not write `import looker_sdk`.
- Return values are plain Python dictionaries and lists. Access properties with dictionary keys (`user["id"]`), not attribute dot notation (`user.id`).
- Always return the final result. Avoid `print()` statements so the output is cleanly structured JSON.

## Installation

Install into your agent workspace using `npx skills`:

```bash
npx skills add lkrdev/cli --skill lkr-code-mode
```

## Command Discovery and CLI Help

Inspect CLI options, authentication subcommands, or sandbox parameters:

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

## Command Execution Syntax

### Direct Inline Code Execution (`--code` / `-c`)

```bash
# In local repository workspace:
uv run lkr code-mode sandbox --code="return me()"

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --code="return me()"
```

### Script File Execution (`--file` / `-f`)

Run standalone script files directly or execute pre-built scripts located in `scripts/`:

```bash
# Execute pre-built helper scripts:
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/personal_folder_dashboards.py
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/order_items_query.py
uv run lkr code-mode sandbox --file=./skills/lkr-code-mode/scripts/traverse_folders.py

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --file=./path/to/script.py
```

### Injected Variables (`--var` / `-v`)

Inject string variables into the sandbox as top-level Python identifiers:

```bash
uv run lkr code-mode sandbox --file=./script.py --var project=my_project --var folder_id=123
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --file=./script.py -v project=my_project -v folder_id=123
```

Inside `script.py`, `project` and `folder_id` are directly accessible as global strings:

```python
# script.py
p = project
f = folder(folder_id)
return {"project": p, "folder_name": f.get("name")}
```

### Development Mode (`--dev-mode`)

Run operations in Looker Development Mode:

```bash
uv run lkr code-mode sandbox --dev-mode --code="return all_projects()"
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --dev-mode --code="return all_projects()"
```

## Authentication Workflow and Pre-Flight Checks

Perform this check once per conversation when establishing the Looker connection. Once verified or when an active session exists, subsequent sandbox commands reuse the session directly.

### Step 1: Prompt for Authentication Preference

Prompt the user to choose their preferred authentication method:
- OAuth (Interactive user session)
- API Key (`LOOKERSDK_*` environment variables)

### Step 2: Session Management and Verification

Check existing credentials and verify connectivity:

```bash
# List configured OAuth accounts
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli auth list
uv run lkr auth list

# Verify current authentication and active user
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli auth whoami
uv run lkr auth whoami
```

### Step 3: OAuth Pre-Flight Verification and Login Flow

If OAuth is selected and no active account is configured, perform this setup once:

1. Prompt the user for their Looker instance URL (e.g. `https://mycompany.looker.com`).
2. Run a pre-flight `GET` check against the instance auth endpoint before opening a browser:
   ```
   https://<instance_url>/auth?client_id=lkr-cli&redirect_uri=YOUR_REDIRECT_URI&response_type=code&scope=api&state=YOUR_UNIQUE_STATE_STRING&code_challenge=CHALLENGE_STRING&code_challenge_method=S256
   ```
3. If the response HTML contains "The OAuth client was not found", inform the user that `lkr-cli` is not registered on their Looker instance and link them to the configuration guide at [https://www.lkr.dev/docs/tools/cli/#oauth2-prerequisites](https://www.lkr.dev/docs/tools/cli/#oauth2-prerequisites).
4. If the client is detected (the response returns "redirect_uri mismatch"), run the interactive login command:
   ```bash
   uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli auth login
   ```

### Step 4: Authentication Execution Options

Execute codemode directly via CLI (`lkr-dev-cli code-mode sandbox --code="..."`) instead of running an MCP server. Pass `--oauth-account` or `uvx --env-file=.env` so credentials stay out of version-controlled files:

#### Named OAuth Profiles (`--oauth-account`)
```bash
# Local workspace execution:
uv run lkr --oauth-account=abc code-mode sandbox --code="return me()"

# Using uvx:
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli --oauth-account=abc code-mode sandbox --code="return me()"
```

#### Custom Environment File (`--env-file`)
```bash
# Passed to uvx directly:
uvx --env-file .env --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox --code="return me()"

# Passed to lkr CLI:
uv run lkr --env-file=.env code-mode sandbox --code="return me()"
```

#### Force OAuth Flow (`--force-oauth`)
```bash
uv run lkr --force-oauth code-mode sandbox --code="return me()"
uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli --force-oauth code-mode sandbox --code="return me()"
```

#### Standard Environment Variables
- `LOOKERSDK_BASE_URL`: Looker instance API URL (e.g. `https://your-instance.looker.com:19999` or `https://your-instance.looker.com`)
- `LOOKERSDK_CLIENT_ID`: API3 client ID
- `LOOKERSDK_CLIENT_SECRET`: API3 client secret
- `LOOKERSDK_VERIFY_SSL`: `true` or `false` (default: `true`)

## SDK Discovery Builtins

Use these built-in sandbox functions to explore available Looker SDK methods, schemas, and types:

| Function | Description | Example |
| :--- | :--- | :--- |
| `dir()` | Lists all available SDK methods | `return [m for m in dir() if 'dashboard' in m]` |
| `help(pattern)` | Search SDK methods matching pattern | `return help('dashboard')` |
| `lookup(method_name)` | Get full docstring and signature for a method | `return lookup('search_dashboards')` |
| `search_with_lookups(pattern)` | Get docstrings for all matching methods | `return search_with_lookups('board_item')` |
| `lookup_type(type_name)` | Inspect fields and types of a Looker model | `return lookup_type('Dashboard')` |
| `examples()` | Built-in SDK code recipes | `return examples()` |
| `readme()` | Full reference documentation | `return readme()` |

## Bundled Helper Scripts (`scripts/`)

Pre-packaged scripts are located in `scripts/`:

- [scripts/personal_folder_dashboards.py](./scripts/personal_folder_dashboards.py): Inspects `me()`, extracts `personal_folder_id`, and returns personal folder dashboards.
- [scripts/order_items_query.py](./scripts/order_items_query.py): Runs an inline query on `thelook` / `order_items` with `created_year` and `users.count` filtered by `status: Returned`.
- [scripts/traverse_folders.py](./scripts/traverse_folders.py): Recursively collects dashboards and looks across all subfolders.
- [scripts/readme.py](./scripts/readme.py): Reference documentation generator.
- [scripts/examples.py](./scripts/examples.py): Built-in code examples collection.

## Common Looker SDK Recipes

### Inspect User and Personal Folder Dashboards

Get the authenticated user, inspect their `personal_folder_id`, and retrieve all dashboards in their personal folder:

```python
user = me()
if not user:
    return {"error": "Unable to retrieve current user metadata."}

personal_folder_id = user.get("personal_folder_id")
if not personal_folder_id:
    return {"error": "User does not have a personal folder configured."}

personal_folder = folder(personal_folder_id)
if not personal_folder:
    return {"error": f"Unable to retrieve folder with ID {personal_folder_id}."}

return {
    "user_id": user.get("id"),
    "user_email": user.get("email"),
    "personal_folder_id": personal_folder_id,
    "dashboards": personal_folder.get("dashboards", []),
}
```

### Recursively Traverse Folders for Dashboards and Looks

Traverse a personal folder and all nested subfolders to gather all dashboards and looks:

```python
def get_all_items(folder_id):
    if not folder_id:
        return {"dashboards": [], "looks": []}
    f = folder(folder_id)
    if not f:
        return {"dashboards": [], "looks": []}
    items = {"dashboards": f.get("dashboards", []), "looks": f.get("looks", [])}
    children = folder_children(folder_id) or []
    for child in children:
        child_items = get_all_items(child.get("id"))
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items

user_data = me()
if not user_data or not user_data.get("personal_folder_id"):
    return {"dashboards": [], "looks": []}
return get_all_items(user_data["personal_folder_id"])
```

### Run an Inline Explore Query on `thelook` (`order_items`)

Execute an inline query on model `thelook`, explore `order_items`, with fields `order_items.created_year` and `users.count`, filtered by `order_items.status: Returned`:

```python
return run_inline_query(
    result_format="json",
    body={
        "model": "thelook",
        "view": "order_items",
        "fields": [
            "order_items.created_year",
            "users.count",
        ],
        "filters": {
            "order_items.status": "Returned",
        },
        "sorts": ["order_items.created_year desc"],
        "limit": "500",
    },
)
```

### Inspect LookML Models and Explores

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
    "sample_measures": measures[:5],
}
```

### Manage LookML Projects and Git Branches

List all LookML projects and inspect git branch state:

```python
projects = all_projects(fields="id,name,git_remote_url")
project_name = projects[0]["id"] if projects else None

branches = git_branches(project_name) if project_name else []
return {
    "projects": projects,
    "selected_project": project_name,
    "branches": branches,
}
```

### Search Dashboards with Field Filtering

Always specify `fields` when querying collections on large instances to prevent timeouts:

```python
return search_dashboards(
    title="Marketing%",
    fields="id,title,folder,user_id,created_at",
    limit=20,
)
```

## Agent Guidelines for Non-Interactive Execution

- Run `me()` once early in a task to verify authentication before executing multiple operations.
- Responses are JSON primitives. Write `dash["title"]` instead of `dash.title`.
- Always filter returned attributes with `fields` (e.g. `fields="id,title"`) when querying large instances.
- Pass `--dev-mode` on the CLI when making changes against LookML files or personal dev branches.
- Always return structured objects (dicts, lists, strings). Do not use `print()` statements.
