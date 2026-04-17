import inspect
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
    Capture the result and any print outputs.
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
