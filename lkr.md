# `lkr`

A CLI for Looker with helpful tools

**Usage**:

```console
$ lkr [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--version`: Show the version and exit.
* `--client-id <str>`: [env var: LOOKERSDK_CLIENT_ID]
* `--client-secret <str>`: [env var: LOOKERSDK_CLIENT_SECRET]
* `--base-url <str>`: [env var: LOOKERSDK_BASE_URL]
* `--log-level <DEBUG|INFO|WARNING|ERROR|CRITICAL>`: [env var: LOG_LEVEL]
* `--quiet`
* `--force-oauth`
* `--dev`
* `--oauth-account <str>`: OAuth account to lookup in DB and use regardless of what&#x27;s active
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `db-template`
* `auth`: Authentication commands for LookML Repository
* `schema`: Generate and validate strongly-typed...
* `mcp`
* `observability`
* `tools`
* `code-mode`

## `lkr db-template`

**Usage**:

```console
$ lkr db-template [OPTIONS]
```

**Options**:

* `--import-error <str>`: [default: No module named &#x27;lkr.db_template.main&#x27;]

## `lkr auth`

Authentication commands for LookML Repository

**Usage**:

```console
$ lkr auth [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `login`: Login to Looker instance using OAuth2 or...
* `logout`: Logout and clear saved credentials
* `whoami`: Check current authentication
* `list`: List all authenticated Looker instances

### `lkr auth login`

Login to Looker instance using OAuth2 or switch to an existing authenticated instance

**Usage**:

```console
$ lkr auth login [OPTIONS]
```

**Options**:

* `-I, --instance-name <str>`: Name of the Looker instance to login or switch to
* `-p, --port <int range>`: Port to run the local OAuth redirect web server on  [1&lt;=x&lt;=65535]
* `--help`: Show this message and exit.

### `lkr auth logout`

Logout and clear saved credentials

**Usage**:

```console
$ lkr auth logout [OPTIONS]
```

**Options**:

* `--instance-name <str>`: Name of the Looker instance to logout from. If not provided, logs out from all instances.
* `--all`: Logout from all instances
* `--help`: Show this message and exit.

### `lkr auth whoami`

Check current authentication

**Usage**:

```console
$ lkr auth whoami [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

### `lkr auth list`

List all authenticated Looker instances

**Usage**:

```console
$ lkr auth list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `lkr schema`

Generate and validate strongly-typed Looker Explore query schemas

**Usage**:

```console
$ lkr schema [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `generate`: Generate a strongly-typed run_inline_query...
* `validate`: Validate a query (--query or --query-file)...

### `lkr schema generate`

Generate a strongly-typed run_inline_query JSON Schema for --model and --explore.

**Usage**:

```console
$ lkr schema generate [OPTIONS]
```

**Options**:

* `-m, --model <str>`: LookML model name  [required]
* `-e, --explore <str>`: LookML explore name  [required]
* `-f, --explore-file <path>`: Path to a local lookml_model_explore JSON file (e.g. tmp/order_items.json)
* `-o, --output <path>`: Optional file path to write the generated JSON schema
* `--help`: Show this message and exit.

### `lkr schema validate`

Validate a query (--query or --query-file) against an Explore schema.

**Usage**:

```console
$ lkr schema validate [OPTIONS]
```

**Options**:

* `-m, --model <str>`: LookML model name
* `-e, --explore <str>`: LookML explore name
* `-f, --explore-file <path>`: Path to a local lookml_model_explore JSON file (e.g. tmp/order_items.json)
* `--schema <str>`: Inline JSON schema string (optional; if omitted, generates schema from --model and --explore)
* `--schema-file <path>`: Path to a generated JSON schema file (optional; if omitted, generates schema from --model and --explore)
* `-q, --query <str>`: Inline query JSON string (either full run_inline_query payload or body WriteQuery)
* `--query-file <path>`: Path to a query JSON file (either full run_inline_query payload or body WriteQuery)
* `--help`: Show this message and exit.

## `lkr mcp`

**Usage**:

```console
$ lkr mcp [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `run`

### `lkr mcp run`

**Usage**:

```console
$ lkr mcp run [OPTIONS]
```

**Options**:

* `--debug / --no-debug`: Debug mode  [default: no-debug]
* `--help`: Show this message and exit.

## `lkr observability`

**Usage**:

```console
$ lkr observability [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `embed`: Start the observability FastAPI server.

### `lkr observability embed`

Start the observability FastAPI server.

**Usage**:

```console
$ lkr observability embed [OPTIONS]
```

**Options**:

* `--host <str>`: Host to bind to  [env var: HOST; default: 0.0.0.0]
* `--port <int>`: Port to bind to  [env var: PORT; default: 8080]
* `--timeout <int>`: Timeout for the health check  [env var: TIMEOUT; default: 120]
* `--event-prefix <str>`: Event prefix  [env var: EVENT_PREFIX; default: lkr-observability]
* `--help`: Show this message and exit.

## `lkr tools`

**Usage**:

```console
$ lkr tools [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `user-attribute-updater`
* `schedule-download-deprecation`: Build a table of users and their...
* `lookml`: LookML synchronization and deployment tools

### `lkr tools user-attribute-updater`

**Usage**:

```console
$ lkr tools user-attribute-updater [OPTIONS]
```

**Options**:

* `--host <str>`: [env var: HOST; default: 127.0.0.1]
* `--port <int>`: [env var: PORT; default: 8080]
* `--help`: Show this message and exit.

### `lkr tools schedule-download-deprecation`

Build a table of users and their scheduling/downloading permissions per model.

**Usage**:

```console
$ lkr tools schedule-download-deprecation [OPTIONS]
```

**Options**:

* `--limit <int>`: Search batch size  [default: 500]
* `--model-offset <int>`: Offset for model columns  [default: 0]
* `--csv`: Output as CSV instead of a table
* `--csv-file-name <str>`: Name for the output CSV file (without extension)  [default: schedule_download_deprecation]
* `--unfiltered`: Show all rows, including those with no missing permissions
* `--email`: Use Email instead of Name
* `--help`: Show this message and exit.

### `lkr tools lookml`

LookML synchronization and deployment tools

**Usage**:

```console
$ lkr tools lookml [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `push`: Push local files to Looker, removing files...
* `pull`: Pull remote files from Looker to local...
* `deploy`: Commit dev workspace and deploy Looker...

#### `lkr tools lookml push`

Push local files to Looker, removing files on the instance that aren&#x27;t being pushed.
If --file / -f is specified (or folder_name is a file), only that single file is pushed without deleting remote orphans.

**Usage**:

```console
$ lkr tools lookml push [OPTIONS] {folder_name}
```

**Arguments**:

* `folder_name`: Local folder name / Looker project ID to push  [required]

**Options**:

* `--project-id, --project <str>`: Looker project ID to push to (if different from folder name)
* `-f, --file <str>`: Single file relative path (or absolute path) to push
* `--deploy`: Commit and deploy to production after push
* `--reset / --no-reset`: Reset developer workspace to production before pushing  [default: reset]
* `--message <str>`: Commit message when deploying  [default: push from lkr cli]
* `--help`: Show this message and exit.

#### `lkr tools lookml pull`

Pull remote files from Looker to local disk, removing local files that aren&#x27;t on the instance.
If --file / -f is specified, only that single file is pulled without deleting local orphans.

**Usage**:

```console
$ lkr tools lookml pull [OPTIONS] {folder_name}
```

**Arguments**:

* `folder_name`: Local folder name / Looker project ID to pull into  [required]

**Options**:

* `--project-id, --project <str>`: Looker project ID to pull from (if different from folder name)
* `-f, --file <str>`: Single file relative path to pull from Looker
* `--deploy`: Commit and deploy to production on Looker after pull
* `--message <str>`: Commit message when deploying  [default: pull from lkr cli then commit and deploy]
* `--help`: Show this message and exit.

#### `lkr tools lookml deploy`

Commit dev workspace and deploy Looker project to production.

**Usage**:

```console
$ lkr tools lookml deploy [OPTIONS] [folder_name]
```

**Arguments**:

* `folder_name`: Local folder name / Looker project ID to deploy

**Options**:

* `--project-id, --project <str>`: Looker project ID to deploy (if folder_name not specified)
* `--message <str>`: Commit message  [default: commit and deploy from lkr cli]
* `--help`: Show this message and exit.

## `lkr code-mode`

**Usage**:

```console
$ lkr code-mode [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `sandbox`
* `run`

### `lkr code-mode sandbox`

**Usage**:

```console
$ lkr code-mode sandbox [OPTIONS]
```

**Options**:

* `-c, --code <str>`: Execute Python code directly in the sandbox
* `-f, --file <str>`: Execute Python code from a file in the sandbox
* `--dev-mode`: Run in dev mode
* `--allow-update-session`: Allow calling update_session inside code-mode
* `-v, --var <str>`: Inject variable as key=value pair (e.g. -v project=my_project)
* `--help`: Show this message and exit.

### `lkr code-mode run`

**Usage**:

```console
$ lkr code-mode run [OPTIONS]
```

**Options**:

* `--debug / --no-debug`: Debug mode  [default: no-debug]
* `--help`: Show this message and exit.
