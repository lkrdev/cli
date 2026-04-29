import inspect
import io
import json
from contextlib import redirect_stdout
from typing import Optional

import typer
import pydantic_monty
from mcp.server.fastmcp import FastMCP

from lkr.auth_service import get_auth, is_auth_expired
from lkr.classes import LkrCtxObj
from lkr.codemode.examples import EXAMPLES
from lkr.codemode.help import search_help, lookup_function, search_with_lookups
from lkr.codemode.readme import get_readme
from lkr.codemode.constant import EXCLUDED_FUNCS
from lkr.codemode.type import lookup_type
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
def run_python_code(code: str, dev_mode: bool = False) -> str:
    """
    Execute Python code safely with access to all Looker SDK methods as global functions.
    Capture the result. 
    
    AGENT HINTS:
    - CRITICAL: Call `readme()` first if you haven't already to see full instructions and examples.
    - Use `dir()`, `help('pattern')`, `lookup('method_name')`, `lookup_type('TypeName')`, and `examples()` to discover available SDK methods, types, and patterns.
    - Do not instantiate an SDK; use global functions directly (e.g. `me()`).
    - You can also use `sdk.method_name()` (e.g. `sdk.me()`) if preferred.
    - Returned Looker models are primitive dictionaries (use `obj["id"]`, not `obj.id`).
    - Return your output (avoid using print() as it may pollute the stdio stream).
    - Recursion: Use `folder_children(id)` to traverse nested folders.
    - Dev Mode: Set `dev_mode=True` to ensure you are in development mode before running code.
    """
    try:
        ctx = LkrCtxObj(force_oauth=False)

        if dev_mode:
            ctx.use_production = False
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
        
        external_funcs['help'] = lambda query: search_help(query, external_funcs, sdk)
        external_funcs['lookup'] = lambda name: lookup_function(name, external_funcs, sdk)
        external_funcs['search_with_lookups'] = lambda query: search_with_lookups(query, external_funcs, sdk)
        external_funcs['lookup_type'] = lookup_type

        external_funcs['examples'] = lambda: EXAMPLES
        external_funcs['readme'] = get_readme

        # Add sdk object to support sdk.method_name
        class SDK:
            pass
        for name, func in external_funcs.items():
            if name not in EXCLUDED_FUNCS:
                setattr(SDK, name, staticmethod(func))
        external_funcs['sdk'] = SDK

        m = pydantic_monty.Monty(code)
        
        # Redirect stdout to capture any print() statements
        # and prevent them from corrupting the JSON-RPC stream
        f = io.StringIO()
        with redirect_stdout(f):
            result = m.run(external_functions=external_funcs)
        
        printed_output = f.getvalue()
        
        # m.run() returns the evaluated result of the last expression (which is already a primitive)
        try:
            # Use JSON for nice formatting if it's a dict/list
            if result is not None:
                if isinstance(result, str):
                    output = result
                else:
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





@group.command(name="run")
def run(
    ctx: typer.Context,
    debug: bool = typer.Option(False, help="Debug mode"),
):
    mcp.run()

if __name__ == "__main__":
    mcp.run("sse")
