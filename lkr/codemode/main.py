import inspect
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager

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
group = typer.Typer(no_args_is_help=True)
ctx_lkr: LkrCtxObj | None = None
class OSCapture:
    def __init__(self):
        self.output = ""

@contextmanager
def capture_os_stdout():
    cap = OSCapture()
    fd, temp_path = tempfile.mkstemp()
    
    if sys.stdout and hasattr(sys.stdout, "flush"):
        sys.stdout.flush()
        
    original_stdout = sys.stdout
    original_stdout_fd = os.dup(1)
    try:
        os.dup2(fd, 1)
        with os.fdopen(os.dup(1), "w") as f:
            sys.stdout = f
            yield cap
            f.flush()
    finally:
        sys.stdout = original_stdout
        os.dup2(original_stdout_fd, 1)
        os.close(original_stdout_fd)
        os.close(fd)
        
        try:
            with open(temp_path, "r") as f:
                cap.output = f.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

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
        global ctx_lkr
        ctx = (
            LkrCtxObj(
                force_oauth=ctx_lkr.force_oauth,
                use_production=ctx_lkr.use_production,
                oauth_account=ctx_lkr.oauth_account,
            )
            if ctx_lkr
            else LkrCtxObj(force_oauth=False)
        )

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

        # Monty external_functions do not support attribute lookups on objects.
        # Pre-process the code to replace `sdk.method_name` with `method_name`.
        code = re.sub(r"\bsdk\.([a-zA-Z_][a-zA-Z0-9_]*)\b", r"\1", code)

        m = pydantic_monty.Monty(code)
        
        # Use low-level OS stdout capture to ensure any print() statements
        # in Rust or sub-interpreters don't corrupt the JSON-RPC stream
        with capture_os_stdout() as cap:
            result = m.run(external_functions=external_funcs)
        
        printed_output = cap.output
        
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
            return json.dumps({
                "stdout": printed_output,
                "result": result
            }, indent=2, default=str)
        return output
    except Exception as e:
        logger.error(f"Error executing Monty: {e}")
        if is_auth_expired(e):
            return "Error: Your Looker OAuth session has expired. Please run 'lkr auth login' to re-authenticate."
        return f"Error: {str(e)}"


@group.command(name="sandbox")
def sandbox(
    ctx: typer.Context,
    code: str | None = typer.Option(
        None, "--code", "-c", help="Execute Python code directly in the sandbox"
    ),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Execute Python code from a file in the sandbox"
    ),
    dev_mode: bool = typer.Option(
        False, "--dev-mode", help="Run in dev mode"
    ),
):
    if not code and not file:
        logger.error("Must specify either --code or --file")
        raise typer.Exit(1)
        
    if code and file:
        logger.error("Cannot specify both --code and --file")
        raise typer.Exit(1)
        
    if file:
        try:
            with open(file, "r") as f:
                code_to_run = f.read()
        except Exception as e:
            logger.error(f"Failed to read file {file}: {e}")
            raise typer.Exit(1)
    else:
        code_to_run = code

    global ctx_lkr
    ctx_lkr = (
        ctx.obj.get("ctx_lkr")
        if (ctx.obj and "ctx_lkr" in ctx.obj)
        else LkrCtxObj(force_oauth=False)
    )
    result = run_python_code(code_to_run, dev_mode=dev_mode)
    typer.echo(result)


@group.command(name="run")
def run(
    ctx: typer.Context,
    debug: bool = typer.Option(False, help="Debug mode"),
):
    global ctx_lkr
    ctx_lkr = (
        ctx.obj.get("ctx_lkr")
        if (ctx.obj and "ctx_lkr" in ctx.obj)
        else LkrCtxObj(force_oauth=False)
    )
    mcp.run()

if __name__ == "__main__":
    mcp.run("sse")
