import sys
import anyio
import contextlib
from io import TextIOWrapper
import mcp.server.stdio

def patch_mcp_stdio_transport(fast_mcp_instance):
    """
    Redirects sys.stdout to sys.stderr to prevent print() statements from polluting the JSON-RPC stream.
    Patches the FastMCP instance to use the original stdout buffer for the underlying transport.
    """
    # Save the original stdout for the MCP transport
    original_stdout = sys.stdout
    
    # Redirect sys.stdout to sys.stderr to prevent print() from polluting the JSON-RPC stream
    sys.stdout = sys.stderr
    
    # Wrap the original stdout buffer using anyio, exactly as FastMCP does
    wrapped_stdout = anyio.wrap_file(TextIOWrapper(original_stdout.buffer, encoding="utf-8"))
    
    # Patch FastMCP's stdio_server to use the original stdout
    original_stdio_server = mcp.server.stdio.stdio_server
    
    @contextlib.asynccontextmanager
    async def patched_stdio_server(*args, **kwargs):
        # Provide our wrapped stdout to the original server
        kwargs["stdout"] = wrapped_stdout
        async with original_stdio_server(*args, **kwargs) as streams:
            yield streams
            
    mcp.server.stdio.stdio_server = patched_stdio_server
