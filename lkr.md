# `lkr`

A CLI for Looker with helpful tools

**Usage**:

```console
$ lkr [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--client-id TEXT`: [env var: LOOKERSDK_CLIENT_ID]
* `--client-secret TEXT`: [env var: LOOKERSDK_CLIENT_SECRET]
* `--base-url TEXT`: [env var: LOOKERSDK_BASE_URL]
* `--log-level [DEBUG|INFO|WARNING|ERROR|CRITICAL]`: [env var: LOG_LEVEL]
* `--quiet`
* `--force-oauth`
* `--dev`
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `mcp`
* `observability`
* `tools`
* `code-mode`
* `auth`: Authentication commands for LookML Repository

## `lkr mcp`

**Usage**:

```console
$ lkr mcp [OPTIONS]
```

**Options**:

* `--import-error TEXT`: [default: No module named &#x27;duckdb&#x27;]

## `lkr observability`

**Usage**:

```console
$ lkr observability [OPTIONS]
```

**Options**:

* `--import-error TEXT`: [default: No module named &#x27;uvicorn&#x27;]

## `lkr tools`

**Usage**:

```console
$ lkr tools [OPTIONS]
```

**Options**:

* `--import-error TEXT`: [default: No module named &#x27;uvicorn&#x27;]

## `lkr code-mode`

**Usage**:

```console
$ lkr code-mode [OPTIONS]
```

**Options**:

* `--import-error TEXT`: [default: No module named &#x27;pydantic_monty&#x27;]

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

* `-I, --instance-name TEXT`: Name of the Looker instance to login or switch to
* `--help`: Show this message and exit.

### `lkr auth logout`

Logout and clear saved credentials

**Usage**:

```console
$ lkr auth logout [OPTIONS]
```

**Options**:

* `--instance-name TEXT`: Name of the Looker instance to logout from. If not provided, logs out from all instances.
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
