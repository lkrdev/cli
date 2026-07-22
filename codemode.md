# Looker Code Mode MCP Server

`lkr code-mode` allows you to invoke a Python-based Model Context Protocol (MCP) server. It offers an AI agent the unique capacity to batched-execute Python commands securely within the Monty sandbox against your active Looker instance!

## How It Works

Instead of dumping hundreds of explicit tool declarations onto your AI agent (token bloat), `lkr code-mode` exposes **exactly one tool**: `run_python_code(code: str)`. 

The tool instantiates Looker SDK natively, searches all bound methods, and passes them safely onto Monty's environment as global functions. When the LLM writes standard Python code (e.g., `me()`, `folder(id)`), Monty will process it correctly locally!

### Key Features:
- **100% Tool Coverage:** Accesses all Looker SDK public operations smoothly without token limits.
- **Recursive Translation:** Complex Looker models like User, Folder, Dashboard get string-converted into dictionaries immediately before ingesting them into Monty.
- **Automatic PKCE Restarter:** Caught an invalid token? Code Mode immediately catches `InvalidRefreshTokenError` and safely opens up your PKCE authentication browser automatically.
- **Extremely Secure:** Monty interpreter ensures isolated sandbox processing. No local filesystem accesses are exposed.

## Continuous Usage

### 1. Starting the Server
To immediately trigger the stdio listener, use:
```bash
uvx -q lkr-dev-cli[codemode] code-mode run
```

### 2. Client Configuration
To hook this server into Cursor or Claude Desktop natively over stdio, append the following onto your `mcpServers` configuration JSON. Make sure to pass your Looker instance credentials as environment variables (see standard API requirements in [README.md](./README.md#using-api-key)):

```json
{
  "mcpServers": {
    "lkr_codemode": {
      "command": "uvx",
      "args": ["-q", "lkr-dev-cli[codemode]", "code-mode", "run"],
      "env": {
        "LOOKERSDK_BASE_URL": "https://your.looker.instance",
        "LOOKERSDK_CLIENT_ID": "your-client-id",
        "LOOKERSDK_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

### 3. Visual Inspector
To check things out on a web panel:
```bash
npx @modelcontextprotocol/inspector uvx -q lkr-dev-cli[codemode] code-mode run
```

## Architectural & Troubleshooting Notes

### The stdio Stream Corruption Trap
When running an MCP server over standard input/output (`stdio`) transport, JSON-RPC packets are transmitted directly through the process's `stdout`. 

If Python code executed within the server (such as tool execution or third-party libraries) writes raw text directly to `sys.stdout` via standard `print()` calls, that raw text corrupts the JSON-RPC response stream. This causes fatal JSON parsing errors on the client (e.g., `invalid character 'C' looking for beginning of value`) and immediately closes the connection.

To safeguard against this:
1. `run_python_code` automatically wraps all Monty execution in a `redirect_stdout` block.
2. If any `print()` output is captured, it is safely packaged and returned as part of a valid JSON structure rather than polluting raw `stdout`.

