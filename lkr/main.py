import os
from typing import Annotated, Optional

import typer

from lkr.auth.main import group as auth_group
from lkr.classes import LkrCtxObj
from lkr.custom_types import LogLevel
from lkr.logger import logger
from lkr.mcp.main import group as mcp_group
from lkr.observability.main import group as observability_group

app = typer.Typer(
    name="lkr", help="LookML Repository CLI", add_completion=True, no_args_is_help=True
)

app.add_typer(auth_group, name="auth")
app.add_typer(mcp_group, name="mcp")
app.add_typer(observability_group, name="observability")


@app.callback()
def callback(
    ctx: typer.Context,
    client_id: Annotated[str | None, typer.Option(envvar="LOOKERSDK_CLIENT_ID")] = None,
    client_secret: Annotated[
        str | None, typer.Option(envvar="LOOKERSDK_CLIENT_SECRET")
    ] = None,
    base_url: Annotated[str | None, typer.Option(envvar="LOOKERSDK_BASE_URL")] = None,
    log_level: Annotated[LogLevel | None, typer.Option(envvar="LOG_LEVEL")] = None,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    force_oauth: Annotated[bool, typer.Option("--force-oauth")] = False,
    dev: Annotated[Optional[bool], typer.Option("--dev")] = None,
):
    if client_id:
        os.environ["LOOKERSDK_CLIENT_ID"] = client_id
        logger.debug("Set LOOKERSDK_CLIENT_ID from command line")
    if client_secret:
        os.environ["LOOKERSDK_CLIENT_SECRET"] = client_secret
        logger.debug("Set LOOKERSDK_CLIENT_SECRET from command line")
    if base_url:
        os.environ["LOOKERSDK_BASE_URL"] = base_url
        logger.debug("Set LOOKERSDK_BASE_URL from command line")
    # Initialize ctx.obj as a dictionary if it's None
    if ctx.obj is None:
        ctx.obj = {}

    ctx_obj = LkrCtxObj(
        force_oauth=force_oauth,
        use_production=not dev if dev is not None else True,
    )
    ctx.obj["ctx_lkr"] = ctx_obj
    # if the user passes --dev, but lkrCtxObj.use_sdk is oauth, then we need to log a warning saying we're ignoring the --dev flag
    if dev and ctx_obj.use_sdk == "oauth":
        logger.warning("Ignoring --dev flag because OAuth token tracks dev/prod mode.")

    if log_level:
        from lkr.logger import set_log_level

        set_log_level(log_level)
    if quiet:
        from lkr.logger import set_log_level

        set_log_level(LogLevel.ERROR)


if __name__ == "__main__":
    app()
