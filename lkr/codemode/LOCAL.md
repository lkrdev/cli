# Local Development Configuration for lkr:codemode

To run this MCP server locally from the repository (for development or testing), you can configure your MCP client (like Claude Desktop or Cursor) to use `uv run` with the `--directory` flag pointing to this project.

### Claude Desktop Configuration

Add the following to your `claude_desktop_config.json` (usually located at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "lkr_codemode_dev": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "-q",
        "run",
        "--directory",
        "/path/to/lkr/cli",
        "lkr",
        "code-mode",
        "run"
      ],
      "env": {
        "LOOKERSDK_BASE_URL": "https://your-instance.cloud.looker.com",
        "LOOKERSDK_CLIENT_ID": "your_client_id",
        "LOOKERSDK_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

> [!WARNING]
> Do NOT place the directory path directly after `run` without the `--directory` flag (e.g., `["run", "/path/to/project", ...]`). `uv` will attempt to execute the directory as a command, resulting in a `Permission denied (os error 13)` error.

> [!TIP]
> **macOS GUI Apps & PATH:** Claude Desktop and Cursor do not inherit your terminal's `PATH` environment variable. If you simply use `"uv"` as the command, the app may fail to start the server because it cannot find `uv`. Using the absolute path (e.g., `/opt/homebrew/bin/uv` or `~/.cargo/bin/uv`) ensures the IDE can launch the process. Find out your path by running `which uv` in your terminal.

### Cursor Integration

To add this local dev server to Cursor:

1. Open **Settings** (`Cmd + ,`).
2. Go to **Features** -> **MCP**.
3. Click **+ Add New MCP Server**.
4. **Name**: `Looker Codemode (Local)`
5. **Type**: `command`
6. **Command**: `uv run -q --directory /Users/bryanweber/projects/lkr/cli lkr code-mode run`

### Testing Interactively via MCP Inspector

You can test the server and its tools interactively in your browser by running the MCP inspector from your terminal:

```bash
npx @modelcontextprotocol/inspector uv run -q --directory /Users/bryanweber/projects/lkr/cli lkr code-mode run
```
