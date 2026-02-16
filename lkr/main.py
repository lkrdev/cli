import os
from typing import Annotated, Literal, Optional

import typer

from lkr.auth.main import group as auth_group
from lkr.classes import LkrCtxObj
from lkr.custom_types import LogLevel
from lkr.logger import logger

app = typer.Typer(
    name="lkr",
    help="A CLI for Looker with helpful tools",
    add_completion=True,
    no_args_is_help=True,
)

app.add_typer(auth_group, name="auth")

IMPORT_ERROR = None


def add_optional_typer_group(app, import_path, group_name, extra_message=None):
    try:
        module_path, attr = import_path.rsplit(".", 1)
        mod = __import__(module_path, fromlist=[attr])
        group = getattr(mod, attr)
        app.add_typer(group, name=group_name)
    except ModuleNotFoundError as import_error:

        @app.command(
            name=group_name,
            add_help_option=False,
            context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        )
        def fallback(import_error=import_error):
            msg = f"{group_name} tools (dependencies not available, try installing optional dependencies: lkr-dev-cli\\[{group_name}])"
            if extra_message:
                msg += f" {extra_message}"
            logger.error(msg)
            logger.error(import_error)
            raise typer.Exit(1)


add_optional_typer_group(app, "lkr.mcp.main.group", "mcp")
add_optional_typer_group(app, "lkr.observability.main.group", "observability")
add_optional_typer_group(app, "lkr.tools.main.group", "tools")


@app.callback()
def callback(
    ctx: typer.Context,
    client_id: Annotated[str | None, typer.Option()] = None,
    client_secret: Annotated[str | None, typer.Option()] = None,
    base_url: Annotated[str | None, typer.Option()] = None,
    log_level: Annotated[LogLevel | None, typer.Option(envvar="LOG_LEVEL")] = None,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
    force_oauth: Annotated[bool, typer.Option("--force-oauth")] = False,
    dev: Annotated[Optional[bool], typer.Option("--dev")] = None,
    env_prefix: Annotated[str | None, typer.Option("--env-prefix")] = "LOOKERSDK",
):
    def get_prefixed_env_var(
        var_name: Literal["CLIENT_ID", "CLIENT_SECRET", "BASE_URL"],
    ) -> str | None:
        value = os.environ.get(f"{env_prefix}_{var_name}")
        if value:
            logger.debug(f"Set {env_prefix}_{var_name} from env")
        return value

    def set_default_env_var(
        var_name: Literal["CLIENT_ID", "CLIENT_SECRET", "BASE_URL"], value: str
    ):
        if value:
            os.environ[f"LOOKERSDK_{var_name}"] = value
            logger.debug(f"Set LOOKERSDK_{var_name} from command line")

    if client_id:
        set_default_env_var("CLIENT_ID", client_id)
    elif prefixed_client := get_prefixed_env_var("CLIENT_ID"):
        set_default_env_var("CLIENT_ID", prefixed_client)

    if client_secret:
        set_default_env_var("CLIENT_SECRET", client_secret)
    elif prefixed_client_secret := get_prefixed_env_var("CLIENT_SECRET"):
        set_default_env_var("CLIENT_SECRET", prefixed_client_secret)

    if base_url:
        set_default_env_var("BASE_URL", base_url)
    elif prefixed_base_url := get_prefixed_env_var("BASE_URL"):
        set_default_env_var("BASE_URL", prefixed_base_url)

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
