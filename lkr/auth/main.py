import builtins
from typing import Annotated, cast

import typer
from looker_sdk.rtl.auth_token import AccessToken, AuthToken
from pydantic import BaseModel

from lkr.auth.oauth import OAuth2PKCE
from lkr.auth_service import (
    ApiKeyAuthSession,
    SqlLiteAuth,
    get_auth,
    init_api_key_sdk,
    normalize_base_url,
)
from lkr.logger import logger

QUESTIONARY_AVAILABLE = True
RICH_AVAILABLE = True
try:
    import questionary
except ModuleNotFoundError:
    QUESTIONARY_AVAILABLE = False
try:
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError:
    RICH_AVAILABLE = False

__all__ = ["group"]

group = typer.Typer(name="auth", help="Authentication commands for LookML Repository")


@group.callback()
def callback(ctx: typer.Context):
    if ctx.invoked_subcommand in ("whoami", "add-access-token"):
        return
    if ctx.obj["ctx_lkr"].use_sdk == "api_key":
        logger.error("API key authentication is not supported for auth commands")
        raise typer.Exit(1)


@group.command(name="add-access-token")
def add_access_token(ctx: typer.Context):
    """Mint an access token via API key and save it to the database"""
    ctx_lkr = ctx.obj["ctx_lkr"]
    if not ctx_lkr.api_key:
        logger.error(
            "--client-id, --client-secret, and --base-url are required for add-access-token"
        )
        raise typer.Exit(1)
    ctx_lkr.api_key.base_url, _ = normalize_base_url(ctx_lkr.api_key.base_url)
    sql_auth = SqlLiteAuth(ctx_lkr)
    sdk = init_api_key_sdk(ctx_lkr.api_key, use_production=True)
    auth_session = cast(ApiKeyAuthSession, sdk.auth)
    auth_session._login({})
    if sql_auth.conn.execute(
        "DELETE FROM auth WHERE access_token = ?", (auth_session.token.access_token,)
    ).rowcount:
        sql_auth.conn.commit()
        sdk.logout()
        auth_session.use_production = ctx_lkr.use_production
        auth_session._login({})
    elif not ctx_lkr.use_production:
        auth_session._switch_to_dev_mode()
    instance_name = sql_auth.add_access_token(
        ctx_lkr.api_key.base_url, auth_session.token, ctx_lkr.use_production
    )
    logger.info(f"Saved access token for {instance_name} ({ctx_lkr.api_key.base_url})")


@group.command()
def login(
    ctx: typer.Context,
    instance_name: Annotated[
        str | None,
        typer.Option(
            "-I",
            "--instance-name",
            help="Name of the Looker instance to login or switch to",
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "-p",
            "--port",
            min=1,
            max=65535,
            help="Port to run the local OAuth redirect web server on",
        ),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            "--remote",
            help="Do not automatically open a local browser; copy the authorization code from https://www.lkr.dev/oauth/callback/",
        ),
    ] = False,
):
    """
    Login to Looker instance using OAuth2 or switch to an existing authenticated instance
    """
    auth = get_auth(ctx)
    all_instances = auth.list_auth()

    def do_switch(instance_name: str):
        auth.set_current_instance(instance_name)
        sdk = auth.get_current_sdk()
        if not sdk:
            logger.error("No looker instance currently authenticated")
            raise typer.Exit(1)
        user = sdk.me()
        workspace = sdk.session()
        logger.info(
            f"Successfully switched to {instance_name} ({sdk.auth.settings.base_url}) as {user.first_name} {user.last_name} ({user.email}) in workspace {workspace.workspace_id}"
        )

    if instance_name:
        if instance_name in [name for name, u, c, up in all_instances]:
            do_switch(instance_name)
            return
        else:
            logger.error(f"Instance '{instance_name}' not found")
            raise typer.Exit(1)
    else:
        options: builtins.list[questionary.Choice] = []
        max_name_length = 0
        for name, url, current, up in all_instances:
            max_name_length = max(max_name_length, len(name))
        options = [
            questionary.Choice(
                title=f"{name:{max_name_length}} ({url})", value=name, checked=current
            )
            for name, url, current, up in all_instances
        ]
        options.append(
            questionary.Choice(title="+ Add new instance", value="_add_new_instance")
        )
        picked = questionary.select(
            "Select instance to login/switch to", choices=options, pointer=">"
        ).ask()
        if picked != "_add_new_instance":
            do_switch(picked)
            return
        else:
            # Login flow for new instance
            base_url = typer.prompt("Enter your Looker instance base URL")
            origin, clean_netloc = normalize_base_url(base_url)
            if QUESTIONARY_AVAILABLE:
                mode = questionary.select(
                    "Do you want this instance to be used for production or development mode?",
                    choices=[
                        questionary.Choice("Development", value=False),
                        questionary.Choice("Production", value=True),
                    ],
                    pointer=">",
                ).ask()
                if mode is None:
                    raise typer.Exit()
                use_production = mode
            else:
                use_production = typer.confirm("Use production mode?", default=False)
            instance_name = typer.prompt(
                "Enter a name for this Looker instance",
                default=f"{'prod' if use_production else 'dev'}-{clean_netloc}",
            )
            # Ensure instance_name is str, not None
            assert instance_name is not None, (
                "Instance name must be set before adding auth."
            )

            def auth_callback(token: AuthToken | AccessToken):
                auth.add_auth(instance_name, origin, token, use_production)

            oauth = OAuth2PKCE(
                new_token_callback=auth_callback,
                use_production=use_production,
                port=port,
                no_browser=no_browser,
            )
            if not no_browser:
                logger.info(
                    f"Opening browser for authentication at {origin + '/auth'}..."
                )
            logger.info(
                f"Listening for OAuth callback on http://localhost:{oauth.port}/callback..."
            )
            login_response = oauth.initiate_login(origin)

            if login_response["auth_code"]:
                logger.info("Successfully received authorization code!")
                logger.debug(
                    "Exchanging authorization code for tokens at /api/token..."
                )
                try:
                    oauth.auth_code = login_response["auth_code"]
                    token = oauth.exchange_code_for_token()
                    if token:
                        logger.info("Successfully authenticated!")
                    else:
                        logger.error("Failed to exchange authorization code for tokens")
                        raise typer.Exit(1)
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        f"Failed to exchange authorization code for tokens: {e!s}"
                    )
                    raise typer.Exit(1)
            else:
                logger.error(
                    "Failed to receive authorization code from OAuth callback."
                )
                logger.debug(
                    "Check if the browser redirected correctly or if an error was returned."
                )
                raise typer.Exit(1)
            do_switch(instance_name)


