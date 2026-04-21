import inspect
import sys
import io
from contextlib import redirect_stdout
from typing import Optional

import typer
import pydantic_monty
from mcp.server.fastmcp import FastMCP

from lkr.auth_service import get_auth, is_auth_expired
from lkr.classes import LkrCtxObj
from lkr.logger import logger

__all__ = ["group"]

mcp = FastMCP("lkr:codemode")
group = typer.Typer()



def get_mcp_sdk(ctx: LkrCtxObj):
    sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=True)
    sdk.auth.settings.agent_tag += "-codemode"
    return sdk



def to_primitive(obj):
    seen = set()

    def _to_primitive(o):
        if isinstance(o, (str, int, float, bool, type(None))):
            return o
        
        obj_id = id(o)
        if obj_id in seen:
            return f"<Circular reference to {type(o).__name__}>"
        seen.add(obj_id)
        
        try:
            if isinstance(o, list):
                return [_to_primitive(item) for item in o]
            elif isinstance(o, dict):
                return {k: _to_primitive(v) for k, v in o.items()}
            else:
                try:
                    return _to_primitive(vars(o))
                except TypeError:
                    return str(o)
                except Exception:
                    return str(o)
        finally:
            seen.remove(obj_id)

    return _to_primitive(obj)



@mcp.tool()
def run_python_code(code: str) -> str:
    """
    Execute Python code safely with access to all Looker SDK methods as global functions.
    Capture the result. 
    
    AGENT HINTS:
    - Use `dir()` and `help('method_name')` to discover available SDK methods.
    - Do not instantiate an SDK; use global functions directly (e.g. `me()`).
    - Returned Looker models are primitive dictionaries (use `obj["id"]`, not `obj.id`).
    - Return your output (avoid using print() as it may pollute the stdio stream).
    - Recursion: Use `folder_children(id)` to traverse nested folders.
    """
    try:
        ctx = LkrCtxObj(force_oauth=False)
        sdk = get_mcp_sdk(ctx)
        
        external_funcs = {}
        for name, method in inspect.getmembers(sdk, predicate=inspect.ismethod):
            if not name.startswith('_'):
                # Wrap in a lambda to recursively convert output to primitives
                def make_wrapper(m):
                    def wrapper(*args, **kwargs):
                        res = m(*args, **kwargs)
                        return to_primitive(res)
                    return wrapper
                external_funcs[name] = make_wrapper(method)

        # Provide helper functions for the LLM to explore the SDK
        external_funcs['dir'] = lambda: list(external_funcs.keys())
        
        def _help(name: str) -> str:
            if name in external_funcs:
                if hasattr(sdk, name):
                    return getattr(sdk, name).__doc__ or "No docstring available."
                return f"{name} is a built-in helper function."
            return f"Function '{name}' not found."
        external_funcs['help'] = _help

        m = pydantic_monty.Monty(code)
        
        # Redirect stdout to capture any print() statements
        # and prevent them from corrupting the JSON-RPC stream
        f = io.StringIO()
        with redirect_stdout(f):
            result = m.run(external_functions=external_funcs)
        
        printed_output = f.getvalue()
        
        # m.run() returns the evaluated result of the last expression (which is already a primitive)
        import json
        try:
            # Use JSON for nice formatting if it's a dict/list
            if result is not None:
                output = json.dumps(result, indent=2, default=str)
            else:
                output = ""
        except Exception:
            output = repr(result)
            
        if printed_output:
            return f"PRINTED OUTPUT:\n{printed_output}\nRESULT:\n{output}"
        return output
    except Exception as e:
        logger.error(f"Error executing Monty: {e}")
        if is_auth_expired(e):
            return "Error: Your Looker OAuth session has expired. Please run 'lkr auth login' to re-authenticate."
        return f"Error: {str(e)}"


@mcp.resource("looker://agent-hints")
def get_agent_hints() -> str:
    """Crucial hints and rules for AI agents writing Python for the Looker SDK."""
    return """
1. **Global Functions**: All Looker SDK methods are global. Use `me()`, not `sdk.me()`.
2. **Dict Access**: Return values are dictionaries, not objects. Use `user["id"]`, not `user.id`.
3. **Discovery**: Use `dir()` and `help('method')` to explore the SDK.
4. **No Imports**: Do not `import looker_sdk`.
5. **Output**: Return your results instead of using `print()`.
6. **Efficiency**: Always use the `fields` parameter (e.g., `all_dashboards(fields="id,title")`) when listing many objects to prevent timeouts.
7. **Nested Folders**: Use `folder_children(id)` to get sub-folders.
"""


@mcp.prompt("explore_looker_sdk")
def explore_looker_sdk() -> str:
    """Provide examples for how to explore the Looker SDK in code mode."""
    return '''
To explore the Looker SDK, you can use the injected `dir()` and `help()` helpers.
Do not use print() as it may corrupt the MCP output stream; always return the result.

Example 1: Find all dashboard-related methods
```python
return [m for m in dir() if 'dashboard' in m.lower()]
```

Example 2: Get the description of a specific method
```python
return help('search_dashboards')
```
'''


@mcp.prompt("list_personal_dashboards")
def list_personal_dashboards() -> str:
    """Provide an example of how to recursively list dashboards in a user's personal folder."""
    return '''
Here is a robust example of how to traverse the folder hierarchy using the Looker SDK in code mode:

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

me_data = me()
return get_all_items(me_data["personal_folder_id"])
```
'''


@group.command(name="run")
def run(
    ctx: typer.Context,
    debug: bool = typer.Option(False, help="Debug mode"),
):
    mcp.run()

if __name__ == "__main__":
    mcp.run("sse")
