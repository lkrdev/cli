import inspect
from typing import Optional

import typer
import pydantic_monty
from mcp.server.fastmcp import FastMCP

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.logger import logger

__all__ = ["group"]

mcp = FastMCP("lkr:codemode")
group = typer.Typer()
ctx_lkr: Optional[LkrCtxObj] = None


def get_mcp_sdk(ctx: LkrCtxObj):
    sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=True)
    sdk.auth.settings.agent_tag += "-codemode"
    return sdk


import json
from looker_sdk.rtl import serialize

def to_primitive(obj):
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, list):
        return [to_primitive(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: to_primitive(v) for k, v in obj.items()}
    else:
        try:
            return to_primitive(vars(obj))
        except TypeError:
            return str(obj)
        except Exception:
            return str(obj)


@mcp.tool()
def run_python_code(code: str) -> str:
    """
    Execute Python code safely with access to all Looker SDK methods as global functions.
    Capture the result and any print outputs.
    """
    global ctx_lkr
    if not ctx_lkr:
         ctx_lkr = LkrCtxObj(force_oauth=False)
         
    sdk = get_mcp_sdk(ctx_lkr)
    
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

    try:
        m = pydantic_monty.Monty(code)
        result = m.run(external_functions=external_funcs)
        
        # Monty run returns a MontyComplete or None
        output = str(getattr(result, "output", "")) if result is not None else ""
        
        # Try to append captured stdout if available on the object
        stdout = getattr(result, "stdout", None) if result is not None else None
        if stdout:
            return f"Output:\n{output}\nStdout:\n{stdout}"
        return output
    except Exception as e:
        logger.error(f"Error executing Monty: {e}")
        return f"Error: {str(e)}"


@group.command(name="run")
def run(
    ctx: typer.Context,
    debug: bool = typer.Option(False, help="Debug mode"),
):
    global ctx_lkr

    ctx_lkr = LkrCtxObj(force_oauth=False)
    mcp.run()

if __name__ == "__main__":
    ctx_lkr = LkrCtxObj(force_oauth=False)
    mcp.run("sse")