@group.command()
def logout(
    ctx: typer.Context,
    instance_name: Annotated[
        str | None,
        typer.Option(
            help="Name of the Looker instance to logout from. If not provided, logs out from all instances."
        ),
    ] = None,
    all: Annotated[
        bool,
        typer.Option("--all", help="Logout from all instances"),
    ] = False,
):
    """
    Logout and clear saved credentials
    """
    auth = get_auth(ctx)
    if instance_name:
        message = f"Are you sure you want to logout from instance '{instance_name}'?"
    elif all:
        message = "Are you sure you want to logout from all instances?"
    else:
        instance_name = auth.get_current_instance()
        if not instance_name:
            logger.error("No instance currently authenticated")
            raise typer.Exit(1)
        message = f"Are you sure you want to logout from instance '{instance_name}'?"

    if not typer.confirm(message, default=False):
        logger.info("Logout cancelled")
        raise typer.Exit()

    if instance_name:
        logger.info(f"Logging out from instance: {instance_name}")
        auth.delete_auth(instance_name=instance_name)
    else:
        logger.info("Logging out from all instances...")
        all_instances = auth.list_auth()
        for instance in all_instances:
            auth.delete_auth(instance_name=instance[0])
    logger.info("Logged out successfully!")


@group.command()
def whoami(ctx: typer.Context):
    """
    Check current authentication
    """
    auth = get_auth(ctx)
    try:
        sdk = auth.get_current_sdk(prompt_refresh_invalid_token=True)
        if not sdk:
            logger.error(
                "Not currently authenticated - use `lkr auth login` or `lkr auth switch` to authenticate"
            )
            raise typer.Exit(1)
        user = sdk.me()
        session_info = sdk.session()
        
        logger.info(
            f"Currently authenticated as {user.first_name} {user.last_name} ({user.email}) to {sdk.auth.settings.base_url} in {session_info.workspace_id}"
        )
    except Exception as e:
        if "invalid_grant" in str(e) or "token expired" in str(e):
            logger.error("Your Looker OAuth session has expired. Please run 'lkr auth login' to re-authenticate.")
            raise typer.Exit(1)
        raise


@group.command()
def list(ctx: typer.Context):
    """
    List all authenticated Looker instances
    """
    console = Console() if RICH_AVAILABLE else None
    auth = get_auth(ctx)
    all_instances = auth.list_auth()
    if not all_instances:
        logger.error("No authenticated instances found")
        raise typer.Exit(1)
    table = Table(" ", "Instance", "URL", "Production")
    for instance in all_instances:
        table.add_row(
            "*" if instance[2] else " ",
            instance[0],
            instance[1],
            "Yes" if instance[3] else "No",
        )
    if console:
        console.print(table)
    else:
        print(table)


class Test(BaseModel):
    name: str
    age: int


@group.command()
def get(
    name: Annotated[str, typer.Option("--name")] = "John",
    age: Annotated[int, typer.Option("--age")] = 30,
):
    """
    get authentication
    """
    test = Test(name=name, age=age)
    print(test.model_dump_json())


@group.command()
def set(ctx: typer.Context):
    """
    put authentication
    """
    import sys

    if sys.stdin.isatty():
        logger.error(
            "This command is intended to be used with a pipe. For example: `lkr auth get | lkr auth set`"
        )
        raise typer.Exit(1)

    read = sys.stdin.read()
    test = Test.model_validate_json(read)
    print(test.model_dump_json())


if __name__ == "__main__":
    group()
