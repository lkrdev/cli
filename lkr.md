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

* `auth`: Authentication commands for LookML Repository
* `schema`: Generate and validate strongly-typed...
* `mcp`
* `observability`
* `tools`
* `code-mode`
* `parse`: Parse SQL and LookML into structured...

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
* `--no-browser, --remote`: Do not automatically open a local browser; copy the authorization code from https://www.lkr.dev/oauth/callback/
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
* `agents`: Conversational Analytics and Gemini...

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
* `create`: Create or update LookML views from...

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

#### `lkr tools lookml create`

Create or update LookML views from database tables using Looker&#x27;s generation API.

**Usage**:

```console
$ lkr tools lookml create [OPTIONS]
```

**Options**:

* `-p, --project-id, --project <str>`: Looker project ID  [required]
* `-c, --connection <str>`: Looker database connection name  [required]
* `--model <str>`: LookML model name (defaults to project ID)
* `-d, --dataset <str>`: Optional database/catalog name for views/{dataset}/{schema} folder path
* `-s, --schema <str>`: Database schema name
* `-t, --table <str>`: Table name to create or update LookML view for
* `-m, --match <str>`: Wildcard pattern to match schemas and tables (e.g. &#x27;raw.*&#x27;, &#x27;*.orders*&#x27;)
* `--folder <str>`: Target folder in Looker project for generated views
* `--branch-prefix <str>`: Branch prefix for Looker dev branch and PRs  [default: lkr-sync/]
* `--deploy / --no-deploy`: Deploy changes to production, falling back to a GitHub PR if required  [default: deploy]
* `--create-pr`: Open a GitHub PR instead of deploying directly to production
* `--allow-update-without-header`: Allow overwriting existing .view.lkml files even if they lack the # AUTOGENERATED header
* `--github-token <str>`: GitHub personal access token for opening PRs (defaults to GITHUB_TOKEN or GH_TOKEN)  [env var: GITHUB_TOKEN, GH_TOKEN]
* `--event-json <str>`: Cloud Logging BigQueryAuditMetadata or webhook event JSON payload
* `--host <str>`: Host interface to bind the HTTP webhook listener to  [env var: HOST; default: 0.0.0.0]
* `--port <int>`: Run as an HTTP webhook listener on the specified port  [env var: PORT]
* `--help`: Show this message and exit.

### `lkr tools agents`

Conversational Analytics and Gemini Enterprise agent tools

**Usage**:

```console
$ lkr tools agents [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `publish`: Publish a Looker CA agent to a Gemini...
* `delete`: Unpublish/delete a Looker CA agent from...
* `list`: List and deduplicate published agents...

#### `lkr tools agents publish`

Publish a Looker CA agent to a Gemini Enterprise app and record it in Looker Artifacts.

**Usage**:

```console
$ lkr tools agents publish [OPTIONS] {agent_id}
```

**Arguments**:

* `agent_id`: Looker Conversational Analytics Agent ID (GUID)  [required]

**Options**:

* `-p, --project-number <str>`: Google Cloud Project Number for Gemini Enterprise  [env var: GE_GCP_PROJECT_NUMBER]
* `-l, --location <str>`: Google Cloud Location for Gemini Enterprise (e.g., global, us, eu)  [env var: GE_GCP_LOCATION]
* `-e, --engine-id <str>`: Gemini Enterprise Engine / App ID  [env var: GE_ENGINE_ID]
* `--validate / --no-validate`: Validate Gemini Enterprise metadata before publishing  [default: no-validate]
* `--help`: Show this message and exit.

#### `lkr tools agents delete`

Unpublish/delete a Looker CA agent from Gemini Enterprise and update its Looker Artifact.

For secondary/multi-app Gemini Enterprise targets, pass `--gcp-token $(gcloud auth print-access-token)`.

**Usage**:

```console
$ lkr tools agents delete [OPTIONS] {agent_id}
```

**Arguments**:

* `agent_id`: Looker Conversational Analytics Agent ID (GUID)  [required]

**Options**:

* `-p, --project-number <str>`: Target Gemini Enterprise GCP Project Number (for multi-app unpublish)  [env var: GE_GCP_PROJECT_NUMBER]
* `-e, --engine-id <str>`: Target Gemini Enterprise Engine / App ID (for multi-app unpublish)  [env var: GE_ENGINE_ID]
* `--platform-agent-id <str>`: Full Discovery Engine agent resource name to delete directly
* `--gcp-token <str>`: GCP OAuth access token, e.g. --gcp-token $(gcloud auth print-access-token)  [env var: GCP_ACCESS_TOKEN]
* `--help`: Show this message and exit.

#### `lkr tools agents list`

List and deduplicate published agents across Looker and Gemini Enterprise.

To also scan Gemini Enterprise Discovery Engine across locations (global, us, eu),
pass `--project-number`, `--engine-id`, and `--gcp-token $(gcloud auth print-access-token)`.

**Usage**:

```console
$ lkr tools agents list [OPTIONS]
```

**Options**:

* `-p, --project-number <str>`: GCP Project Number to enable Discovery Engine search  [env var: GE_GCP_PROJECT_NUMBER]
* `-e, --engine-id <str>`: Comma-separated Gemini Enterprise Engine ID(s) for Discovery Engine search  [env var: GE_ENGINE_ID]
* `--gcp-token <str>`: GCP OAuth access token, e.g. --gcp-token $(gcloud auth print-access-token)  [env var: GCP_ACCESS_TOKEN]
* `--looker-api`: Scan all Looker agents sequentially via Looker API (paced at 10 req/min) when --gcp-token is omitted
* `--update-artifact / --no-update-artifact`: Sync discovered publication states (including Gemini UI deletions) back to the Looker artifact store  [default: update-artifact]
* `--json`: Output deduplicated agent publications as JSON
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

## `lkr parse`

Parse SQL and LookML into structured components

**Usage**:

```console
$ lkr parse [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `sql`: Parse semicolon-delimited SQL queries from...
* `sql-lookml-compare`: Compare and map SQL queries (--sql /...
* `lookml-to-api`: Generate Looker API all_lookml_models and...
* `lookml-database-compare`: Compile explore SQL and validate tables...
* `lookml`: Parse LookML from --path, --file, or...

### `lkr parse sql`

Parse semicolon-delimited SQL queries from --sql or --file into structured JSON.

**Usage**:

```console
$ lkr parse sql [OPTIONS]
```

**Options**:

* `-s, --sql <str>`: Inline SQL string (semicolon-delimited)
* `-f, --file <path>`: Path to SQL file (semicolon-delimited)
* `-o, --output <path>`: Optional output .json file path
* `-d, --dialect <str>`: Optional SQLGlot dialect (e.g. bigquery, snowflake)
* `--help`: Show this message and exit.

### `lkr parse sql-lookml-compare`

Compare and map SQL queries (--sql / --sql-file) to LookML views and fields (--path / --lookml-file / --lookml) with file and line numbers.

**Usage**:

```console
$ lkr parse sql-lookml-compare [OPTIONS]
```

**Options**:

* `-s, --sql <str>`: Inline SQL string (semicolon-delimited)
* `--sql-file <path>`: Path to SQL file (semicolon-delimited)
* `-p, --path <path>`: Path to a LookML directory
* `-f, --lookml-file <path>`: Path to a LookML file
* `-l, --lookml <str>`: Inline LookML string
* `-d, --dialect <str>`: Optional SQLGlot dialect (e.g. bigquery, snowflake)
* `-o, --output <path>`: Optional output .json file path
* `--describe`: Include high-level property documentation (_doc) in output JSON
* `--sql-db <str>`: Default database/project for unqualified SQL tables  [env var: LKR_SQL_DB]
* `--sql-schema <str>`: Default schema/dataset for unqualified SQL tables  [env var: LKR_SQL_SCHEMA]
* `--lkml-conn <str>`: Looker connection name override for LookML views  [env var: LKR_LKML_CONN]
* `--lkml-db <str>`: Database/project override for LookML views  [env var: LKR_LKML_DB]
* `--lkml-schema <str>`: Schema/dataset override for LookML views  [env var: LKR_LKML_SCHEMA]
* `--help`: Show this message and exit.

### `lkr parse lookml-to-api`

Generate Looker API all_lookml_models and lookml_model_explore responses from LookML.

**Usage**:

```console
$ lkr parse lookml-to-api [OPTIONS]
```

**Options**:

* `-p, --path <path>`: Path to a LookML directory
* `-f, --file <path>`: Path to a LookML file
* `-l, --lookml <str>`: Inline LookML string
* `-m, --model <str>`: Optional LookML model name filter
* `-e, --explore <str>`: Optional LookML explore name filter
* `-o, --output <path>`: Optional output .json file path
* `--help`: Show this message and exit.

### `lkr parse lookml-database-compare`

Compile explore SQL and validate tables and columns against the database.

Complements Looker&#x27;s CI/CD and `spectacles` SQL Validator: while SQL validators
verify that LookML fields generate runnable SQL across transformations, this
command checks bidirectional schema coverage—verifying both that all database
tables and columns are modeled in LookML (`unmodeled_in_lookml`) and that LookML
references exist in the database (`missing_in_database`).

**Usage**:

```console
$ lkr parse lookml-database-compare [OPTIONS]
```

**Options**:

* `-p, --path <path>`: Path to a LookML directory
* `-f, --lookml-file <path>`: Path to a LookML file
* `-l, --lookml <str>`: Inline LookML string
* `-m, --model <str>`: Filter to one or more LookML models (repeatable)
* `-e, --explore <str>`: Filter to one or more LookML explores (repeatable)
* `-c, --columns`: Include physical columns referenced on each table
* `--validate`: Compare compiled LookML tables against the database schema
* `--validate-columns`: Validate compiled tables and columns against the database schema
* `--db-schema-file <path>`: Path to JSON file containing database schema for offline validation
* `--format <console|json|txt>`: Output format: console, json, txt  [default: console]
* `-o, --output <path>`: Optional output file path
* `--help`: Show this message and exit.

### `lkr parse lookml`

Parse LookML from --path, --file, or --lookml with extensions/refinements and positions.

**Usage**:

```console
$ lkr parse lookml [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `-p, --path <path>`: Path to a LookML directory
* `-f, --file <path>`: Path to a LookML file
* `-l, --lookml <str>`: Inline LookML string
* `-o, --output <path>`: Optional output .json file path
* `--help`: Show this message and exit.

**Commands**:

* `user-attributes`: Extract all user attributes referenced in...
* `snapshot`: Jest-style LookML snapshot testing to...

#### `lkr parse lookml user-attributes`

Extract all user attributes referenced in a LookML project, LookML dashboards (.dashboard.lookml), or JSON dashboard filters with optional instance validation.

**Usage**:

```console
$ lkr parse lookml user-attributes [OPTIONS]
```

**Options**:

* `-p, --path <path>`: Path to a LookML directory (defaults to &#x27;.&#x27; when no other input is specified)
* `-f, --file <path>`: Path to a LookML or LookML dashboard (.dashboard.lookml) file
* `-l, --lookml <str>`: Inline LookML string
* `--dashboard-file <path>`: Path to a JSON file containing a Looker DashboardFilter object, a Dashboard object with dashboard_filters/dashboard_elements (e.g. looker-cli export), or a JSON array of DashboardFilter/Dashboard objects
* `--dashboard-json, --dashboard-filters <str>`: Inline JSON string containing a DashboardFilter object, a Dashboard object with dashboard_filters/dashboard_elements, or a JSON array of DashboardFilter/Dashboard objects
* `-o, --output <path>`: Optional output file path
* `--validate`: Validate user attributes against Looker instance
* `--format <str>`: Output format (text or json)  [default: text]
* `--help`: Show this message and exit.

#### `lkr parse lookml snapshot`

Jest-style LookML snapshot testing to guard tests, access controls, connections, and manifest changes.

**Usage**:

```console
$ lkr parse lookml snapshot [OPTIONS]
```

**Options**:

* `-p, --path <path>`: Path to LookML directory to snapshot  [required]
* `-u, --update`: Update snapshots in place with received data
* `--ci`: CI mode: fail on missing or mismatched snapshots without writing
* `--only <str>`: Comma-separated list of objects to snapshot (tests, access, connections, manifest)
* `-m, --model <str>`: Optional model name filter for snapshot
* `--format <console|json>`: Output format: console or json  [default: console]
* `-o, --output <path>`: Optional output file path
* `--help`: Show this message and exit.
