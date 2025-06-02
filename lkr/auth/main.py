import urllib.parse
from typing import Annotated, List, Union

import questionary
import typer
from looker_sdk.rtl.auth_token import AccessToken, AuthToken
from rich.console import Console
from rich.table import Table

from lkr.auth.oauth import OAuth2PKCE
from lkr.auth_service import get_auth
from lkr.logger import logger

__all__ = ["group"]

group = typer.Typer(name="auth", help="Authentication commands for LookML Repository")


@group.callback()
def callback(ctx: typer.Context):
    if ctx.invoked_subcommand == "whoami":
        return
    if ctx.obj["ctx_lkr"].use_sdk == "api_key":
        logger.error("API key authentication is not supported for auth commands")
        raise typer.Exit(1)


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
        options: List[questionary.Choice] = []
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
            base_url = (base_url or "").strip()
            if not base_url.startswith("http"):
                base_url = f"https://{base_url}"
            parsed_url = urllib.parse.urlparse(base_url)
            origin = urllib.parse.urlunparse(
                (parsed_url.scheme, parsed_url.netloc, "", "", "", "")
            )
            use_production = typer.confirm("Use production mode?", default=False)
            instance_name = typer.prompt(
                "Enter a name for this Looker instance",
                default=f"{'dev' if not use_production else 'prod'}-{parsed_url.netloc}",
            )
            # Ensure instance_name is str, not None
            assert instance_name is not None, (
                "Instance name must be set before adding auth."
            )

            def auth_callback(token: Union[AuthToken, AccessToken]):
                auth.add_auth(instance_name, origin, token, use_production)

            oauth = OAuth2PKCE(
                new_token_callback=auth_callback, use_production=use_production
            )
            logger.info(f"Opening browser for authentication at {origin + '/auth'}...")
            login_response = oauth.initiate_login(origin)

            if login_response["auth_code"]:
                logger.info("Successfully received authorization code!")
                try:
                    oauth.auth_code = login_response["auth_code"]
                    token = oauth.exchange_code_for_token()
                    if token:
                        logger.info("Successfully authenticated!")
                    else:
                        logger.error("Failed to exchange authorization code for tokens")
                        raise typer.Exit(1)
                except Exception as e:
                    logger.error(
                        f"Failed to exchange authorization code for tokens: {str(e)}"
                    )
                    raise typer.Exit(1)
            else:
                logger.error("Failed to receive authorization code")
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
    sdk = auth.get_current_sdk(prompt_refresh_invalid_token=True)
    if not sdk:
        logger.error(
            "Not currently authenticated - use `lkr auth login` or `lkr auth switch` to authenticate"
        )
        raise typer.Exit(1)
    user = sdk.me()
    logger.info(
        f"Currently authenticated as {user.first_name} {user.last_name} ({user.email}) to {sdk.auth.settings.base_url}"
    )


@group.command()
def list(ctx: typer.Context):
    """
    List all authenticated Looker instances
    """
    console = Console()
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
    console.print(table)


if __name__ == "__main__":
    group()
