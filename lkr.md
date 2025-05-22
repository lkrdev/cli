# `lkr`

LookML Repository CLI

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
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `auth`: Authentication commands for LookML Repository
* `mcp`
* `observability`

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

* `--host TEXT`: Host to bind to  [env var: HOST; default: 0.0.0.0]
* `--port INTEGER`: Port to bind to  [env var: PORT; default: 8080]
* `--timeout INTEGER`: Timeout for the health check  [env var: TIMEOUT; default: 120]
* `--event-prefix TEXT`: Event prefix  [env var: EVENT_PREFIX; default: lkr-observability]
* `--help`: Show this message and exit.
